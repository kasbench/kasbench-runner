"""GET /metrics endpoint for the KASBench Benchmark Runner.

Scrapes Prometheus metrics from the monitoring namespace, transforms them
to Pandas DataFrames, serializes to Parquet, and uploads to S3.

Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6
"""

from __future__ import annotations

import asyncio
import io
from datetime import datetime, timezone

import boto3
import httpx
import pandas as pd
import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from kasbench_runner.errors import build_error_response
from kasbench_runner.models.state import BenchmarkState, BenchmarkStatus

logger = structlog.get_logger(__name__)

router = APIRouter()

# Prometheus endpoint within the monitoring namespace
PROMETHEUS_URL = "http://prometheus.monitoring.svc:9090/api/v1/query"

# Predefined metrics queries to scrape
METRICS_QUERIES = [
    "container_cpu_usage_seconds_total",
    "container_memory_usage_bytes",
    "container_network_receive_bytes_total",
    "container_network_transmit_bytes_total",
    "kube_pod_status_phase",
]


@router.get("/metrics")
async def get_metrics(request: Request) -> JSONResponse:
    """Scrape Prometheus metrics, convert to Parquet, and upload to S3.

    Req 17.1/17.2: Only available when benchmark status is SUCCESS or FAILED.
    Req 17.3: Scrape Prometheus metrics from monitoring namespace.
    Req 17.4: Transform to Pandas DataFrames.
    Req 17.5: Serialize to Parquet format.
    Req 17.6: Upload to S3.
    """
    state: BenchmarkState = request.app.state.benchmark_state

    # Req 17.1, 17.2: Must be success or failed
    if state.status not in (BenchmarkStatus.SUCCESS, BenchmarkStatus.FAILED):
        return build_error_response(
            error="benchmark_not_completed",
            message="Metrics collection is only available after the benchmark has completed (status must be 'success' or 'failed')",
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
    log.info("metrics_collection_start")

    # Req 17.3: Scrape Prometheus metrics
    metrics_data = await _scrape_prometheus_metrics()

    # Req 17.4 & 17.5: Transform to DataFrames and serialize to Parquet
    parquet_files = _transform_to_parquet(metrics_data)

    # Req 17.6: Upload to S3
    s3_prefix = f"{run_identifier}/{trial_identifier}/metrics/"
    file_count = await _upload_to_s3(
        bucket=s3_bucket,
        prefix=s3_prefix,
        parquet_files=parquet_files,
    )

    log.info("metrics_collection_complete", file_count=file_count)

    return JSONResponse(
        status_code=200,
        content={
            "message": "Metrics collected and uploaded successfully",
            "file_count": file_count,
            "s3_prefix": s3_prefix,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


async def _scrape_prometheus_metrics() -> dict[str, list[dict]]:
    """Scrape predefined metrics from Prometheus.

    Returns a dict mapping metric name to list of result dicts from the
    Prometheus query API.
    """
    results: dict[str, list[dict]] = {}

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        for query in METRICS_QUERIES:
            try:
                response = await client.get(
                    PROMETHEUS_URL,
                    params={"query": query},
                )
                if response.status_code == 200:
                    data = response.json()
                    # Prometheus API returns: {"status": "success", "data": {"result": [...]}}
                    result_list = (
                        data.get("data", {}).get("result", [])
                        if data.get("status") == "success"
                        else []
                    )
                    results[query] = result_list
                else:
                    logger.warning(
                        "prometheus_query_non_200",
                        query=query,
                        status_code=response.status_code,
                    )
                    results[query] = []
            except httpx.HTTPError as exc:
                logger.warning(
                    "prometheus_query_failed",
                    query=query,
                    error=str(exc),
                )
                results[query] = []

    return results


def _transform_to_parquet(metrics_data: dict[str, list[dict]]) -> dict[str, bytes]:
    """Transform Prometheus metrics results to Parquet bytes.

    Args:
        metrics_data: Dict mapping metric name to list of Prometheus result dicts.

    Returns:
        Dict mapping filename (metric_name.parquet) to Parquet bytes.
    """
    parquet_files: dict[str, bytes] = {}

    for metric_name, results in metrics_data.items():
        if not results:
            # Create an empty DataFrame with standard columns
            df = pd.DataFrame(columns=["metric", "labels", "timestamp", "value"])
        else:
            rows = []
            for result in results:
                metric_labels = result.get("metric", {})
                value_pair = result.get("value", [])
                if len(value_pair) == 2:
                    timestamp, value = value_pair
                    rows.append(
                        {
                            "metric": metric_labels.get("__name__", metric_name),
                            "labels": str(metric_labels),
                            "timestamp": float(timestamp),
                            "value": str(value),
                        }
                    )
            df = pd.DataFrame(rows) if rows else pd.DataFrame(
                columns=["metric", "labels", "timestamp", "value"]
            )

        # Req 17.5: Serialize to Parquet
        buffer = io.BytesIO()
        df.to_parquet(buffer, engine="pyarrow", index=False)
        parquet_files[f"{metric_name}.parquet"] = buffer.getvalue()

    return parquet_files


async def _upload_to_s3(
    bucket: str,
    prefix: str,
    parquet_files: dict[str, bytes],
) -> int:
    """Upload Parquet files to S3.

    Args:
        bucket: S3 bucket name.
        prefix: S3 key prefix (e.g. "run001/trial001/metrics/").
        parquet_files: Dict mapping filename to Parquet bytes.

    Returns:
        Number of files uploaded.
    """
    s3 = boto3.client("s3")
    file_count = 0

    for filename, parquet_bytes in parquet_files.items():
        key = f"{prefix}{filename}"
        try:
            await asyncio.to_thread(
                s3.put_object,
                Bucket=bucket,
                Key=key,
                Body=parquet_bytes,
                ContentType="application/octet-stream",
            )
            file_count += 1
            logger.debug("s3_metrics_upload_success", key=key)
        except Exception as exc:
            logger.error(
                "s3_metrics_upload_failed",
                key=key,
                error=str(exc),
            )
            raise

    return file_count
