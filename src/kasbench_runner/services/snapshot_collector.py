"""Kubernetes cluster state snapshot collector.

Captures comprehensive cluster state (resource manifests, metadata,
descriptions, events, raw API responses) and uploads all files to S3
with integrity verification via SHA-256 checksums.

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10,
              3.11, 3.12, 3.13, 3.14, 3.15, 3.16
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

import kr8s
import structlog
import yaml

from kasbench_runner.errors import (
    InvalidPhaseError,
    SnapshotCollectionError,
)
from kasbench_runner.services.s3_client import S3Client, S3OperationError

logger = structlog.get_logger()


@dataclass(frozen=True)
class SnapshotResult:
    """Result of a snapshot collection operation."""

    files_uploaded: int
    s3_prefix: str


class SnapshotCollector:
    """Collects Kubernetes cluster state and uploads to S3."""

    REQUIRED_METADATA_FILES: list[str] = [
        "metadata/date.txt",
        "metadata/kubectl-version.yaml",
        "metadata/context.txt",
        "metadata/cluster-info.txt",
        "metadata/api-resources.txt",
    ]

    REQUIRED_RESOURCE_FILES: list[str] = [
        "resources/nodes.yaml",
        "resources/pods.yaml",
        "resources/pods-wide.txt",
        "resources/workloads.yaml",
        "resources/autoscaling.yaml",
        "resources/network.yaml",
        "resources/storage.yaml",
        "resources/policies.yaml",
        "resources/configmaps.yaml",
        "resources/webhooks.yaml",
    ]

    OPTIONAL_CRD_FILES: list[str] = [
        "resources/vpa.yaml",
        "resources/keda.yaml",
        "resources/gateway-api.yaml",
    ]

    def __init__(self, s3_client: S3Client) -> None:
        """Initialize with an S3Client instance."""
        self._s3_client = s3_client

    async def collect_snapshot(
        self,
        phase: str,
        run_identifier: str,
        trial_identifier: str,
    ) -> SnapshotResult:
        """Collect full cluster snapshot and upload to S3.

        Args:
            phase: "pre" or "post".
            run_identifier: Run ID for S3 path.
            trial_identifier: Trial ID for S3 path.

        Returns:
            SnapshotResult with files_uploaded and s3_prefix.

        Raises:
            InvalidPhaseError: Phase not "pre" or "post".
            SnapshotCollectionError: Required K8s API call failed.
            S3OperationError: Required S3 upload failed.
        """
        if phase not in ("pre", "post"):
            raise InvalidPhaseError(phase=phase)

        prefix = f"{run_identifier}/{trial_identifier}/snapshot/{phase}"
        timestamp = datetime.now(timezone.utc).isoformat()
        all_files: dict[str, bytes] = {}

        # Collect required sections (raises on failure)
        all_files.update(await self._collect_metadata())
        all_files.update(await self._collect_resources())
        all_files.update(await self._collect_descriptions())
        all_files.update(await self._collect_events())
        all_files.update(await self._collect_raw_endpoints())

        # Collect optional CRDs (logs warning on failure)
        all_files.update(await self._collect_optional_crds())

        # Prepend headers to all files
        for path, content in all_files.items():
            all_files[path] = self._prepend_header(content, label=path, timestamp=timestamp)

        # Compute and add SHA256SUMS
        all_files["SHA256SUMS"] = self._compute_sha256sums(all_files)

        # Upload to S3 - SHA256SUMS last as completeness indicator
        files_to_upload = {k: v for k, v in all_files.items() if k != "SHA256SUMS"}
        optional_paths = set(self.OPTIONAL_CRD_FILES)

        for path, content in files_to_upload.items():
            s3_key = f"{prefix}/{path}"
            content_type = self._guess_content_type(path)
            try:
                await self._s3_client.upload_bytes(s3_key, content, content_type)
            except S3OperationError:
                if path in optional_paths:
                    logger.warning(
                        "snapshot_optional_upload_failed",
                        path=path,
                        s3_key=s3_key,
                    )
                else:
                    raise

        # Upload SHA256SUMS last
        sha_key = f"{prefix}/SHA256SUMS"
        await self._s3_client.upload_bytes(sha_key, all_files["SHA256SUMS"], "text/plain")

        logger.info(
            "snapshot_upload_complete",
            prefix=prefix,
            files_uploaded=len(all_files),
        )

        return SnapshotResult(files_uploaded=len(all_files), s3_prefix=prefix)

    async def _collect_metadata(self) -> dict[str, bytes]:
        """Collect metadata files.

        Gathers: date.txt, kubectl-version.yaml, context.txt,
        cluster-info.txt, api-resources.txt.

        Returns:
            Dict mapping relative path to content bytes.

        Raises:
            SnapshotCollectionError: If any metadata collection fails.
        """
        files: dict[str, bytes] = {}

        try:
            api = await kr8s.asyncio.api()
        except Exception as exc:
            raise SnapshotCollectionError(
                resource="metadata/api-connection",
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            ) from exc

        # date.txt - UTC timestamp
        try:
            date_content = datetime.now(timezone.utc).isoformat()
            files["metadata/date.txt"] = date_content.encode("utf-8")
        except Exception as exc:
            raise SnapshotCollectionError(
                resource="metadata/date.txt",
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            ) from exc

        # kubectl-version.yaml - server version info
        try:
            version = await api.version()
            version_yaml = yaml.dump(version, default_flow_style=False)
            files["metadata/kubectl-version.yaml"] = version_yaml.encode("utf-8")
        except Exception as exc:
            raise SnapshotCollectionError(
                resource="metadata/kubectl-version.yaml",
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            ) from exc

        # context.txt - current context name
        try:
            context_name = api._url or "unknown"
            files["metadata/context.txt"] = str(context_name).encode("utf-8")
        except Exception as exc:
            raise SnapshotCollectionError(
                resource="metadata/context.txt",
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            ) from exc

        # cluster-info.txt - cluster endpoint
        try:
            cluster_info = f"Kubernetes control plane: {api._url or 'unknown'}"
            files["metadata/cluster-info.txt"] = cluster_info.encode("utf-8")
        except Exception as exc:
            raise SnapshotCollectionError(
                resource="metadata/cluster-info.txt",
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            ) from exc

        # api-resources.txt - available API resources
        try:
            resources = await api.api_resources()
            lines = []
            for resource in resources:
                name = resource.get("name", "")
                kind = resource.get("kind", "")
                namespaced = resource.get("namespaced", False)
                api_version = resource.get("apiVersion", "")
                lines.append(f"{name}\t{kind}\t{namespaced}\t{api_version}")
            content = "NAME\tKIND\tNAMESPACED\tAPI_VERSION\n"
            content += "\n".join(lines)
            files["metadata/api-resources.txt"] = content.encode("utf-8")
        except Exception as exc:
            raise SnapshotCollectionError(
                resource="metadata/api-resources.txt",
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            ) from exc

        return files

    async def _collect_resources(self) -> dict[str, bytes]:
        """Collect required resource manifests.

        Gathers: nodes, pods, pods-wide, workloads, autoscaling,
        network, storage, policies, configmaps, webhooks.

        Returns:
            Dict mapping relative path to content bytes.

        Raises:
            SnapshotCollectionError: If any required resource collection fails.
        """
        files: dict[str, bytes] = {}

        try:
            api = await kr8s.asyncio.api()
        except Exception as exc:
            raise SnapshotCollectionError(
                resource="resources/api-connection",
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            ) from exc

        # nodes.yaml
        try:
            nodes = [n async for n in api.get("nodes")]
            nodes_data = [n.raw for n in nodes]
            files["resources/nodes.yaml"] = yaml.dump(
                {"items": nodes_data}, default_flow_style=False
            ).encode("utf-8")
        except Exception as exc:
            raise SnapshotCollectionError(
                resource="resources/nodes.yaml",
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            ) from exc

        # pods.yaml
        try:
            pods = [p async for p in api.get("pods", namespace=kr8s.ALL)]
            pods_data = [p.raw for p in pods]
            files["resources/pods.yaml"] = yaml.dump(
                {"items": pods_data}, default_flow_style=False
            ).encode("utf-8")
        except Exception as exc:
            raise SnapshotCollectionError(
                resource="resources/pods.yaml",
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            ) from exc

        # pods-wide.txt - table-like output
        try:
            lines = ["NAMESPACE\tNAME\tREADY\tSTATUS\tRESTARTS\tIP\tNODE"]
            for pod in pods:
                ns = pod.namespace
                name = pod.name
                status_phase = pod.status.get("phase", "Unknown")
                pod_ip = pod.status.get("podIP", "<none>")
                node_name = pod.raw.get("spec", {}).get("nodeName", "<none>")
                # Calculate ready count
                container_statuses = pod.status.get("containerStatuses", [])
                ready_count = sum(
                    1 for cs in container_statuses if cs.get("ready", False)
                )
                total_count = len(
                    pod.raw.get("spec", {}).get("containers", [])
                )
                ready_str = f"{ready_count}/{total_count}"
                # Calculate restarts
                restarts = sum(
                    cs.get("restartCount", 0) for cs in container_statuses
                )
                lines.append(
                    f"{ns}\t{name}\t{ready_str}\t{status_phase}\t{restarts}\t{pod_ip}\t{node_name}"
                )
            files["resources/pods-wide.txt"] = "\n".join(lines).encode("utf-8")
        except Exception as exc:
            raise SnapshotCollectionError(
                resource="resources/pods-wide.txt",
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            ) from exc

        # workloads.yaml - deployments, statefulsets, daemonsets, replicasets, jobs, cronjobs
        try:
            workloads: list[dict] = []
            for kind in ["deployments", "statefulsets", "daemonsets", "replicasets", "jobs", "cronjobs"]:
                items = [r async for r in api.get(kind, namespace=kr8s.ALL)]
                workloads.extend([r.raw for r in items])
            files["resources/workloads.yaml"] = yaml.dump(
                {"items": workloads}, default_flow_style=False
            ).encode("utf-8")
        except Exception as exc:
            raise SnapshotCollectionError(
                resource="resources/workloads.yaml",
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            ) from exc

        # autoscaling.yaml - HPAs
        try:
            hpas = [r async for r in api.get("horizontalpodautoscalers", namespace=kr8s.ALL)]
            files["resources/autoscaling.yaml"] = yaml.dump(
                {"items": [r.raw for r in hpas]}, default_flow_style=False
            ).encode("utf-8")
        except Exception as exc:
            raise SnapshotCollectionError(
                resource="resources/autoscaling.yaml",
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            ) from exc

        # network.yaml - services, endpoints, endpointslices, ingresses, networkpolicies
        try:
            network_items: list[dict] = []
            for kind in ["services", "endpoints", "endpointslices", "ingresses", "networkpolicies"]:
                items = [r async for r in api.get(kind, namespace=kr8s.ALL)]
                network_items.extend([r.raw for r in items])
            files["resources/network.yaml"] = yaml.dump(
                {"items": network_items}, default_flow_style=False
            ).encode("utf-8")
        except Exception as exc:
            raise SnapshotCollectionError(
                resource="resources/network.yaml",
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            ) from exc

        # storage.yaml - PVCs, PVs, storageclasses, volumeattachments
        try:
            storage_items: list[dict] = []
            for kind in ["persistentvolumeclaims", "persistentvolumes", "storageclasses", "volumeattachments"]:
                if kind in ("persistentvolumes", "storageclasses", "volumeattachments"):
                    # Cluster-scoped resources
                    items = [r async for r in api.get(kind)]
                else:
                    items = [r async for r in api.get(kind, namespace=kr8s.ALL)]
                storage_items.extend([r.raw for r in items])
            files["resources/storage.yaml"] = yaml.dump(
                {"items": storage_items}, default_flow_style=False
            ).encode("utf-8")
        except Exception as exc:
            raise SnapshotCollectionError(
                resource="resources/storage.yaml",
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            ) from exc

        # policies.yaml - resourcequotas, limitranges, poddisruptionbudgets
        try:
            policy_items: list[dict] = []
            for kind in ["resourcequotas", "limitranges", "poddisruptionbudgets"]:
                items = [r async for r in api.get(kind, namespace=kr8s.ALL)]
                policy_items.extend([r.raw for r in items])
            files["resources/policies.yaml"] = yaml.dump(
                {"items": policy_items}, default_flow_style=False
            ).encode("utf-8")
        except Exception as exc:
            raise SnapshotCollectionError(
                resource="resources/policies.yaml",
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            ) from exc

        # configmaps.yaml
        try:
            configmaps = [r async for r in api.get("configmaps", namespace=kr8s.ALL)]
            files["resources/configmaps.yaml"] = yaml.dump(
                {"items": [r.raw for r in configmaps]}, default_flow_style=False
            ).encode("utf-8")
        except Exception as exc:
            raise SnapshotCollectionError(
                resource="resources/configmaps.yaml",
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            ) from exc

        # webhooks.yaml - validatingwebhookconfigurations, mutatingwebhookconfigurations
        try:
            webhook_items: list[dict] = []
            for kind in ["validatingwebhookconfigurations", "mutatingwebhookconfigurations"]:
                items = [r async for r in api.get(kind)]
                webhook_items.extend([r.raw for r in items])
            files["resources/webhooks.yaml"] = yaml.dump(
                {"items": webhook_items}, default_flow_style=False
            ).encode("utf-8")
        except Exception as exc:
            raise SnapshotCollectionError(
                resource="resources/webhooks.yaml",
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            ) from exc

        return files

    async def _collect_descriptions(self) -> dict[str, bytes]:
        """Collect detailed resource descriptions for nodes and pods.

        Returns:
            Dict mapping relative path to content bytes.

        Raises:
            SnapshotCollectionError: If description collection fails.
        """
        files: dict[str, bytes] = {}

        try:
            api = await kr8s.asyncio.api()
        except Exception as exc:
            raise SnapshotCollectionError(
                resource="descriptions/api-connection",
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            ) from exc

        # descriptions/nodes.txt - detailed node descriptions
        try:
            nodes = [n async for n in api.get("nodes")]
            lines = []
            for node in nodes:
                raw = node.raw
                name = raw.get("metadata", {}).get("name", "unknown")
                lines.append(f"Name: {name}")
                lines.append(f"Labels: {raw.get('metadata', {}).get('labels', {})}")
                lines.append(f"Annotations: {raw.get('metadata', {}).get('annotations', {})}")
                conditions = raw.get("status", {}).get("conditions", [])
                lines.append("Conditions:")
                for cond in conditions:
                    lines.append(
                        f"  {cond.get('type')}: {cond.get('status')} "
                        f"(reason: {cond.get('reason', 'N/A')}, "
                        f"message: {cond.get('message', 'N/A')})"
                    )
                addresses = raw.get("status", {}).get("addresses", [])
                lines.append("Addresses:")
                for addr in addresses:
                    lines.append(f"  {addr.get('type')}: {addr.get('address')}")
                capacity = raw.get("status", {}).get("capacity", {})
                lines.append(f"Capacity: {capacity}")
                allocatable = raw.get("status", {}).get("allocatable", {})
                lines.append(f"Allocatable: {allocatable}")
                lines.append("---")
            files["descriptions/nodes.txt"] = "\n".join(lines).encode("utf-8")
        except Exception as exc:
            raise SnapshotCollectionError(
                resource="descriptions/nodes.txt",
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            ) from exc

        # descriptions/pods.txt - detailed pod descriptions
        try:
            pods = [p async for p in api.get("pods", namespace=kr8s.ALL)]
            lines = []
            for pod in pods:
                raw = pod.raw
                name = raw.get("metadata", {}).get("name", "unknown")
                namespace = raw.get("metadata", {}).get("namespace", "default")
                lines.append(f"Name: {name}")
                lines.append(f"Namespace: {namespace}")
                lines.append(f"Labels: {raw.get('metadata', {}).get('labels', {})}")
                lines.append(f"Node: {raw.get('spec', {}).get('nodeName', '<none>')}")
                lines.append(f"Status: {raw.get('status', {}).get('phase', 'Unknown')}")
                lines.append(f"IP: {raw.get('status', {}).get('podIP', '<none>')}")
                containers = raw.get("spec", {}).get("containers", [])
                lines.append("Containers:")
                for container in containers:
                    lines.append(f"  {container.get('name')}:")
                    lines.append(f"    Image: {container.get('image', 'N/A')}")
                    resources = container.get("resources", {})
                    lines.append(f"    Requests: {resources.get('requests', {})}")
                    lines.append(f"    Limits: {resources.get('limits', {})}")
                conditions = raw.get("status", {}).get("conditions", [])
                lines.append("Conditions:")
                for cond in conditions:
                    lines.append(
                        f"  {cond.get('type')}: {cond.get('status')}"
                    )
                lines.append("---")
            files["descriptions/pods.txt"] = "\n".join(lines).encode("utf-8")
        except Exception as exc:
            raise SnapshotCollectionError(
                resource="descriptions/pods.txt",
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            ) from exc

        return files

    async def _collect_events(self) -> dict[str, bytes]:
        """Collect cluster events.

        Gathers all events and warning-only events separately.

        Returns:
            Dict mapping relative path to content bytes.

        Raises:
            SnapshotCollectionError: If event collection fails.
        """
        files: dict[str, bytes] = {}

        try:
            api = await kr8s.asyncio.api()
            events = [e async for e in api.get("events", namespace=kr8s.ALL)]

            # events/all.yaml - all events
            all_events_data = [e.raw for e in events]
            files["events/all.yaml"] = yaml.dump(
                {"items": all_events_data}, default_flow_style=False
            ).encode("utf-8")

            # events/warnings.yaml - warning-only events
            warning_events = [
                e.raw for e in events if e.raw.get("type") == "Warning"
            ]
            files["events/warnings.yaml"] = yaml.dump(
                {"items": warning_events}, default_flow_style=False
            ).encode("utf-8")

        except Exception as exc:
            raise SnapshotCollectionError(
                resource="events",
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            ) from exc

        return files

    async def _collect_raw_endpoints(self) -> dict[str, bytes]:
        """Collect raw API endpoint responses.

        Gathers /readyz, /livez, node-metrics, pod-metrics.

        Returns:
            Dict mapping relative path to content bytes.

        Raises:
            SnapshotCollectionError: If endpoint collection fails.
        """
        files: dict[str, bytes] = {}

        try:
            api = await kr8s.asyncio.api()
        except Exception as exc:
            raise SnapshotCollectionError(
                resource="raw/api-connection",
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            ) from exc

        # /readyz?verbose
        try:
            async with api.call_api("GET", base="/readyz?verbose", version="") as response:
                files["raw/readyz.txt"] = response.content
        except Exception as exc:
            raise SnapshotCollectionError(
                resource="raw/readyz.txt",
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            ) from exc

        # /livez?verbose
        try:
            async with api.call_api("GET", base="/livez?verbose", version="") as response:
                files["raw/livez.txt"] = response.content
        except Exception as exc:
            raise SnapshotCollectionError(
                resource="raw/livez.txt",
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            ) from exc

        # node-metrics
        try:
            async with api.call_api(
                "GET", base="/apis/metrics.k8s.io/v1beta1/nodes", version=""
            ) as response:
                files["raw/node-metrics.json"] = response.content
        except Exception as exc:
            raise SnapshotCollectionError(
                resource="raw/node-metrics.json",
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            ) from exc

        # pod-metrics
        try:
            async with api.call_api(
                "GET", base="/apis/metrics.k8s.io/v1beta1/pods", version=""
            ) as response:
                files["raw/pod-metrics.json"] = response.content
        except Exception as exc:
            raise SnapshotCollectionError(
                resource="raw/pod-metrics.json",
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            ) from exc

        return files

    async def _collect_optional_crds(self) -> dict[str, bytes]:
        """Attempt to collect optional CRD resources.

        Collects VPA, KEDA, and Gateway API resources. Logs a warning
        and continues on failure for each — these are not required.

        Returns:
            Dict mapping relative path to content bytes (only for
            successfully collected resources).
        """
        files: dict[str, bytes] = {}

        try:
            api = await kr8s.asyncio.api()
        except Exception as exc:
            logger.warning(
                "snapshot_optional_crds_api_unavailable",
                error=str(exc),
            )
            return files

        # VPA - VerticalPodAutoscalers
        try:
            vpas = [
                r async for r in api.get(
                    "verticalpodautoscalers.autoscaling.k8s.io",
                    namespace=kr8s.ALL,
                )
            ]
            files["resources/vpa.yaml"] = yaml.dump(
                {"items": [r.raw for r in vpas]}, default_flow_style=False
            ).encode("utf-8")
        except Exception as exc:
            logger.warning(
                "snapshot_optional_crd_failed",
                resource="resources/vpa.yaml",
                error=str(exc),
            )

        # KEDA - ScaledObjects and ScaledJobs
        try:
            keda_items: list[dict] = []
            for kind in ["scaledobjects.keda.sh", "scaledjobs.keda.sh"]:
                items = [r async for r in api.get(kind, namespace=kr8s.ALL)]
                keda_items.extend([r.raw for r in items])
            files["resources/keda.yaml"] = yaml.dump(
                {"items": keda_items}, default_flow_style=False
            ).encode("utf-8")
        except Exception as exc:
            logger.warning(
                "snapshot_optional_crd_failed",
                resource="resources/keda.yaml",
                error=str(exc),
            )

        # Gateway API - gateways, httproutes, gatewayclasses
        try:
            gateway_items: list[dict] = []
            for kind in [
                "gateways.gateway.networking.k8s.io",
                "httproutes.gateway.networking.k8s.io",
                "gatewayclasses.gateway.networking.k8s.io",
            ]:
                if kind == "gatewayclasses.gateway.networking.k8s.io":
                    items = [r async for r in api.get(kind)]
                else:
                    items = [r async for r in api.get(kind, namespace=kr8s.ALL)]
                gateway_items.extend([r.raw for r in items])
            files["resources/gateway-api.yaml"] = yaml.dump(
                {"items": gateway_items}, default_flow_style=False
            ).encode("utf-8")
        except Exception as exc:
            logger.warning(
                "snapshot_optional_crd_failed",
                resource="resources/gateway-api.yaml",
                error=str(exc),
            )

        return files

    def _prepend_header(self, content: bytes, label: str, timestamp: str) -> bytes:
        """Prepend ISO 8601 UTC timestamp and resource label header to content.

        Header format:
            # Collected: <ISO 8601 timestamp>
            # Resource: <label>
            <content>

        Args:
            content: The raw file content.
            label: Human-readable resource label (e.g. "metadata/date.txt").
            timestamp: ISO 8601 UTC timestamp string.

        Returns:
            Content with prepended header.
        """
        header = f"# Collected: {timestamp}\n# Resource: {label}\n"
        return header.encode("utf-8") + content

    def _compute_sha256sums(self, files: dict[str, bytes]) -> bytes:
        """Generate SHA256SUMS content for all collected files.

        Format: one line per file with "<sha256hex>  <filename>\n"

        Args:
            files: Dict mapping filename to content bytes.

        Returns:
            SHA256SUMS manifest as bytes.
        """
        lines = []
        for filename in sorted(files.keys()):
            digest = hashlib.sha256(files[filename]).hexdigest()
            lines.append(f"{digest}  {filename}")
        return "\n".join(lines).encode("utf-8")

    @staticmethod
    def _guess_content_type(path: str) -> str:
        """Determine content type based on file extension.

        Args:
            path: File path/name.

        Returns:
            MIME content type string.
        """
        if path.endswith(".yaml"):
            return "text/yaml"
        elif path.endswith(".json"):
            return "application/json"
        else:
            return "text/plain"
