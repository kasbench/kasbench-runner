"""POST /images/export endpoint for the KASBench Benchmark Runner.

Queries Kubernetes deployments and statefulsets in the globeco namespace
for container images (excluding busybox), formats the results, and uploads
to S3.
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


def _extract_images(kubectl_json: dict) -> str:
    """Extract container images from kubectl JSON output.

    Filters out busybox containers and formats output as a tab-separated table
    with columns: Kind, Name, Images.

    Args:
        kubectl_json: Parsed JSON from kubectl get output.

    Returns:
        Formatted text with image information, one resource per line.
    """
    lines: list[str] = []

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

        # Filter out busybox images (case-insensitive)
        images = [
            c["image"]
            for c in containers
            if "image" in c
            and "busybox" not in c["image"].lower()
        ]

        if not images:
            continue

        lines.append(f"{kind}\t{name}\t{', '.join(images)}")

    if not lines:
        return ""

    # Format with column alignment (simulate `column -t -s $'\t'`)
    # Split into columns and pad to max width
    rows = [line.split("\t") for line in lines]
    if not rows:
        return ""

    num_cols = max(len(row) for row in rows)
    col_widths = [0] * num_cols
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    formatted_lines = []
    for row in rows:
        parts = []
        for i, cell in enumerate(row):
            if i < len(row) - 1:
                parts.append(cell.ljust(col_widths[i]))
            else:
                parts.append(cell)
        formatted_lines.append("  ".join(parts))

    return "\n".join(formatted_lines) + "\n"


@router.post("/images/export")
async def post_images_export(request: Request) -> JSONResponse:
    """Export container images from deployments/statefulsets to S3.

    Steps:
      1. State guard — reject if NOT_INITIALIZED
      2. Run kubectl get deployments,statefulsets in globeco namespace
      3. Parse JSON output and extract container images (excluding busybox)
      4. Format as aligned text table
      5. Upload to S3 at {run_id}/{trial_id}/images/images.txt
      6. Return 200 with s3Key and timestamp
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
    run_identifier = config.run_identifier
    trial_identifier = config.trial_identifier
    s3_bucket = config.s3_bucket

    log = logger.bind(
        run_identifier=run_identifier,
        trial_identifier=trial_identifier,
        namespace=_NAMESPACE,
    )
    log.info("images_export_start")

    # Step 2: Run kubectl get deployments,statefulsets
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
        return build_error_response(
            error="images_kubectl_failed",
            message="kubectl get deployments,statefulsets returned non-zero exit code",
            status_code=500,
            exit_code=proc.returncode,
            stderr=stderr_text,
            namespace=_NAMESPACE,
        )

    # Step 3: Parse JSON output
    stdout_text = stdout_bytes.decode().strip()

    if not stdout_text:
        log.error("images_kubectl_empty")
        return build_error_response(
            error="images_kubectl_empty",
            message="No data was returned from kubectl get command",
            status_code=500,
            namespace=_NAMESPACE,
        )

    try:
        kubectl_json = json.loads(stdout_text)
    except json.JSONDecodeError as exc:
        log.error("images_json_parse_failed", error=str(exc))
        return build_error_response(
            error="images_json_parse_failed",
            message=f"Failed to parse kubectl JSON output: {exc}",
            status_code=500,
            output_preview=stdout_text[:200],
        )

    # Step 4: Extract and format images
    formatted_output = _extract_images(kubectl_json)

    if not formatted_output:
        log.warning("images_none_found")
        formatted_output = ""

    # Step 5: Upload to S3
    s3_key = f"{run_identifier}/{trial_identifier}/images/images.txt"
    s3_client = S3Client(bucket=s3_bucket)

    try:
        await s3_client.upload_bytes(
            key=s3_key,
            data=formatted_output.encode("utf-8"),
            content_type="text/plain",
        )
    except S3OperationError as exc:
        log.error("s3_upload_failed", s3_key=s3_key, error=str(exc))
        return build_error_response(
            error="s3_operation_failed",
            message=f"S3 upload failed: {exc.message}",
            status_code=500,
            s3_key=s3_key,
        )

    log.info("images_export_success", s3_key=s3_key)

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
