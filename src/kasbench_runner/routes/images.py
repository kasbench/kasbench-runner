"""POST /images/export endpoint for the KASBench Benchmark Runner.

Queries Kubernetes deployments and statefulsets in the globeco namespace
for container images (excluding busybox), resolves the running image IDs
(digests) from the pods, and uploads the results as a JSON document to S3.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from kasbench_runner.errors import build_error_response
from kasbench_runner.models.state import BenchmarkState, BenchmarkStatus
from kasbench_runner.services.s3_client import S3Client, S3OperationError

logger = structlog.get_logger(__name__)

router = APIRouter()

_NAMESPACE = "globeco"

# kubectl command to get deployments and statefulsets as JSON
_KUBECTL_COMMAND = [
    "kubectl", "get", "deployments,statefulsets",
    "--namespace", _NAMESPACE,
    "-o", "json",
]

# kubectl command to get pods as JSON (used to resolve running image IDs/digests)
_KUBECTL_PODS_COMMAND = [
    "kubectl", "get", "pods",
    "--namespace", _NAMESPACE,
    "-o", "json",
]


def _build_image_id_index(pods_json: dict) -> dict[tuple[str, str], str]:
    """Map (container name, image) to the resolved image ID from pod statuses.

    Kubernetes reports the resolved image ID (typically a registry digest) in
    each pod's ``status.containerStatuses[*].imageID``. We index those by
    container name and the image reference so that the workload's declared
    containers can be enriched with the digest actually running.

    Args:
        pods_json: Parsed JSON from ``kubectl get pods -o json``.

    Returns:
        A dict keyed by ``(container_name, image)`` mapping to the image ID.
        Also keyed by ``(container_name, "")`` as a fallback when the declared
        image reference differs from the pod's reported image.
    """
    index: dict[tuple[str, str], str] = {}

    for pod in pods_json.get("items", []):
        statuses = pod.get("status", {}).get("containerStatuses", []) or []
        for status in statuses:
            name = status.get("name", "")
            image = status.get("image", "")
            image_id = status.get("imageID", "")
            if not image_id:
                continue
            index[(name, image)] = image_id
            # Fallback keyed only by container name.
            index.setdefault((name, ""), image_id)

    return index


def _extract_images(
    kubectl_json: dict,
    image_id_index: dict[tuple[str, str], str],
) -> list[dict]:
    """Extract container images and their resolved image IDs.

    Filters out busybox containers and returns a structured list of workloads,
    each carrying its containers with declared image and resolved image ID.

    Args:
        kubectl_json: Parsed JSON from ``kubectl get deployments,statefulsets``.
        image_id_index: Mapping produced by ``_build_image_id_index``.

    Returns:
        A list of dicts, one per workload, in the shape::

            {
                "kind": "Deployment",
                "name": "my-app",
                "containers": [
                    {"name": "app", "image": "...", "imageID": "..."},
                    ...
                ]
            }
    """
    workloads: list[dict] = []

    items = kubectl_json.get("items", [])
    for item in items:
        kind = item.get("kind", "")
        name = item.get("metadata", {}).get("name", "")
        containers = (
            item.get("spec", {})
            .get("template", {})
            .get("spec", {})
            .get("containers", [])
        )

        container_entries: list[dict] = []
        for c in containers:
            image = c.get("image")
            if not image or "busybox" in image.lower():
                continue

            container_name = c.get("name", "")
            image_id = (
                image_id_index.get((container_name, image))
                or image_id_index.get((container_name, ""))
                or ""
            )

            container_entries.append({
                "name": container_name,
                "image": image,
                "imageID": image_id,
            })

        if not container_entries:
            continue

        workloads.append({
            "kind": kind,
            "name": name,
            "containers": container_entries,
        })

    return workloads


class ImagesExportError(Exception):
    """Raised when the image export flow fails at a recoverable step.

    Carries the structured fields needed to build an error response so that
    both the HTTP endpoint and the initialization flow can surface a
    consistent error.
    """

    def __init__(self, error: str, message: str, status_code: int, **context: object) -> None:
        super().__init__(message)
        self.error = error
        self.message = message
        self.status_code = status_code
        self.context = context


async def export_images(
    *,
    run_identifier: str,
    trial_identifier: str,
    s3_bucket: str,
    filename: str,
) -> str:
    """Query cluster images and upload them to S3 under the given filename.

    Steps:
      1. Run kubectl get deployments,statefulsets in globeco namespace
      2. Run kubectl get pods to resolve running image IDs (digests)
      3. Parse JSON output and extract container images (excluding busybox),
         enriched with each container's resolved image ID
      4. Serialize as a JSON document
      5. Upload to S3 at {run_id}/{trial_id}/images/{filename}

    Args:
        run_identifier: The run identifier used in the S3 key prefix.
        trial_identifier: The trial identifier used in the S3 key prefix.
        s3_bucket: The destination S3 bucket.
        filename: The object name under the images/ prefix (e.g. "pre-images.json").

    Returns:
        The S3 key the images were uploaded to.

    Raises:
        ImagesExportError: If kubectl fails, returns no data, produces
            unparseable JSON, or the S3 upload fails.
    """
    log = logger.bind(
        run_identifier=run_identifier,
        trial_identifier=trial_identifier,
        namespace=_NAMESPACE,
        filename=filename,
    )
    log.info("images_export_start")

    # Step 1: Run kubectl get deployments,statefulsets
    proc = await asyncio.create_subprocess_exec(
        *_KUBECTL_COMMAND,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()

    if proc.returncode != 0:
        stderr_text = stderr_bytes.decode().strip()
        log.error(
            "images_kubectl_failed",
            exit_code=proc.returncode,
            stderr=stderr_text,
        )
        raise ImagesExportError(
            error="images_kubectl_failed",
            message="kubectl get deployments,statefulsets returned non-zero exit code",
            status_code=500,
            exit_code=proc.returncode,
            stderr=stderr_text,
            namespace=_NAMESPACE,
        )

    # Step 2: Parse JSON output
    stdout_text = stdout_bytes.decode().strip()

    if not stdout_text:
        log.error("images_kubectl_empty")
        raise ImagesExportError(
            error="images_kubectl_empty",
            message="No data was returned from kubectl get command",
            status_code=500,
            namespace=_NAMESPACE,
        )

    try:
        kubectl_json = json.loads(stdout_text)
    except json.JSONDecodeError as exc:
        log.error("images_json_parse_failed", error=str(exc))
        raise ImagesExportError(
            error="images_json_parse_failed",
            message=f"Failed to parse kubectl JSON output: {exc}",
            status_code=500,
            output_preview=stdout_text[:200],
        )

    # Step 2: Run kubectl get pods to resolve running image IDs (digests).
    # This is best-effort: if pods can't be queried we still export the
    # declared images, just without resolved image IDs.
    image_id_index: dict[tuple[str, str], str] = {}
    pods_proc = await asyncio.create_subprocess_exec(
        *_KUBECTL_PODS_COMMAND,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    pods_stdout_bytes, pods_stderr_bytes = await pods_proc.communicate()

    if pods_proc.returncode != 0:
        log.warning(
            "images_kubectl_pods_failed",
            exit_code=pods_proc.returncode,
            stderr=pods_stderr_bytes.decode().strip(),
        )
    else:
        pods_stdout_text = pods_stdout_bytes.decode().strip()
        try:
            pods_json = json.loads(pods_stdout_text) if pods_stdout_text else {}
            image_id_index = _build_image_id_index(pods_json)
        except json.JSONDecodeError as exc:
            log.warning("images_pods_json_parse_failed", error=str(exc))

    # Step 3: Extract images enriched with resolved image IDs
    workloads = _extract_images(kubectl_json, image_id_index)

    if not workloads:
        log.warning("images_none_found")

    document = {
        "runIdentifier": run_identifier,
        "trialIdentifier": trial_identifier,
        "namespace": _NAMESPACE,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "workloads": workloads,
    }

    # Step 4: Serialize as JSON
    serialized = json.dumps(document, indent=2, sort_keys=False)

    # Step 5: Upload to S3
    s3_key = f"{run_identifier}/{trial_identifier}/images/{filename}"
    s3_client = S3Client(bucket=s3_bucket)

    try:
        await s3_client.upload_bytes(
            key=s3_key,
            data=serialized.encode("utf-8"),
            content_type="application/json",
        )
    except S3OperationError as exc:
        log.error("s3_upload_failed", s3_key=s3_key, error=str(exc))
        raise ImagesExportError(
            error="s3_operation_failed",
            message=f"S3 upload failed: {exc.message}",
            status_code=500,
            s3_key=s3_key,
        )

    log.info("images_export_success", s3_key=s3_key)
    return s3_key


@router.post("/images/export")
async def post_images_export(request: Request) -> JSONResponse:
    """Export container images from deployments/statefulsets to S3.

    Steps:
      1. State guard — reject if NOT_INITIALIZED
      2-5. Delegate to export_images (kubectl, parse, serialize, upload)
      6. Return 200 with s3Key and timestamp

    Uploads to {run_id}/{trial_id}/images/post-images.json.
    """
    state: BenchmarkState = request.app.state.benchmark_state

    # Step 1: State guard
    if state.status == BenchmarkStatus.NOT_INITIALIZED:
        return build_error_response(
            error="benchmark_not_initialized",
            message="Benchmark must be initialized before exporting images",
            status_code=409,
            current_status=state.status.value,
        )

    config = state.config

    try:
        s3_key = await export_images(
            run_identifier=config.run_identifier,
            trial_identifier=config.trial_identifier,
            s3_bucket=config.s3_bucket,
            filename="post-images.json",
        )
    except ImagesExportError as exc:
        return build_error_response(
            error=exc.error,
            message=exc.message,
            status_code=exc.status_code,
            **exc.context,
        )

    # Step 6: Return success response
    return JSONResponse(
        status_code=200,
        content={
            "message": "Images exported successfully",
            "s3Key": s3_key,
            "namespace": _NAMESPACE,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
