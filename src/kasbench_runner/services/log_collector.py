"""Kubernetes pod log collector and S3 uploader.

Collects logs from all containers across all pods in a given namespace
and uploads them to S3 with best-effort error handling.

Requirements: 3.1, 3.2, 3.3, 4.1, 4.2, 5.1, 5.2, 6.1, 6.2, 8.1, 8.2, 8.3
"""

from dataclasses import dataclass

import kr8s
import structlog

from kasbench_runner.errors import SnapshotCollectionError
from kasbench_runner.services.s3_client import S3Client, S3OperationError

logger = structlog.get_logger()


@dataclass(frozen=True)
class LogCollectionResult:
    """Result of a log collection and upload operation."""

    files_exported: int
    s3_prefix: str
    errors: list[dict]


@dataclass(frozen=True)
class LogEntry:
    """A single collected log ready for upload."""

    pod_name: str
    container_name: str
    filename: str
    content: bytes


class LogCollector:
    """Collects Kubernetes pod logs and uploads to S3."""

    def __init__(self, s3_client: S3Client) -> None:
        """Initialize with an S3Client instance."""
        self._s3_client = s3_client

    async def collect_and_upload(
        self,
        namespace: str,
        run_identifier: str,
        trial_identifier: str,
    ) -> LogCollectionResult:
        """Collect logs from all pods in namespace and upload to S3.

        Orchestrates pod discovery, container log collection, and S3 upload
        with best-effort error handling. Individual container or upload
        failures are recorded but do not abort the operation.

        Args:
            namespace: Target Kubernetes namespace.
            run_identifier: Run ID for S3 path construction.
            trial_identifier: Trial ID for S3 path construction.

        Returns:
            LogCollectionResult with files_exported count, s3_prefix, and errors list.

        Raises:
            SnapshotCollectionError: If the initial pod listing fails
                (Kubernetes API unreachable).
        """
        s3_prefix = f"{run_identifier}/{trial_identifier}/logs/{namespace}/"
        log = logger.bind(
            namespace=namespace,
            run_identifier=run_identifier,
            trial_identifier=trial_identifier,
            s3_prefix=s3_prefix,
        )
        log.info("log_collection_start")

        # Step 1: Discover pods (fatal on failure)
        pods = await self._discover_pods(namespace)
        log.info("log_collection_pods_discovered", pod_count=len(pods))

        if not pods:
            log.info("log_collection_complete", files_exported=0, error_count=0)
            return LogCollectionResult(
                files_exported=0,
                s3_prefix=s3_prefix,
                errors=[],
            )

        # Step 2: Collect logs from all containers (best-effort)
        errors: list[dict] = []
        log_entries: list[LogEntry] = []

        for pod in pods:
            pod_name = pod.name
            containers = pod.raw.get("spec", {}).get("containers", [])
            container_count = len(containers)

            for container in containers:
                container_name = container.get("name", "unknown")

                content = await self._collect_container_log(pod, container_name)
                if content is None:
                    errors.append(
                        {
                            "pod": pod_name,
                            "container": container_name,
                            "phase": "collection",
                            "error": "container logs not available",
                        }
                    )
                    log.warning(
                        "log_collection_container_failed",
                        pod=pod_name,
                        container=container_name,
                    )
                    continue

                filename = self._determine_filename(
                    pod_name, container_name, container_count
                )
                log_entries.append(
                    LogEntry(
                        pod_name=pod_name,
                        container_name=container_name,
                        filename=filename,
                        content=content,
                    )
                )

        # Step 3: Upload collected logs to S3 (best-effort)
        files_exported = 0

        for entry in log_entries:
            s3_key = f"{run_identifier}/{trial_identifier}/logs/{namespace}/{entry.filename}"
            try:
                await self._s3_client.upload_bytes(
                    key=s3_key,
                    data=entry.content,
                    content_type="text/plain",
                )
                files_exported += 1
            except S3OperationError as exc:
                errors.append(
                    {
                        "pod": entry.pod_name,
                        "container": entry.container_name,
                        "phase": "upload",
                        "error": exc.message,
                    }
                )
                log.error(
                    "log_collection_upload_failed",
                    pod=entry.pod_name,
                    container=entry.container_name,
                    s3_key=s3_key,
                    error=exc.message,
                )

        log.info(
            "log_collection_complete",
            files_exported=files_exported,
            error_count=len(errors),
        )

        return LogCollectionResult(
            files_exported=files_exported,
            s3_prefix=s3_prefix,
            errors=errors,
        )

    async def _discover_pods(self, namespace: str) -> list:
        """Query all pods in the namespace via kr8s.

        Args:
            namespace: Target Kubernetes namespace.

        Returns:
            List of kr8s Pod objects.

        Raises:
            SnapshotCollectionError: If the Kubernetes API is unreachable.
        """
        try:
            api = await kr8s.asyncio.api()
            pods = [p async for p in api.get("pods", namespace=namespace)]
            return pods
        except Exception as exc:
            raise SnapshotCollectionError(
                resource="pods",
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            ) from exc

    def _determine_filename(
        self, pod_name: str, container_name: str, container_count: int
    ) -> str:
        """Determine the log filename based on container count.

        Single-container pods: {pod_name}.log
        Multi-container pods:  {pod_name}-{container_name}.log

        Args:
            pod_name: Name of the pod.
            container_name: Name of the container.
            container_count: Total number of containers in the pod.

        Returns:
            The filename string for this container's log.
        """
        if container_count == 1:
            return f"{pod_name}.log"
        return f"{pod_name}-{container_name}.log"

    async def _collect_container_log(self, pod, container_name: str) -> bytes | None:
        """Fetch logs from a single container.

        Returns None if logs are unavailable (container never started,
        waiting state, etc.).

        Args:
            pod: A kr8s Pod object.
            container_name: Name of the container to fetch logs from.

        Returns:
            Log content as bytes, or None if unavailable.
        """
        try:
            lines: list[str] = []
            async for line in pod.logs(container=container_name):
                lines.append(line)
            if not lines:
                return None
            log_content = "\n".join(lines)
            return log_content.encode("utf-8")
        except Exception:
            return None
