"""POST /roundtrip/export endpoint for the KASBench Benchmark Runner.

Orchestrates kubectl exec query of roundtrip trade order data and S3 upload.

Requirements: 1.1, 1.2, 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 4.1, 4.2,
              4.3, 4.4, 5.1, 5.2, 6.1, 6.2, 6.3, 6.4
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from kasbench_runner.errors import build_error_response
from kasbench_runner.models.state import BenchmarkState, BenchmarkStatus
from kasbench_runner.services.s3_client import S3Client, S3OperationError

logger = structlog.get_logger(__name__)

router = APIRouter()

_TERMINAL_STATUSES = {
    BenchmarkStatus.SUCCESS,
    BenchmarkStatus.FAILED,
    BenchmarkStatus.ABORTED,
}

_KUBECTL_COMMAND = [
    "kubectl", "exec", "svc/globeco-debug-tools", "--",
    "psql", "-h", "globeco-trade-service-postgresql",
    "-U", "postgres", "-tAc",
    "select json_agg(t) from (select sum(quantity_ordered) quantity_ordered, "
    "sum(quantity_placed) quantity_placed, sum(quantity_filled) quantity_filled "
    "from execution) t;",
]


@router.post("/roundtrip/export")
async def post_roundtrip_export(request: Request) -> JSONResponse:
    """Collect roundtrip trade order data and upload to S3."""
    state: BenchmarkState = request.app.state.benchmark_state

    # State guard
    if state.status not in _TERMINAL_STATUSES:
        return build_error_response(
            error="benchmark_not_completed",
            message=(
                "Roundtrip export is only available after the benchmark "
                "has completed (status must be 'success', 'failed', or 'aborted')"
            ),
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
    )
    log.info("roundtrip_export_start")

    # Execute kubectl query
    proc = await asyncio.create_subprocess_exec(
        *_KUBECTL_COMMAND,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()

    if proc.returncode != 0:
        stderr_text = stderr_bytes.decode().strip()
        log.error(
            "roundtrip_query_failed",
            exit_code=proc.returncode,
            stderr=stderr_text,
        )
        return build_error_response(
            error="roundtrip_query_failed",
            message="kubectl exec query returned non-zero exit code",
            status_code=500,
            exit_code=proc.returncode,
            stderr=stderr_text,
        )

    stdout_text = stdout_bytes.decode().strip()

    if not stdout_text:
        log.error("roundtrip_query_empty")
        return build_error_response(
            error="roundtrip_query_empty",
            message="No data was returned from the roundtrip query",
            status_code=500,
        )

    # Validate JSON structure (bracket check)
    json_valid = stdout_text.startswith("[") and stdout_text.endswith("]")

    if not json_valid:
        log.warning(
            "roundtrip_output_invalid_json",
            output_preview=stdout_text[:200],
        )

    # Upload to S3
    s3_key = f"{run_identifier}/{trial_identifier}/roundtrip/trade_orders.json"
    s3_client = S3Client(bucket=s3_bucket)

    try:
        await s3_client.upload_json(key=s3_key, data=stdout_text.encode("utf-8"))
    except S3OperationError as exc:
        log.error("s3_upload_failed", s3_key=s3_key, error=str(exc))
        return build_error_response(
            error="s3_operation_failed",
            message=f"S3 upload failed: {exc.message}",
            status_code=500,
        )

    log.info("roundtrip_export_success", s3_key=s3_key)

    return JSONResponse(
        status_code=200,
        content={
            "message": "Roundtrip data exported successfully",
            "s3Key": s3_key,
            "jsonValid": json_valid,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
