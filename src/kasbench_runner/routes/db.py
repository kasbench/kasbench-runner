"""GET /db/{role} endpoint for the KASBench Benchmark Runner.

Streams the SQLite database file from a Load Generator container.

Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7
"""

from __future__ import annotations

import httpx
import structlog
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from kasbench_runner.config import VALID_ROLES
from kasbench_runner.errors import build_error_response

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
