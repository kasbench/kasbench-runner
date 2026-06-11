"""Kubernetes cluster installation and configuration manager.

Orchestrates kubeadm init, kubeconfig copy, Flannel install, worker join,
node readiness polling via kr8s, namespace creation, and EBS CSI driver setup.

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11, 4.12, 4.13, 4.14
"""

import asyncio
import os
import time

import kr8s
import structlog

from kasbench_runner.errors import RunnerError, SSHError
from kasbench_runner.services.ssh_client import SSHClient

logger = structlog.get_logger()

NAMESPACES = ["globeco", "monitoring", "elasticsearch", "observability"]

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
    ) -> None:
        """Initialize KubernetesManager.

        Args:
            ssh_client: SSH client for remote command execution.
            readiness_timeout_seconds: Max time to wait for all nodes to be Ready.
            poll_interval_seconds: Interval between node readiness polls.
        """
        self._ssh = ssh_client
        self._readiness_timeout = readiness_timeout_seconds
        self._poll_interval = poll_interval_seconds

    async def install_cluster(
        self,
        control_plane: str,
        amd_workers: list[str],
        arm_workers: list[str],
        k8s_version: str,
        cidr: str,
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
        local_kube_dir = os.path.join(os.environ.get("HOME", "/root"), ".kube")
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
            nodes = await api.get("nodes")

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
            nodes = await api.get("nodes")
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
        # Install EBS CSI driver via Helm
        helm_command = (
            "helm upgrade --install aws-ebs-csi-driver"
            " aws-ebs-csi-driver/aws-ebs-csi-driver"
            " --namespace kube-system"
            " --set controller.replicaCount=1"
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
            "  fsType: ext4"
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
