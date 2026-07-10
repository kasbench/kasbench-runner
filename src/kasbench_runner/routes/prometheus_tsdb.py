"""POST /prometheus/tsdb/export endpoint for the KASBench Benchmark Runner.

Triggers a Prometheus TSDB snapshot, copies it from the prometheus-server pod,
and uploads the snapshot directory to S3.

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 5.10, 5.11
"""

from __future__ import annotations

import io
import shutil
import tarfile
import tempfile
from datetime import datetime, timezone

import httpx
import kr8s
import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from kasbench_runner.errors import build_error_response
from kasbench_runner.models.requests import TsdbExportRequest
from kasbench_runner.models.state import BenchmarkState, BenchmarkStatus
from kasbench_runner.services.s3_client import S3Client, S3OperationError

logger = structlog.get_logger(__name__)

router = APIRouter()

# Labels used to find the prometheus-server pod
_PROMETHEUS_LABELS = {
    "app.kubernetes.io/component": "server",
    "app.kubernetes.io/instance": "prometheus",
}
_PROMETHEUS_NAMESPACE = "monitoring"


@router.post("/prometheus/tsdb/export")
async def post_prometheus_tsdb_export(
    request: Request, body: TsdbExportRequest = TsdbExportRequest()
) -> JSONResponse:
    """Export a Prometheus TSDB snapshot to S3.

    Steps:
      1. State guard — reject if NOT_INITIALIZED
      2. Trigger TSDB snapshot via Prometheus admin API
      3. Find prometheus-server pod via kr8s
      4. Copy snapshot directory from pod to local temp directory
      5. Upload directory to S3
      6. Clean up local temp copy
      7. Return 200 with s3Path and timestamp
    """
    state: BenchmarkState = request.app.state.benchmark_state

    # Step 1: State guard
    if state.status == BenchmarkStatus.NOT_INITIALIZED:
        return build_error_response(
            error="benchmark_not_initialized",
            message="Benchmark must be initialized before exporting TSDB snapshots",
            status_code=409,
            current_status=state.status.value,
        )

    config = state.config
    control_plane_node = config.control_plane_node
    s3_bucket = config.s3_bucket
    run_identifier = config.run_identifier
    trial_identifier = config.trial_identifier
    prometheus_port = body.prometheus_port

    s3_path = f"{run_identifier}/{trial_identifier}/tsdb-snapshots"

    log = logger.bind(
        run_identifier=run_identifier,
        trial_identifier=trial_identifier,
        prometheus_port=prometheus_port,
        s3_path=s3_path,
    )
    log.info("tsdb_export_start")

    # Step 2: Trigger TSDB snapshot via Prometheus admin API
    snapshot_url = (
        f"http://{control_plane_node}:{prometheus_port}/api/v1/admin/tsdb/snapshot"
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(snapshot_url)
            response.raise_for_status()
            snapshot_data = response.json()
            snapshot_name = snapshot_data["data"]["name"]
    except (httpx.HTTPError, httpx.TimeoutException, KeyError, Exception) as exc:
        log.error("prometheus_snapshot_failed", error=str(exc), url=snapshot_url)
        return build_error_response(
            error="prometheus_snapshot_failed",
            message=f"Prometheus TSDB snapshot trigger failed: {exc}",
            status_code=502,
            url=snapshot_url,
        )

    log.info("tsdb_snapshot_created", snapshot_name=snapshot_name)

    # Step 3: Find prometheus-server pod via kr8s
    try:
        api = await kr8s.asyncio.api()
        label_selector = ",".join(
            f"{k}={v}" for k, v in _PROMETHEUS_LABELS.items()
        )
        pods = [
            pod
            async for pod in api.get(
                "pods",
                namespace=_PROMETHEUS_NAMESPACE,
                label_selector=label_selector,
            )
        ]
    except Exception as exc:
        log.error("prometheus_pod_lookup_failed", error=str(exc))
        return build_error_response(
            error="prometheus_pod_not_found",
            message=f"Failed to look up prometheus-server pod: {exc}",
            status_code=500,
            namespace=_PROMETHEUS_NAMESPACE,
            labels=_PROMETHEUS_LABELS,
        )

    if not pods:
        log.error("prometheus_pod_not_found")
        return build_error_response(
            error="prometheus_pod_not_found",
            message=(
                "No prometheus-server pod found matching labels "
                f"{_PROMETHEUS_LABELS} in namespace '{_PROMETHEUS_NAMESPACE}'"
            ),
            status_code=500,
            namespace=_PROMETHEUS_NAMESPACE,
            labels=_PROMETHEUS_LABELS,
        )

    pod = pods[0]
    log.info("prometheus_pod_found", pod_name=pod.name)

    # Step 4: Copy snapshot directory from pod to local temp directory
    temp_dir = tempfile.mkdtemp(prefix="tsdb-snapshot-")
    snapshot_path = f"/data/snapshots/{snapshot_name}"

    try:
        # Use pod exec to tar the snapshot and stream it locally
        # The tar command packs the snapshot directory; we unpack locally
        tar_command = ["tar", "cf", "-", "-C", "/data/snapshots", snapshot_name]
        exec_result = await pod.exec(tar_command)

        # Write the tar output to a temporary file and extract
        tar_bytes = exec_result.stdout if hasattr(exec_result, "stdout") else exec_result
        if isinstance(tar_bytes, str):
            tar_bytes = tar_bytes.encode("latin-1")

        tar_buffer = io.BytesIO(tar_bytes)
        with tarfile.open(fileobj=tar_buffer, mode="r:") as tar:
            tar.extractall(path=temp_dir)

        log.info("snapshot_copied_to_local", temp_dir=temp_dir)
    except Exception as exc:
        # Clean up temp dir on failure
        shutil.rmtree(temp_dir, ignore_errors=True)
        log.error("snapshot_copy_failed", error=str(exc), pod_name=pod.name)
        return build_error_response(
            error="snapshot_copy_failed",
            message=f"Failed to copy snapshot from pod '{pod.name}': {exc}",
            status_code=500,
            pod_name=pod.name,
            snapshot_path=snapshot_path,
        )

    # Step 5: Upload directory to S3
    try:
        s3_client = S3Client(bucket=s3_bucket)
        await s3_client.upload_directory(prefix=s3_path, local_dir=temp_dir)
        log.info("tsdb_snapshot_uploaded_to_s3", s3_path=s3_path)
    except S3OperationError as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        log.error("s3_upload_failed", error=str(exc))
        return build_error_response(
            error="s3_operation_failed",
            message=f"S3 upload failed: {exc.message}",
            status_code=500,
            bucket=s3_bucket,
            prefix=s3_path,
        )

    # Step 6: Clean up local temp copy
    shutil.rmtree(temp_dir, ignore_errors=True)
    log.info("temp_dir_cleaned_up")

    # Step 7: Return success response
    timestamp = datetime.now(timezone.utc).isoformat()

    return JSONResponse(
        status_code=200,
        content={
            "s3Path": s3_path,
            "timestamp": timestamp,
        },
    )
