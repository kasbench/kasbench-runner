"""GET /output/{role} endpoint for the KASBench Benchmark Runner.

Streams the output file from a Load Generator's /download-output endpoint.

Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6
"""

from __future__ import annotations

from typing import AsyncIterator

import httpx
import structlog
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from kasbench_runner.config import VALID_ROLES
from kasbench_runner.errors import build_error_response

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
