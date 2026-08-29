"""Kubernetes cluster installation and configuration manager.

Orchestrates kubeadm init, kubeconfig copy, Flannel install, worker join,
node readiness polling via kr8s, namespace creation, EBS CSI driver setup,
Envoy Gateway install, Prometheus install, and OpenTelemetry Collector setup.

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11, 4.12, 4.13, 4.14, 5
"""

import asyncio
import os
import time

import kr8s
import structlog

from kasbench_runner.errors import RunnerError, SSHError
from kasbench_runner.services.ssh_client import SSHClient

logger = structlog.get_logger()

# NAMESPACES = ["globeco", "monitoring", "elasticsearch", "observability"]
# NAMESPACES = ["monitoring", "elasticsearch", "observability"]
NAMESPACES = []

# Node conditions that indicate a critical problem if persisted > 120s
CRITICAL_NOT_READY_REASONS = {"NetworkNotReady", "KubeletNotReady", "ContainerRuntimeNotReady"}

# How long a critical condition can persist before we abort (seconds)
CRITICAL_CONDITION_TIMEOUT = 120


class KubernetesError(RunnerError):
    """Kubernetes installation step failure."""

    def __init__(self, step: str, node: str | None, command: str, error_output: str):
        super().__init__(
            error="kubernetes_install_failed",
            message=f"Kubernetes installation failed at step '{step}'"
            + (f" on node '{node}'" if node else ""),
            step=step,
            node=node or "",
            command=command,
            error_output=error_output,
        )


class NodeReadinessError(RunnerError):
    """Node readiness polling failure."""

    def __init__(self, message: str, unready_nodes: dict[str, str]):
        super().__init__(
            error="node_readiness_failed",
            message=message,
            unready_nodes=unready_nodes,
        )


