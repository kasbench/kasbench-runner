"""Output endpoints for the KASBench Benchmark Runner.

GET /output/{role} - Streams output file from a Load Generator.
POST /output/export - Exports output from all roles to S3.
POST /output/export/{role} - Exports output from a single role to S3.

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import AsyncIterator

import httpx
import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from kasbench_runner.config import VALID_ROLES
from kasbench_runner.errors import build_error_response
from kasbench_runner.models.responses import ExportResponse, ExportResultEntry
from kasbench_runner.models.state import BenchmarkState, BenchmarkStatus
from kasbench_runner.services.s3_client import S3Client, S3OperationError

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("/output/{role}")
async def get_output(role: str):
    """Stream the output file from a Load Generator.

    Validates the role, then proxies the request to the Load Generator's
    /download-output endpoint as a streaming text/plain response.
    """
    # Req 9.5: Validate role parameter
    if role not in VALID_ROLES:
        return build_error_response(
            error="invalid_role",
            message=f"Invalid role: '{role}'",
            status_code=400,
            invalid_value=role,
            valid_roles=list(VALID_ROLES),
        )

    # Req 9.1: Forward to GET http://{role}:8080/download-output
    url = f"http://{role}:8080/download-output"

    try:
        client = httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=None, write=None, pool=None))
        response = await client.send(
            client.build_request("GET", url),
            stream=True,
        )

        # Req 9.3: Forward 409 (subprocess active)
        if response.status_code == 409:
            body = await response.aread()
            await response.aclose()
            await client.aclose()
            return build_error_response(
                error="subprocess_active",
                message="Load generator subprocess is still active",
                status_code=409,
                role=role,
                upstream_status=409,
            )

        # Req 9.4: Forward 404 (no output available)
        if response.status_code == 404:
            body = await response.aread()
            await response.aclose()
            await client.aclose()
            return build_error_response(
                error="no_output_available",
                message="No output available for this role",
                status_code=404,
                role=role,
                upstream_status=404,
            )

        # Req 9.2: Stream text/plain response to client on 200
        if response.status_code == 200:

            async def stream_content() -> AsyncIterator[bytes]:
                try:
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        yield chunk
                finally:
                    await response.aclose()
                    await client.aclose()

            return StreamingResponse(
                content=stream_content(),
                media_type="text/plain",
                status_code=200,
            )

        # Unexpected status code - close and return error
        body = await response.aread()
        await response.aclose()
        await client.aclose()
        return build_error_response(
            error="unexpected_upstream_status",
            message=f"Unexpected status from load generator: {response.status_code}",
            status_code=502,
            role=role,
            upstream_status=response.status_code,
        )

    except (httpx.ConnectTimeout, httpx.ConnectError) as exc:
        # Req 9.6: Connection timeout 10s → 502
        logger.error(
            "output_connection_failed",
            role=role,
            url=url,
            error=str(exc),
        )
        return build_error_response(
            error="load_generator_connection_failed",
            message=f"Failed to connect to load generator '{role}'",
            status_code=502,
            role=role,
            url=url,
            error_detail=str(exc),
        )
    except httpx.HTTPError as exc:
        logger.error(
            "output_request_failed",
            role=role,
            url=url,
            error=str(exc),
        )
        return build_error_response(
            error="load_generator_request_failed",
            message=f"Request to load generator '{role}' failed",
            status_code=502,
            role=role,
            url=url,
            error_detail=str(exc),
        )


async def _export_single_role(
    role: str, s3_client: S3Client, run_identifier: str, trial_identifier: str
) -> ExportResultEntry:
    """Fetch output from a single role's LG and upload to S3.

    Returns an ExportResultEntry indicating success or failure.
    """
    url = f"http://{role}:8080/download-output"
    s3_key = f"{run_identifier}/{trial_identifier}/output/{role}-output.txt"

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=None, write=None, pool=None)
        ) as client:
            response = await client.get(url)

        if response.status_code != 200:
            return ExportResultEntry(
                role=role,
                status="failed",
                error=f"Load generator returned HTTP {response.status_code}",
            )

        # Upload to S3
        await s3_client.upload_bytes(key=s3_key, data=response.content, content_type="text/plain")

        return ExportResultEntry(role=role, status="success", s3_key=s3_key)

    except (httpx.ConnectTimeout, httpx.ConnectError) as exc:
        logger.error("output_export_connection_failed", role=role, url=url, error=str(exc))
        return ExportResultEntry(
            role=role,
            status="failed",
            error=f"Failed to connect to load generator '{role}': {exc}",
        )
    except httpx.HTTPError as exc:
        logger.error("output_export_request_failed", role=role, url=url, error=str(exc))
        return ExportResultEntry(
            role=role,
            status="failed",
            error=f"Request to load generator '{role}' failed: {exc}",
        )
    except S3OperationError as exc:
        logger.error("output_export_s3_failed", role=role, s3_key=s3_key, error=str(exc))
        return ExportResultEntry(
            role=role,
            status="failed",
            error=f"S3 upload failed for key '{s3_key}': {exc.message}",
        )


@router.post("/output/export/{role}")
async def post_output_export_role(request: Request, role: str) -> JSONResponse:
    """Export output from a single Load Generator role to S3.

    Fetches output via GET http://{role}:8080/download-output and uploads
    to S3 at {s3Bucket}/{runIdentifier}/{trialIdentifier}/output/{role}-output.txt.
    """
    state: BenchmarkState = request.app.state.benchmark_state

    # Req 6.8: State guard — reject if NOT_INITIALIZED
    if state.status == BenchmarkStatus.NOT_INITIALIZED:
        return build_error_response(
            error="benchmark_not_initialized",
            message="Benchmark must be initialized before exporting output",
            status_code=409,
            current_status=state.status.value,
        )

    # Req 6.5: Validate role parameter
    if role not in VALID_ROLES:
        return build_error_response(
            error="invalid_role",
            message=f"Invalid role: '{role}'",
            status_code=400,
            invalid_value=role,
            valid_roles=list(VALID_ROLES),
        )

    config = state.config
    run_identifier = config.run_identifier
    trial_identifier = config.trial_identifier
    s3_bucket = config.s3_bucket

    log = logger.bind(
        role=role,
        run_identifier=run_identifier,
        trial_identifier=trial_identifier,
    )
    log.info("output_export_single_start")

    s3_client = S3Client(bucket=s3_bucket)
    result = await _export_single_role(role, s3_client, run_identifier, trial_identifier)

    if result.status == "failed":
        # Determine error type for status code
        error = result.error or ""
        if "Failed to connect" in error or "Request to load generator" in error:
            log.error("output_export_single_lg_failed", error=error)
            return build_error_response(
                error="load_generator_connection_failed",
                message=f"Failed to connect to load generator '{role}'",
                status_code=502,
                role=role,
                error_detail=error,
            )
        elif "S3 upload failed" in error:
            log.error("output_export_single_s3_failed", error=error)
            return build_error_response(
                error="s3_operation_failed",
                message=f"S3 upload failed for role '{role}'",
                status_code=500,
                role=role,
                error_detail=error,
            )
        else:
            # LG returned non-200
            log.error("output_export_single_upstream_failed", error=error)
            return build_error_response(
                error="load_generator_connection_failed",
                message=f"Load generator '{role}' returned an error",
                status_code=502,
                role=role,
                error_detail=error,
            )

    s3_key = result.s3_key
    log.info("output_export_single_success", s3_key=s3_key)

    response = ExportResponse(
        message="Export complete",
        files_exported=1,
        results=[result],
        s3_key=s3_key,
        timestamp=datetime.now(timezone.utc),
    )

    return JSONResponse(status_code=200, content=response.model_dump(by_alias=True, mode="json"))


@router.post("/output/export")
async def post_output_export_all(request: Request) -> JSONResponse:
    """Export output from all Load Generator roles to S3.

    Iterates all 5 roles, fetches output from each, and uploads to S3.
    Returns 200 if all succeed, or 207 if partial failures occur.
    """
    state: BenchmarkState = request.app.state.benchmark_state

    # Req 6.8: State guard — reject if NOT_INITIALIZED
    if state.status == BenchmarkStatus.NOT_INITIALIZED:
        return build_error_response(
            error="benchmark_not_initialized",
            message="Benchmark must be initialized before exporting output",
            status_code=409,
            current_status=state.status.value,
        )

    config = state.config
    run_identifier = config.run_identifier
    trial_identifier = config.trial_identifier
    s3_bucket = config.s3_bucket
    s3_prefix = f"{run_identifier}/{trial_identifier}/output/"

    log = logger.bind(
        run_identifier=run_identifier,
        trial_identifier=trial_identifier,
        s3_prefix=s3_prefix,
    )
    log.info("output_export_all_start")

    s3_client = S3Client(bucket=s3_bucket)

    results: list[ExportResultEntry] = []
    for role in VALID_ROLES:
        result = await _export_single_role(role, s3_client, run_identifier, trial_identifier)
        results.append(result)

    # Determine outcome
    failed_results = [r for r in results if r.status == "failed"]
    success_count = len(results) - len(failed_results)

    if not failed_results:
        # All succeeded — 200
        log.info("output_export_all_success", files_exported=success_count)
        response = ExportResponse(
            message="Export complete",
            files_exported=success_count,
            results=results,
            s3_prefix=s3_prefix,
            timestamp=datetime.now(timezone.utc),
        )
        return JSONResponse(status_code=200, content=response.model_dump(by_alias=True, mode="json"))
    else:
        # Partial failures — 207
        log.warning(
            "output_export_all_partial",
            success_count=success_count,
            failed_count=len(failed_results),
        )
        response = ExportResponse(
            message="Export completed with errors",
            files_exported=success_count,
            results=results,
            s3_prefix=s3_prefix,
            timestamp=datetime.now(timezone.utc),
        )
        return JSONResponse(status_code=207, content=response.model_dump(by_alias=True, mode="json"))
