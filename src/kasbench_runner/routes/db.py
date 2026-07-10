"""Database endpoints for the KASBench Benchmark Runner.

GET /db/{role} - Streams the SQLite database file from a Load Generator container.
POST /db/export/{role} - Exports a single role's database to S3.
POST /db/export - Exports all roles' databases to S3.

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9, 10.1-10.7
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import structlog
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from kasbench_runner.config import VALID_ROLES
from kasbench_runner.errors import build_error_response
from kasbench_runner.models.responses import ExportResponse, ExportResultEntry
from kasbench_runner.models.state import BenchmarkStatus
from kasbench_runner.services.s3_client import S3Client, S3OperationError

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("/db/{role}")
async def get_db(role: str):
    """Stream the SQLite database from a Load Generator.

    Validates the role parameter, then proxies the request to the
    Load Generator's /download-db endpoint using streaming to avoid
    buffering the entire file in memory.
    """
    # Req 10.5: Validate role parameter
    if role not in VALID_ROLES:
        return build_error_response(
            error="invalid_role",
            message=f"Invalid role: '{role}'",
            status_code=400,
            invalid_value=role,
            valid_roles=list(VALID_ROLES),
        )

    # Req 10.1: Forward to GET http://{role}:8080/download-db
    upstream_url = f"http://{role}:8080/download-db"

    try:
        client = httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=None, write=None, pool=None))

        response = await client.send(
            client.build_request("GET", upstream_url),
            stream=True,
        )

        # Req 10.3: Forward 409 (subprocess active)
        if response.status_code == 409:
            body = await response.aread()
            await response.aclose()
            await client.aclose()
            return build_error_response(
                error="subprocess_active",
                message="Load generator subprocess is still active",
                status_code=409,
                role=role,
                upstream_body=body.decode(errors="replace"),
            )

        # Req 10.4: Forward 404 (DB not available)
        if response.status_code == 404:
            body = await response.aread()
            await response.aclose()
            await client.aclose()
            return build_error_response(
                error="db_not_available",
                message="Database file not available",
                status_code=404,
                role=role,
                upstream_body=body.decode(errors="replace"),
            )

        # Req 10.7: Any other non-200 status → 502
        if response.status_code != 200:
            body = await response.aread()
            await response.aclose()
            await client.aclose()
            return build_error_response(
                error="upstream_error",
                message=f"Unexpected status from load generator '{role}'",
                status_code=502,
                role=role,
                upstream_status=response.status_code,
                upstream_body=body.decode(errors="replace"),
            )

        # Req 10.2: Stream application/x-sqlite3 response to client
        async def stream_generator():
            try:
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    yield chunk
            finally:
                await response.aclose()
                await client.aclose()

        return StreamingResponse(
            content=stream_generator(),
            media_type="application/x-sqlite3",
            status_code=200,
        )

    except (httpx.ConnectTimeout, httpx.ConnectError) as exc:
        # Req 10.6: Connection timeout 10s → 502
        logger.error(
            "db_connection_failed",
            role=role,
            url=upstream_url,
            error=str(exc),
        )
        return build_error_response(
            error="upstream_connection_failed",
            message=f"Failed to connect to load generator '{role}'",
            status_code=502,
            role=role,
            url=upstream_url,
            error_detail=str(exc),
        )
    except httpx.TimeoutException as exc:
        # Other timeouts also → 502
        logger.error(
            "db_timeout",
            role=role,
            url=upstream_url,
            error=str(exc),
        )
        return build_error_response(
            error="upstream_timeout",
            message=f"Timeout connecting to load generator '{role}'",
            status_code=502,
            role=role,
            url=upstream_url,
            error_detail=str(exc),
        )


# ---------------------------------------------------------------------------
# Database export endpoints
# ---------------------------------------------------------------------------


async def _export_single_role(
    role: str, s3_client: S3Client, run_identifier: str, trial_identifier: str
) -> ExportResultEntry:
    """Fetch a single role's database from LG and upload to S3.

    Returns an ExportResultEntry with success or failure details.
    """
    upstream_url = f"http://{role}:8080/download-db"
    s3_key = f"{run_identifier}/{trial_identifier}/db/{role}.db"

    try:
        # Req 7.7: 10s connect timeout for LG fetch
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=None, write=None, pool=None)
        ) as client:
            response = await client.get(upstream_url)

            # Req 7.6: LG non-200 → record failure
            if response.status_code != 200:
                return ExportResultEntry(
                    role=role,
                    status="failed",
                    error=f"Load generator returned HTTP {response.status_code}",
                )

            db_bytes = response.content

        # Upload to S3
        await s3_client.upload_bytes(s3_key, db_bytes, "application/octet-stream")

        return ExportResultEntry(role=role, status="success", s3_key=s3_key)

    except (httpx.ConnectTimeout, httpx.ConnectError) as exc:
        # Req 7.7: Connection timeout/refused → failure
        logger.error("db_export_connection_failed", role=role, error=str(exc))
        return ExportResultEntry(
            role=role,
            status="failed",
            error=f"Failed to connect to load generator: {exc}",
        )
    except httpx.TimeoutException as exc:
        logger.error("db_export_timeout", role=role, error=str(exc))
        return ExportResultEntry(
            role=role,
            status="failed",
            error=f"Timeout connecting to load generator: {exc}",
        )
    except S3OperationError as exc:
        # Req 7.8: S3 failure → failure
        logger.error("db_export_s3_failed", role=role, error=str(exc))
        return ExportResultEntry(
            role=role,
            status="failed",
            error=f"S3 upload failed: {exc.message}",
        )


@router.post("/db/export/{role}")
async def export_db_single(role: str, request: Request):
    """Export a single role's database to S3.

    Fetches the database from the Load Generator via GET http://{role}:8080/download-db,
    then uploads to S3 at {s3Bucket}/{runIdentifier}/{trialIdentifier}/db/{role}.db.
    """
    # Req 7.9: State guard - reject if NOT_INITIALIZED
    state = request.app.state.benchmark_state
    if state.status == BenchmarkStatus.NOT_INITIALIZED:
        return build_error_response(
            error="benchmark_not_initialized",
            message="Benchmark must be initialized before exporting databases",
            status_code=409,
        )

    # Req 7.5: Validate role
    if role not in VALID_ROLES:
        return build_error_response(
            error="invalid_role",
            message=f"Invalid role: '{role}'",
            status_code=400,
            invalid_value=role,
            valid_roles=list(VALID_ROLES),
        )

    run_identifier = state.config.run_identifier
    trial_identifier = state.config.trial_identifier
    s3_client = S3Client(bucket=state.config.s3_bucket)
    s3_key = f"{run_identifier}/{trial_identifier}/db/{role}.db"
    upstream_url = f"http://{role}:8080/download-db"

    try:
        # Req 7.2: Fetch from LG with 10s connect timeout
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=None, write=None, pool=None)
        ) as client:
            response = await client.get(upstream_url)

            # Req 7.6: LG non-200 → 502
            if response.status_code != 200:
                return build_error_response(
                    error="upstream_error",
                    message=f"Load generator '{role}' returned HTTP {response.status_code}",
                    status_code=502,
                    role=role,
                    upstream_status=response.status_code,
                )

            db_bytes = response.content

    except (httpx.ConnectTimeout, httpx.ConnectError) as exc:
        # Req 7.7: Connection timeout/refused → 502
        logger.error("db_export_connection_failed", role=role, url=upstream_url, error=str(exc))
        return build_error_response(
            error="upstream_connection_failed",
            message=f"Failed to connect to load generator '{role}'",
            status_code=502,
            role=role,
            url=upstream_url,
            error_detail=str(exc),
        )
    except httpx.TimeoutException as exc:
        logger.error("db_export_timeout", role=role, url=upstream_url, error=str(exc))
        return build_error_response(
            error="upstream_timeout",
            message=f"Timeout connecting to load generator '{role}'",
            status_code=502,
            role=role,
            url=upstream_url,
            error_detail=str(exc),
        )

    # Upload to S3
    try:
        await s3_client.upload_bytes(s3_key, db_bytes, "application/octet-stream")
    except S3OperationError as exc:
        # Req 7.8: S3 failure → 500
        logger.error("db_export_s3_failed", role=role, s3_key=s3_key, error=str(exc))
        return build_error_response(
            error="s3_operation_failed",
            message=f"S3 upload failed for role '{role}'",
            status_code=500,
            role=role,
            s3_key=s3_key,
            error_detail=str(exc),
        )

    return ExportResponse(
        message=f"Database export complete for role '{role}'",
        files_exported=1,
        results=[ExportResultEntry(role=role, status="success", s3_key=s3_key)],
        s3_key=s3_key,
        timestamp=datetime.now(timezone.utc),
    )


@router.post("/db/export")
async def export_db_all(request: Request):
    """Export all roles' databases to S3.

    Iterates all 5 roles, fetches each database from the Load Generator,
    and uploads to S3 at {s3Bucket}/{runIdentifier}/{trialIdentifier}/db/{role}.db.
    Returns 200 with per-role results.
    """
    # Req 7.9: State guard - reject if NOT_INITIALIZED
    state = request.app.state.benchmark_state
    if state.status == BenchmarkStatus.NOT_INITIALIZED:
        return build_error_response(
            error="benchmark_not_initialized",
            message="Benchmark must be initialized before exporting databases",
            status_code=409,
        )

    run_identifier = state.config.run_identifier
    trial_identifier = state.config.trial_identifier
    s3_client = S3Client(bucket=state.config.s3_bucket)

    results: list[ExportResultEntry] = []
    for role in VALID_ROLES:
        result = await _export_single_role(role, s3_client, run_identifier, trial_identifier)
        results.append(result)

    s3_prefix = f"{run_identifier}/{trial_identifier}/db/"
    files_exported = sum(1 for r in results if r.status == "success")

    return ExportResponse(
        message="Database export complete",
        files_exported=files_exported,
        results=results,
        s3_prefix=s3_prefix,
        timestamp=datetime.now(timezone.utc),
    )