class KubernetesManager:
    """Manages Kubernetes cluster installation and configuration.

    Orchestrates the full cluster setup flow: kubeadm init on the control plane,
    kubeconfig copy, Flannel CNI install, worker node joins, readiness polling,
    namespace creation, and EBS CSI driver installation.
    """

    def __init__(
        self,
        ssh_client: SSHClient,
        readiness_timeout_seconds: int = 300,
        poll_interval_seconds: int = 10,
        prometheus_values_url: str = "https://raw.githubusercontent.com/kasbench/globeco-observability/v1.1.5/k8s_aws/values_prometheus.yaml",
    ) -> None:
        """Initialize KubernetesManager.

        Args:
            ssh_client: SSH client for remote command execution.
            readiness_timeout_seconds: Max time to wait for all nodes to be Ready.
            poll_interval_seconds: Interval between node readiness polls.
            prometheus_values_url: URL for the Prometheus Helm values file.
        """
        self._ssh = ssh_client
        self._readiness_timeout = readiness_timeout_seconds
        self._poll_interval = poll_interval_seconds
        self._prometheus_values_url = prometheus_values_url

    async def install_cluster(
        self,
        control_plane: str,
        amd_workers: list[str],
        arm_workers: list[str],
        k8s_version: str,
        cidr: str,
        autoscaler: str = "none",
    ) -> None:
        """Orchestrate full Kubernetes cluster installation.

        Executes all steps in sequence: kubeadm init, kubeconfig copy,
        Flannel install, token creation, worker joins, readiness wait,
        namespace creation, and EBS CSI driver setup.

        Args:
            control_plane: Hostname of the control plane node.
            amd_workers: List of AMD64 worker node hostnames.
            arm_workers: List of ARM64 worker node hostnames.
            k8s_version: Kubernetes version string (e.g. "1.36.1").
            cidr: Pod network CIDR range (e.g. "10.244.0.0/16").
            autoscaler: Autoscaler type (e.g. "vpa", "hpa", "none").

        Raises:
            KubernetesError: If any installation step fails.
            NodeReadinessError: If nodes fail to become ready within timeout.
        """
        all_workers = amd_workers + arm_workers
        expected_node_count = 1 + len(all_workers)

        logger.info(
            "kubernetes_install_starting",
            control_plane=control_plane,
            worker_count=len(all_workers),
            k8s_version=k8s_version,
            cidr=cidr,
        )

        # Step 1: kubeadm init on control plane
        await self._init_control_plane(control_plane, k8s_version, cidr)

        # Step 2: Copy kubeconfig to local
        await self._copy_kubeconfig(control_plane)

        # Step 3: Install Flannel CNI
        await self._install_flannel(control_plane)

        # Step 4: Get join token
        join_command = await self._get_join_token(control_plane)

        # Step 5: Join all workers
        await self._join_workers(all_workers, join_command)

        # Step 6: Wait for all nodes to become Ready
        await self._wait_for_nodes(expected_node_count)

        # Step 7: Create required namespaces
        await self._create_namespaces()

        # Step 8: Install EBS CSI driver and StorageClass
        await self._install_ebs_csi()

        # Step 8.5: Install EFS CSI driver
        await self._install_efs_csi()

        # Step 9: Install Envoy Gateway
        # await self._install_envoy_gateway()

        # Step 10: Install Prometheus
        await self._install_prometheus()

        # Step 11: Install OpenTelemetry Collector operator
        await self._install_otel_collector()

        # Step 12: Install Vertical Pod Autoscaler (conditional)
        if autoscaler.lower() == "vpa":
            await self._install_vpa()

        # Step 13: Install KEDA (conditional)
        if autoscaler.lower() == "keda":
            await self._install_keda()

        logger.info("kubernetes_install_completed", node_count=expected_node_count)

    async def _init_control_plane(
        self, hostname: str, k8s_version: str, cidr: str
    ) -> None:
        """Run kubeadm init on the control plane node.

        Args:
            hostname: Control plane hostname.
            k8s_version: Kubernetes version.
            cidr: Pod CIDR range.

        Raises:
            KubernetesError: If kubeadm init fails.
        """
        command = (
            f"sudo kubeadm init"
            f" --kubernetes-version={k8s_version}"
            f" --pod-network-cidr={cidr}"
        )
        try:
            await self._ssh.connect(hostname)
            await self._ssh.execute(command)
            await self._ssh.close()
        except SSHError as exc:
            await self._ssh.close()
            raise KubernetesError(
                step="kubeadm_init",
                node=hostname,
                command=command,
                error_output=exc.context.get("stderr", str(exc)),
            ) from exc

        logger.info("kubeadm_init_completed", hostname=hostname)

    async def _copy_kubeconfig(self, hostname: str) -> None:
        """Set up kubeconfig on control plane, then SCP it to local $HOME/.kube/config.

        After kubeadm init, the admin kubeconfig lives at /etc/kubernetes/admin.conf.
        This method first sets up the standard ~/.kube/config on the remote node,
        then copies it locally.

        Args:
            hostname: Control plane hostname.

        Raises:
            KubernetesError: If the remote setup or SCP operation fails.
        """
        local_kube_dir = os.path.join(os.environ.get("HOME", "/home/ubuntu"), ".kube")
        local_path = os.path.join(local_kube_dir, "config")
        remote_path = "/home/ubuntu/.kube/config"

        # Set up kubeconfig on the remote control plane node
        setup_command = (
            "mkdir -p /home/ubuntu/.kube"
            " && sudo cp /etc/kubernetes/admin.conf /home/ubuntu/.kube/config"
            " && sudo chown ubuntu:ubuntu /home/ubuntu/.kube/config"
        )
        try:
            await self._ssh.connect(hostname)
            await self._ssh.execute(setup_command)
            await self._ssh.close()
        except SSHError as exc:
            await self._ssh.close()
            raise KubernetesError(
                step="copy_kubeconfig",
                node=hostname,
                command=setup_command,
                error_output=exc.context.get("stderr", str(exc)),
            ) from exc

        logger.info("remote_kubeconfig_setup", hostname=hostname)

        # SCP the kubeconfig to local
        try:
            await self._ssh.connect(hostname)
            await self._ssh.copy_from_remote(remote_path, local_path)
            await self._ssh.close()
        except SSHError as exc:
            await self._ssh.close()
            raise KubernetesError(
                step="copy_kubeconfig",
                node=hostname,
                command=f"scp {remote_path} -> {local_path}",
                error_output=exc.context.get("stderr", str(exc)),
            ) from exc

        logger.info("kubeconfig_copied", hostname=hostname, local_path=local_path)

    async def _install_flannel(self, hostname: str) -> None:
        """Run flannel-install.sh on the control plane.

        Args:
            hostname: Control plane hostname.

        Raises:
            KubernetesError: If flannel installation fails.
        """
        command = "bash /home/ubuntu/flannel-install.sh"
        try:
            await self._ssh.connect(hostname)
            await self._ssh.execute(command)
            await self._ssh.close()
        except SSHError as exc:
            await self._ssh.close()
            raise KubernetesError(
                step="flannel_install",
                node=hostname,
                command=command,
                error_output=exc.context.get("stderr", str(exc)),
            ) from exc

        logger.info("flannel_installed", hostname=hostname)

    async def _get_join_token(self, hostname: str) -> str:
        """Get the kubeadm join command from the control plane.

        Args:
            hostname: Control plane hostname.

        Returns:
            The full kubeadm join command string.

        Raises:
            KubernetesError: If token creation fails.
        """
        command = "kubeadm token create --print-join-command"
        try:
            await self._ssh.connect(hostname)
            result = await self._ssh.execute(command)
            await self._ssh.close()
        except SSHError as exc:
            await self._ssh.close()
            raise KubernetesError(
                step="get_join_token",
                node=hostname,
                command=command,
                error_output=exc.context.get("stderr", str(exc)),
            ) from exc

        join_command = result.stdout.strip()
        logger.info("join_token_obtained", hostname=hostname)
        return join_command

    async def _join_workers(self, workers: list[str], join_command: str) -> None:
        """Join all worker nodes to the cluster.

        Args:
            workers: List of worker hostnames.
            join_command: The kubeadm join command to execute.

        Raises:
            KubernetesError: If any worker fails to join.
        """
        command = f"sudo {join_command}"
        for worker in workers:
            try:
                await self._ssh.connect(worker)
                await self._ssh.execute(command)
                await self._ssh.close()
            except SSHError as exc:
                await self._ssh.close()
                raise KubernetesError(
                    step="kubeadm_join",
                    node=worker,
                    command=command,
                    error_output=exc.context.get("stderr", str(exc)),
                ) from exc

            logger.info("worker_joined", hostname=worker)

    async def _wait_for_nodes(self, expected_count: int) -> None:
        """Poll kr8s for node readiness until all nodes are Ready or timeout.

        Logs ready count vs expected total at each poll iteration.
        Aborts early if a node has a critical not-ready condition for >120s.

        Args:
            expected_count: Total expected number of nodes (control plane + workers).

        Raises:
            NodeReadinessError: If timeout expires or a critical condition persists.
        """
        start_time = time.monotonic()
        # Track when we first see critical conditions per node
        critical_first_seen: dict[str, float] = {}

        logger.info(
            "node_readiness_polling_started",
            expected_count=expected_count,
            timeout_seconds=self._readiness_timeout,
            poll_interval=self._poll_interval,
        )

        while True:
            elapsed = time.monotonic() - start_time

            if elapsed >= self._readiness_timeout:
                # Timeout expired — report unready nodes
                unready = await self._get_unready_nodes()
                raise NodeReadinessError(
                    message=(
                        f"Node readiness timeout expired after {self._readiness_timeout}s. "
                        f"Unready nodes: {list(unready.keys())}"
                    ),
                    unready_nodes=unready,
                )

            # Get current node statuses via kr8s
            api = await kr8s.asyncio.api()
            nodes = [node async for node in api.get("nodes")]

            ready_count = 0
            current_unready: dict[str, str] = {}

            for node in nodes:
                node_name = node.name
                conditions = node.status.get("conditions", [])
                is_ready = False

                for condition in conditions:
                    if condition.get("type") == "Ready":
                        if condition.get("status") == "True":
                            is_ready = True
                            # Clear critical tracking if node recovered
                            critical_first_seen.pop(node_name, None)
                        else:
                            reason = condition.get("reason", "Unknown")
                            current_unready[node_name] = reason

                            # Check for critical conditions
                            if reason in CRITICAL_NOT_READY_REASONS:
                                if node_name not in critical_first_seen:
                                    critical_first_seen[node_name] = time.monotonic()
                                else:
                                    critical_duration = (
                                        time.monotonic() - critical_first_seen[node_name]
                                    )
                                    if critical_duration > CRITICAL_CONDITION_TIMEOUT:
                                        raise NodeReadinessError(
                                            message=(
                                                f"Node '{node_name}' has condition "
                                                f"'{reason}' for >{CRITICAL_CONDITION_TIMEOUT}s"
                                            ),
                                            unready_nodes={node_name: reason},
                                        )
                        break

                if is_ready:
                    ready_count += 1

            logger.info(
                "node_readiness_poll",
                ready_count=ready_count,
                expected_count=expected_count,
                elapsed_seconds=round(elapsed, 1),
            )

            if ready_count >= expected_count:
                logger.info(
                    "all_nodes_ready",
                    ready_count=ready_count,
                    elapsed_seconds=round(elapsed, 1),
                )
                return

            await asyncio.sleep(self._poll_interval)

    async def _get_unready_nodes(self) -> dict[str, str]:
        """Get a map of unready node names to their condition reasons."""
        unready: dict[str, str] = {}
        try:
            api = await kr8s.asyncio.api()
            nodes = [node async for node in api.get("nodes")]
            for node in nodes:
                conditions = node.status.get("conditions", [])
                for condition in conditions:
                    if condition.get("type") == "Ready":
                        if condition.get("status") != "True":
                            unready[node.name] = condition.get("reason", "Unknown")
                        break
        except Exception as exc:
            logger.warning("failed_to_get_unready_nodes", error=str(exc))
        return unready

    async def _create_namespaces(self) -> None:
        """Create required Kubernetes namespaces idempotently.

        Creates: globeco, monitoring, elasticsearch, observability.
        Skips creation if a namespace already exists.

        Raises:
            KubernetesError: If namespace creation fails.
        """
        for namespace in NAMESPACES:
            command = f"kubectl create namespace {namespace} --dry-run=client -o yaml | kubectl apply -f -"
            try:
                proc = await asyncio.create_subprocess_exec(
                    "bash",
                    "-c",
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await proc.communicate()

                if proc.returncode != 0:
                    raise KubernetesError(
                        step="create_namespace",
                        node=None,
                        command=command,
                        error_output=stderr.decode().strip(),
                    )

                logger.info("namespace_ensured", namespace=namespace)
            except KubernetesError:
                raise
            except Exception as exc:
                raise KubernetesError(
                    step="create_namespace",
                    node=None,
                    command=command,
                    error_output=str(exc),
                ) from exc

    async def _install_ebs_csi(self) -> None:
        """Install AWS EBS CSI driver via Helm and create ebs-gp3 StorageClass.

        Installs the EBS CSI driver Helm chart and creates the StorageClass
        if it does not already exist.

        Raises:
            KubernetesError: If Helm install or StorageClass creation fails.
        """
        # Add Helm repo and update
        repo_add_command = (
            "helm repo add aws-ebs-csi-driver"
            " https://kubernetes-sigs.github.io/aws-ebs-csi-driver"
            " && helm repo update"
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                "bash",
                "-c",
                repo_add_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                raise KubernetesError(
                    step="helm_install_ebs_csi",
                    node=None,
                    command=repo_add_command,
                    error_output=stderr.decode().strip(),
                )

            logger.info("helm_repo_added", repo="aws-ebs-csi-driver")
        except KubernetesError:
            raise
        except Exception as exc:
            raise KubernetesError(
                step="helm_install_ebs_csi",
                node=None,
                command=repo_add_command,
                error_output=str(exc),
            ) from exc

        # Install EBS CSI driver via Helm
        helm_command = (
            "helm upgrade --install aws-ebs-csi-driver"
            " aws-ebs-csi-driver/aws-ebs-csi-driver"
            " --namespace kube-system"
            " --set controller.replicaCount=1"
            # " --set storageClasses[0].name=ebs-sc" 
            # " --set storageClasses[0].reclaimPolicy=Delete" 
            # " --set storageClasses[0].volumeBindingMode=WaitForFirstConsumer" 
            # " --set storageClasses[0].parameters.type=gp3"
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                "bash",
                "-c",
                helm_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                raise KubernetesError(
                    step="helm_install_ebs_csi",
                    node=None,
                    command=helm_command,
                    error_output=stderr.decode().strip(),
                )

            logger.info("ebs_csi_driver_installed")
        except KubernetesError:
            raise
        except Exception as exc:
            raise KubernetesError(
                step="helm_install_ebs_csi",
                node=None,
                command=helm_command,
                error_output=str(exc),
            ) from exc

        # Create ebs-gp3 StorageClass if not exists
        storage_class_yaml = (
            "apiVersion: storage.k8s.io/v1\\n"
            "kind: StorageClass\\n"
            "metadata:\\n"
            "  name: ebs-gp3\\n"
            "provisioner: ebs.csi.aws.com\\n"
            "volumeBindingMode: WaitForFirstConsumer\\n"
            "parameters:\\n"
            "  type: gp3\\n"
            "  fsType: ext4\\n"
            "reclaimPolicy: Delete"
        )
        sc_command = f'echo -e "{storage_class_yaml}" | kubectl apply -f -'
        try:
            proc = await asyncio.create_subprocess_exec(
                "bash",
                "-c",
                sc_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                raise KubernetesError(
                    step="create_storage_class",
                    node=None,
                    command=sc_command,
                    error_output=stderr.decode().strip(),
                )

            logger.info("ebs_gp3_storage_class_ensured")
        except KubernetesError:
            raise
        except Exception as exc:
            raise KubernetesError(
                step="create_storage_class",
                node=None,
                command=sc_command,
                error_output=str(exc),
            ) from exc

    async def _install_efs_csi(self) -> None:
        """Install AWS EFS CSI driver via Helm.

        Adds the aws-efs-csi-driver Helm repo and installs the chart
        into the kube-system namespace.

        Raises:
            KubernetesError: If Helm repo add or chart install fails.
        """
        # Add Helm repo
        repo_add_command = (
            "helm repo add aws-efs-csi-driver"
            " https://kubernetes-sigs.github.io/aws-efs-csi-driver/"
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                "bash",
                "-c",
                repo_add_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                raise KubernetesError(
                    step="install_efs_csi",
                    node=None,
                    command=repo_add_command,
                    error_output=stderr.decode().strip(),
                )

            logger.info("helm_repo_added", repo="aws-efs-csi-driver")
        except KubernetesError:
            raise
        except Exception as exc:
            raise KubernetesError(
                step="install_efs_csi",
                node=None,
                command=repo_add_command,
                error_output=str(exc),
            ) from exc

        # Install EFS CSI driver via Helm
        helm_command = (
            "helm install aws-efs-csi-driver"
            " aws-efs-csi-driver/aws-efs-csi-driver"
            " -n kube-system"
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                "bash",
                "-c",
                helm_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                raise KubernetesError(
                    step="install_efs_csi",
                    node=None,
                    command=helm_command,
                    error_output=stderr.decode().strip(),
                )

            logger.info("efs_csi_driver_installed")
        except KubernetesError:
            raise
        except Exception as exc:
            raise KubernetesError(
                step="install_efs_csi",
                node=None,
                command=helm_command,
                error_output=str(exc),
            ) from exc

    async def _install_envoy_gateway(self) -> None:
        """Install Envoy Gateway via Helm OCI chart and wait for readiness.

        Raises:
            KubernetesError: If Helm install or readiness wait fails.
        """
        # Helm install
        helm_command = (
            "helm install eg oci://docker.io/envoyproxy/gateway-helm"
            " --version v1.8.2 -n envoy-gateway-system --create-namespace"
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                "bash",
                "-c",
                helm_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                raise KubernetesError(
                    step="install_envoy_gateway",
                    node=None,
                    command=helm_command,
                    error_output=stderr.decode().strip(),
                )

            logger.info("envoy_gateway_helm_installed")
        except KubernetesError:
            raise
        except Exception as exc:
            raise KubernetesError(
                step="install_envoy_gateway",
                node=None,
                command=helm_command,
                error_output=str(exc),
            ) from exc

        # Wait for readiness
        wait_command = (
            "kubectl wait --timeout=5m -n envoy-gateway-system"
            " deployment/envoy-gateway --for=condition=Available"
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                "bash",
                "-c",
                wait_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                raise KubernetesError(
                    step="install_envoy_gateway",
                    node=None,
                    command=wait_command,
                    error_output=stderr.decode().strip(),
                )

            logger.info("envoy_gateway_installed")
        except KubernetesError:
            raise
        except Exception as exc:
            raise KubernetesError(
                step="install_envoy_gateway",
                node=None,
                command=wait_command,
                error_output=str(exc),
            ) from exc

    async def _install_prometheus(self) -> None:
        """Install Prometheus via Helm with custom values file.

        Adds the prometheus-community Helm repo, updates repos, then installs
        Prometheus into the monitoring namespace using the configured values URL.

        Raises:
            KubernetesError: If Helm repo add/update or chart install fails.
        """
        # Add Helm repo and update
        repo_add_command = (
            "helm repo add prometheus-community"
            " https://prometheus-community.github.io/helm-charts"
            " && helm repo update"
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                "bash",
                "-c",
                repo_add_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                raise KubernetesError(
                    step="install_prometheus",
                    node=None,
                    command=repo_add_command,
                    error_output=stderr.decode().strip(),
                )

            logger.info("helm_repo_added", repo="prometheus-community")
        except KubernetesError:
            raise
        except Exception as exc:
            raise KubernetesError(
                step="install_prometheus",
                node=None,
                command=repo_add_command,
                error_output=str(exc),
            ) from exc

        # Install Prometheus chart
        helm_command = (
            "helm install prometheus prometheus-community/prometheus"
            f" -f {self._prometheus_values_url} -n monitoring --create-namespace "
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                "bash",
                "-c",
                helm_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                raise KubernetesError(
                    step="install_prometheus",
                    node=None,
                    command=helm_command,
                    error_output=stderr.decode().strip(),
                )

            logger.info("prometheus_installed")
        except KubernetesError:
            raise
        except Exception as exc:
            raise KubernetesError(
                step="install_prometheus",
                node=None,
                command=helm_command,
                error_output=str(exc),
            ) from exc

    # Substrings that indicate a transient, retryable failure when fetching
    # remote manifests (e.g. GitHub returning 5xx while serving release assets).
    _TRANSIENT_ERROR_MARKERS = (
        "504 gateway timeout",
        "502 bad gateway",
        "503 service unavailable",
        "500 internal server error",
        "gateway time-out",
        "gateway timeout",
        "unable to read url",
        "timeout",
        "timed out",
        "connection reset",
        "connection refused",
        "temporary failure",
        "temporarily unavailable",
        "tls handshake",
        "eof",
        "i/o timeout",
        "no such host",
        "server misbehaving",
    )

    @classmethod
    def _is_transient_error(cls, error_output: str) -> bool:
        """Return True if the error output looks like a transient network failure.

        Used to decide whether a failed remote-manifest fetch should be retried.
        """
        lowered = error_output.lower()
        return any(marker in lowered for marker in cls._TRANSIENT_ERROR_MARKERS)

    async def _run_kubectl_apply_with_retry(
        self,
        command: str,
        step: str,
        *,
        max_attempts: int = 5,
        base_backoff: float = 5.0,
        extra_retry_predicate=None,
    ) -> None:
        """Run a kubectl apply command, retrying transient failures.

        Retries up to ``max_attempts`` times using exponential backoff
        (``base_backoff`` * 2**(attempt-1): 5s, 10s, 20s, 40s, ...) when the
        command fails with a transient network error such as a GitHub 504
        Gateway Timeout while fetching a remote manifest.

        Args:
            command: The shell command to execute.
            step: Step name recorded on the raised KubernetesError.
            max_attempts: Maximum number of attempts before giving up.
            base_backoff: Base backoff in seconds for exponential backoff.
            extra_retry_predicate: Optional callable taking the lowercased
                error output and returning True to also retry on that error
                (e.g. cert-manager webhook races).

        Raises:
            KubernetesError: If the command fails on the final attempt or with
                a non-retryable error.
        """
        for attempt in range(1, max_attempts + 1):
            try:
                proc = await asyncio.create_subprocess_exec(
                    "bash",
                    "-c",
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _stdout, stderr = await proc.communicate()

                if proc.returncode == 0:
                    if attempt > 1:
                        logger.info(
                            "kubectl_apply_succeeded_after_retry",
                            step=step,
                            attempt=attempt,
                        )
                    return

                error_output = stderr.decode().strip()
                retryable = self._is_transient_error(error_output) or (
                    extra_retry_predicate is not None
                    and extra_retry_predicate(error_output.lower())
                )

                if retryable and attempt < max_attempts:
                    backoff = base_backoff * (2 ** (attempt - 1))
                    logger.warning(
                        "kubectl_apply_transient_retry",
                        step=step,
                        attempt=attempt,
                        max_attempts=max_attempts,
                        backoff_seconds=backoff,
                        error_snippet=error_output[:300],
                    )
                    await asyncio.sleep(backoff)
                    continue

                # Non-retryable error, or retries exhausted.
                raise KubernetesError(
                    step=step,
                    node=None,
                    command=command,
                    error_output=error_output,
                )
            except KubernetesError:
                raise
            except Exception as exc:
                if attempt < max_attempts:
                    backoff = base_backoff * (2 ** (attempt - 1))
                    logger.warning(
                        "kubectl_apply_exception_retry",
                        step=step,
                        attempt=attempt,
                        max_attempts=max_attempts,
                        backoff_seconds=backoff,
                        error=str(exc),
                    )
                    await asyncio.sleep(backoff)
                    continue
                raise KubernetesError(
                    step=step,
                    node=None,
                    command=command,
                    error_output=str(exc),
                ) from exc

    async def _install_otel_collector(self) -> None:
        """Install cert-manager and OpenTelemetry Operator.

        First installs cert-manager and waits for readiness, then installs
        the OpenTelemetry Operator and waits for its controller manager.

        Raises:
            KubernetesError: If any command fails.
        """
        # Install cert-manager (retries transient GitHub/network failures)
        cm_apply_cmd = (
            "kubectl apply -f"
            " https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml"
        )
        await self._run_kubectl_apply_with_retry(
            cm_apply_cmd,
            step="install_otel_collector",
        )

        # Wait for cert-manager deployments
        cm_wait_cmd = (
            "kubectl wait --for=condition=Available deployment --all"
            " -n cert-manager --timeout=360s"
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                "bash",
                "-c",
                cm_wait_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                raise KubernetesError(
                    step="install_otel_collector",
                    node=None,
                    command=cm_wait_cmd,
                    error_output=stderr.decode().strip(),
                )

            logger.info("cert_manager_deployments_available")
        except KubernetesError:
            raise
        except Exception as exc:
            raise KubernetesError(
                step="install_otel_collector",
                node=None,
                command=cm_wait_cmd,
                error_output=str(exc),
            ) from exc

        # Wait for cert-manager webhook pod to be Ready (TLS bootstrap)
        cm_webhook_wait_cmd = (
            "kubectl wait --for=condition=Ready"
            " pod -l app.kubernetes.io/component=webhook"
            " -n cert-manager --timeout=120s"
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                "bash",
                "-c",
                cm_webhook_wait_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                raise KubernetesError(
                    step="install_otel_collector",
                    node=None,
                    command=cm_webhook_wait_cmd,
                    error_output=stderr.decode().strip(),
                )

            logger.info("cert_manager_webhook_pod_ready")
        except KubernetesError:
            raise
        except Exception as exc:
            raise KubernetesError(
                step="install_otel_collector",
                node=None,
                command=cm_webhook_wait_cmd,
                error_output=str(exc),
            ) from exc

        # Probe cert-manager webhook endpoint to confirm TLS is serving.
        # Pod readiness alone doesn't guarantee the webhook is accepting connections.
        cm_webhook_probe_cmd = (
            "for i in $(seq 1 30); do"
            " if kubectl get --raw"
            " /api/v1/namespaces/cert-manager/services/cert-manager-webhook:https/proxy/livez"
            " 2>/dev/null; then exit 0; fi;"
            " sleep 5;"
            " done; exit 1"
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                "bash",
                "-c",
                cm_webhook_probe_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                logger.warning(
                    "cert_manager_webhook_probe_failed",
                    stderr=stderr.decode().strip()[:500],
                )
                # Fall through — the retry logic below will handle transient failures
            else:
                logger.info("cert_manager_webhook_serving")
        except Exception as exc:
            logger.warning("cert_manager_webhook_probe_exception", error=str(exc))

        logger.info("cert_manager_installed")

        # Install OTel operator. Retries transient GitHub/network failures
        # (e.g. 504 Gateway Timeout fetching the release manifest) as well as
        # the cert-manager webhook readiness race condition.
        otel_apply_cmd = (
            "kubectl apply -f"
            " https://github.com/open-telemetry/opentelemetry-operator/releases/latest/download/opentelemetry-operator.yaml"
        )
        await self._run_kubectl_apply_with_retry(
            otel_apply_cmd,
            step="install_otel_collector",
            extra_retry_predicate=lambda err: "webhook" in err,
        )
        logger.info("otel_operator_applied")

        # Wait for OTel operator
        otel_wait_cmd = (
            "kubectl wait --for=condition=Available"
            " deployment/opentelemetry-operator-controller-manager"
            " -n opentelemetry-operator-system --timeout=360s"
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                "bash",
                "-c",
                otel_wait_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                raise KubernetesError(
                    step="install_otel_collector",
                    node=None,
                    command=otel_wait_cmd,
                    error_output=stderr.decode().strip(),
                )

            logger.info("otel_collector_installed")
        except KubernetesError:
            raise
        except Exception as exc:
            raise KubernetesError(
                step="install_otel_collector",
                node=None,
                command=otel_wait_cmd,
                error_output=str(exc),
            ) from exc

    async def _install_vpa(self) -> None:
        """Install Kubernetes Vertical Pod Autoscaler (VPA).

        Clones the autoscaler repository, checks out the latest VPA release
        branch, and runs the vpa-up.sh installation script which deploys VPA
        components into the kube-system namespace.

        Reference: https://github.com/kubernetes/autoscaler/blob/master/vertical-pod-autoscaler/docs/installation.md

        Raises:
            KubernetesError: If cloning, checkout, or vpa-up.sh fails.
        """
        # Clone the autoscaler repository
        clone_command = (
            "rm -rf /tmp/autoscaler"
            " && git clone https://github.com/kubernetes/autoscaler.git /tmp/autoscaler"
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                "bash",
                "-c",
                clone_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                raise KubernetesError(
                    step="install_vpa",
                    node=None,
                    command=clone_command,
                    error_output=stderr.decode().strip(),
                )

            logger.info("vpa_repo_cloned")
        except KubernetesError:
            raise
        except Exception as exc:
            raise KubernetesError(
                step="install_vpa",
                node=None,
                command=clone_command,
                error_output=str(exc),
            ) from exc

        # Run vpa-up.sh from the vertical-pod-autoscaler directory
        vpa_up_command = "cd /tmp/autoscaler/vertical-pod-autoscaler && ./hack/vpa-up.sh"
        try:
            proc = await asyncio.create_subprocess_exec(
                "bash",
                "-c",
                vpa_up_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                raise KubernetesError(
                    step="install_vpa",
                    node=None,
                    command=vpa_up_command,
                    error_output=stderr.decode().strip(),
                )

            logger.info("vpa_installed")
        except KubernetesError:
            raise
        except Exception as exc:
            raise KubernetesError(
                step="install_vpa",
                node=None,
                command=vpa_up_command,
                error_output=str(exc),
            ) from exc

        # Wait for VPA components to be ready in kube-system
        wait_command = (
            "kubectl wait --for=condition=Available"
            " deployment/vpa-admission-controller"
            " deployment/vpa-recommender"
            " deployment/vpa-updater"
            " -n kube-system --timeout=300s"
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                "bash",
                "-c",
                wait_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                raise KubernetesError(
                    step="install_vpa",
                    node=None,
                    command=wait_command,
                    error_output=stderr.decode().strip(),
                )

            logger.info("vpa_components_ready")
        except KubernetesError:
            raise
        except Exception as exc:
            raise KubernetesError(
                step="install_vpa",
                node=None,
                command=wait_command,
                error_output=str(exc),
            ) from exc

    async def _install_keda(self) -> None:
        """Install KEDA (Kubernetes Event-Driven Autoscaling) via Helm.

        Adds the kedacore Helm repository, updates repos, and installs the
        KEDA Helm chart (which includes CRDs) into the keda namespace.

        Reference: https://keda.sh/docs/2.20/deploy/

        Raises:
            KubernetesError: If Helm repo add/update or chart install fails.
        """
        # Add KEDA Helm repo and update
        repo_add_command = (
            "helm repo add kedacore https://kedacore.github.io/charts"
            " && helm repo update"
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                "bash",
                "-c",
                repo_add_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                raise KubernetesError(
                    step="install_keda",
                    node=None,
                    command=repo_add_command,
                    error_output=stderr.decode().strip(),
                )

            logger.info("helm_repo_added", repo="kedacore")
        except KubernetesError:
            raise
        except Exception as exc:
            raise KubernetesError(
                step="install_keda",
                node=None,
                command=repo_add_command,
                error_output=str(exc),
            ) from exc

        # Install KEDA chart (includes CRDs)
        helm_command = (
            "helm install keda kedacore/keda"
            " --namespace keda --create-namespace"
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                "bash",
                "-c",
                helm_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                raise KubernetesError(
                    step="install_keda",
                    node=None,
                    command=helm_command,
                    error_output=stderr.decode().strip(),
                )

            logger.info("keda_helm_installed")
        except KubernetesError:
            raise
        except Exception as exc:
            raise KubernetesError(
                step="install_keda",
                node=None,
                command=helm_command,
                error_output=str(exc),
            ) from exc

        # Wait for KEDA operator to be ready
        wait_command = (
            "kubectl wait --for=condition=Available"
            " deployment/keda-operator"
            " -n keda --timeout=300s"
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                "bash",
                "-c",
                wait_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                raise KubernetesError(
                    step="install_keda",
                    node=None,
                    command=wait_command,
                    error_output=stderr.decode().strip(),
                )

            logger.info("keda_installed")
        except KubernetesError:
            raise
        except Exception as exc:
            raise KubernetesError(
                step="install_keda",
                node=None,
                command=wait_command,
                error_output=str(exc),
            ) from exc
