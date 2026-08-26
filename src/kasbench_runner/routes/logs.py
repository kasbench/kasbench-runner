"""POST /logs/{namespace}/export endpoint for the KASBench Benchmark Runner.

Collects Kubernetes pod logs from all pods in a specified namespace
and uploads them to S3 with best-effort error handling.

Requirements: 1.1, 1.2, 2.1, 2.2, 7.1, 7.2, 8.4
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from kasbench_runner.errors import SnapshotCollectionError, build_error_response
from kasbench_runner.models.state import BenchmarkState, BenchmarkStatus
from kasbench_runner.services.log_collector import LogCollector
from kasbench_runner.services.s3_client import S3Client

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.post("/logs/{namespace}/export")
async def post_logs_export(namespace: str, request: Request) -> JSONResponse:
    """Collect pod logs from a namespace and upload to S3.

    Steps:
      1. State guard — reject if benchmark not initialized
      2. Instantiate LogCollector with S3Client
      3. Collect logs from all pods in namespace
      4. Upload collected logs to S3
      5. Return 200 (all OK), 207 (partial failures), or 500 (fatal)
    """
    state: BenchmarkState = request.app.state.benchmark_state

    # Step 1: State guard — reject if not initialized
    if state.status == BenchmarkStatus.NOT_INITIALIZED:
        return build_error_response(
            error="not_initialized",
            message="Benchmark has not been initialized",
            status_code=409,
        )

    config = state.config
    run_identifier = config.run_identifier
    trial_identifier = config.trial_identifier
    s3_bucket = config.s3_bucket

    log = logger.bind(
        namespace=namespace,
        run_identifier=run_identifier,
        trial_identifier=trial_identifier,
    )
    log.info("logs_export_start")

    # Step 2: Instantiate services
    s3_client = S3Client(bucket=s3_bucket)
    collector = LogCollector(s3_client=s3_client)

    # Step 3 & 4: Collect and upload logs
    try:
        result = await collector.collect_and_upload(
            namespace=namespace,
            run_identifier=run_identifier,
            trial_identifier=trial_identifier,
        )
    except SnapshotCollectionError as exc:
        log.error(
            "logs_export_kubernetes_error",
            error=exc.message,
        )
        return build_error_response(
            error="kubernetes_error",
            message=exc.message,
            status_code=500,
            **exc.context,
        )

    # Step 5: Build response
    timestamp = datetime.now(timezone.utc).isoformat()

    if result.errors:
        response_body = {
            "message": f"Log export completed with {len(result.errors)} error(s)",
            "filesExported": result.files_exported,
            "s3Prefix": result.s3_prefix,
            "errors": result.errors,
            "timestamp": timestamp,
        }
        status_code = 207
    else:
        response_body = {
            "message": "Logs exported successfully",
            "filesExported": result.files_exported,
            "s3Prefix": result.s3_prefix,
            "timestamp": timestamp,
        }
        status_code = 200

    log.info(
        "logs_export_complete",
        status_code=status_code,
        files_exported=result.files_exported,
        error_count=len(result.errors),
    )

    return JSONResponse(status_code=status_code, content=response_body)
