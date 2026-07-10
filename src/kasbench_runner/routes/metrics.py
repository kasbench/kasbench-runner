"""POST /metrics/export endpoint for the KASBench Benchmark Runner.

Orchestrates Prometheus range query execution and S3 upload of metric
results as JSON files.

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5,
              3.1, 3.2, 3.3, 3.4, 6.3, 7.1, 8.1, 8.2, 8.3, 8.4,
              11.1, 11.2, 11.3, 11.4, 11.5
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from kasbench_runner.errors import build_error_response
from kasbench_runner.models.requests import MetricsExportRequest
from kasbench_runner.models.state import BenchmarkState, BenchmarkStatus
from kasbench_runner.services.metrics_config import ALL_METRICS
from kasbench_runner.services.prometheus_client import PrometheusClient
from kasbench_runner.services.s3_client import S3Client, S3OperationError

logger = structlog.get_logger(__name__)

router = APIRouter()

# Terminal statuses that allow metrics collection
_TERMINAL_STATUSES = {
    BenchmarkStatus.SUCCESS,
    BenchmarkStatus.FAILED,
    BenchmarkStatus.ABORTED,
}


@router.post("/metrics/export")
async def post_metrics(
    request: Request, body: MetricsExportRequest = MetricsExportRequest()
) -> JSONResponse:
    """Collect Prometheus metrics and upload to S3.

    Steps:
      1. State guard — reject non-terminal statuses
      2. Validate time bounds
      3. Overwrite protection
      4. Execute Prometheus queries
      5. Upload successful results to S3
      6. Return 200 (all OK) or 207 (partial failures)
    """
    state: BenchmarkState = request.app.state.benchmark_state

    # Step 1: State guard — reject if status not in terminal set
    if state.status not in _TERMINAL_STATUSES:
        return build_error_response(
            error="benchmark_not_completed",
            message=(
                "Metrics collection is only available after the benchmark "
                "has completed (status must be 'success', 'failed', or 'aborted')"
            ),
            status_code=409,
            current_status=state.status.value,
        )

    # Step 2: Validate time bounds
    if state.start_time is None:
        return build_error_response(
            error="missing_time_bounds",
            message="Benchmark start time is not available",
            status_code=500,
        )

    if state.end_time is None:
        return build_error_response(
            error="missing_time_bounds",
            message="Benchmark end time is not available",
            status_code=500,
        )

    config = state.config
    run_identifier = config.run_identifier
    trial_identifier = config.trial_identifier
    s3_bucket = config.s3_bucket
    control_plane_node = config.control_plane_node

    s3_prefix = f"{run_identifier}/{trial_identifier}/metrics/"

    log = logger.bind(
        run_identifier=run_identifier,
        trial_identifier=trial_identifier,
        s3_prefix=s3_prefix,
    )
    log.info("metrics_collection_start", overwrite=body.overwrite)

    # Build all S3 keys
    s3_keys = [
        f"{run_identifier}/{trial_identifier}/metrics/{metric.name}"
        for metric in ALL_METRICS
    ]

    # Step 3: Overwrite protection
    s3_client = S3Client(bucket=s3_bucket)

    if not body.overwrite:
        try:
            existing_keys = await s3_client.check_objects_exist(s3_keys)
        except S3OperationError as exc:
            log.error("s3_existence_check_failed", error=str(exc))
            return build_error_response(
                error="s3_operation_failed",
                message=f"S3 existence check failed: {exc.message}",
                status_code=500,
            )

        if existing_keys:
            # Extract metric names from full keys
            existing_names = [
                key.split("/metrics/", 1)[1] for key in existing_keys
            ]
            log.warning(
                "metrics_already_exist",
                existing_count=len(existing_names),
            )
            return build_error_response(
                error="metrics_already_exist",
                message=(
                    f"{len(existing_names)} metric(s) already exist in S3"
                ),
                status_code=409,
                existing=existing_names,
            )

    # Step 4: Execute Prometheus queries
    prometheus_client = PrometheusClient(control_plane_node=control_plane_node)

    start_ts = state.start_time.timestamp()
    end_ts = state.end_time.timestamp()

    query_summary = await prometheus_client.execute_all(
        metrics=ALL_METRICS,
        start_ts=start_ts,
        end_ts=end_ts,
        step=body.step,
        interval=body.interval,
        port=body.prometheus_port,
    )

    # Build error list from query failures
    errors: list[dict] = []
    for result in query_summary.failed:
        errors.append(
            {
                "metricName": result.metric_name,
                "phase": "query",
                "error": result.error_message or "Unknown query error",
            }
        )

    # Step 5: Upload successful results to S3
    upload_count = 0
    for result in query_summary.successful:
        key = f"{run_identifier}/{trial_identifier}/metrics/{result.metric_name}"
        data = json.dumps(result.response_json).encode("utf-8")

        try:
            await s3_client.upload_json(key=key, data=data)
            upload_count += 1
        except S3OperationError as exc:
            log.error(
                "s3_upload_failed",
                metric_name=result.metric_name,
                error=str(exc),
            )
            errors.append(
                {
                    "metricName": result.metric_name,
                    "phase": "upload",
                    "error": exc.message,
                }
            )

    # Step 6: Return response
    metrics_total = len(ALL_METRICS)
    timestamp = datetime.now(timezone.utc).isoformat()

    response_body = {
        "message": (
            "All metrics collected and uploaded successfully"
            if not errors
            else f"Metrics collection completed with {len(errors)} error(s)"
        ),
        "metricsUploaded": upload_count,
        "metricsTotal": metrics_total,
        "s3Prefix": s3_prefix,
        "errors": errors,
        "timestamp": timestamp,
    }

    status_code = 200 if not errors else 207

    log.info(
        "metrics_collection_complete",
        status_code=status_code,
        uploaded=upload_count,
        total=metrics_total,
        error_count=len(errors),
    )

    return JSONResponse(status_code=status_code, content=response_body)
