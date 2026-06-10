"""GET /status endpoint for the KASBench Benchmark Runner.

Queries all Load Generator /health endpoints to determine overall benchmark
status and per-generator details.

Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import httpx
import structlog
from fastapi import APIRouter, Request

from kasbench_runner.config import VALID_ROLES
from kasbench_runner.errors import build_error_response
from kasbench_runner.models.responses import LoadGeneratorStatus, StatusResponse
from kasbench_runner.models.state import BenchmarkState, BenchmarkStatus

logger = structlog.get_logger(__name__)

router = APIRouter()

# Timeout for each Load Generator /health query (Req 8.2)
_HEALTH_QUERY_TIMEOUT = 5.0


@router.get("/status")
async def get_status(request: Request) -> StatusResponse:
    """Return the current benchmark status.

    - If not_initialized: returns minimal response (Req 8.1)
    - Otherwise: queries all LG /health endpoints, aggregates status (Req 8.2–8.7)
    """
    state: BenchmarkState = request.app.state.benchmark_state

    # Req 8.1: Not initialized → minimal response
    if state.status == BenchmarkStatus.NOT_INITIALIZED:
        return StatusResponse(
            status=state.status.value,
            start_time=None,
            end_time=None,
            load_generators=[],
        )

    # Req 8.2: Query each LG /health with 5s timeout
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(_HEALTH_QUERY_TIMEOUT),
    ) as client:
        tasks = [
            _query_health(client, role)
            for role in VALID_ROLES
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    # Req 8.7: If any health query fails/timeouts → 500
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            role = VALID_ROLES[i]
            error_detail = str(result)
            logger.error(
                "health_query_failed",
                role=role,
                error=error_detail,
            )
            return build_error_response(  # type: ignore[return-value]
                error="health_query_failed",
                message=f"Failed to query health for load generator '{role}'",
                status_code=500,
                role=role,
                error_detail=error_detail,
            )

    # Build per-generator status list (Req 8.6)
    generator_statuses: list[LoadGeneratorStatus] = []
    for i, role in enumerate(VALID_ROLES):
        health_data: dict = results[i]  # type: ignore[assignment]
        generator_statuses.append(
            LoadGeneratorStatus(
                role=role,
                status=health_data.get("Status", "unknown"),
                start_time=_parse_timestamp(health_data.get("StartTime")),
                end_time=_parse_timestamp(health_data.get("EndTime")),
            )
        )

    # Determine aggregated status (Req 8.3, 8.4, 8.5)
    statuses = [gs.status for gs in generator_statuses]

    if all(s == "success" for s in statuses):
        # Req 8.3: All success → status=success, end_time = max(endTimes)
        end_times = [
            gs.end_time for gs in generator_statuses if gs.end_time is not None
        ]
        state.status = BenchmarkStatus.SUCCESS
        if end_times:
            state.end_time = max(end_times)
    elif any(s == "failed" for s in statuses):
        # Req 8.4: Any failed → status=failed, end_time = min(failed endTimes)
        failed_end_times = [
            gs.end_time
            for gs in generator_statuses
            if gs.status == "failed" and gs.end_time is not None
        ]
        state.status = BenchmarkStatus.FAILED
        if failed_end_times:
            state.end_time = min(failed_end_times)
    # Req 8.5: Otherwise (mixed non-terminal) → leave status unchanged

    # Req 8.6: Return full status response
    return StatusResponse(
        status=state.status.value,
        start_time=state.start_time,
        end_time=state.end_time,
        load_generators=generator_statuses,
    )


async def _query_health(client: httpx.AsyncClient, role: str) -> dict:
    """Query a single Load Generator's /health endpoint.

    Args:
        client: The httpx async client configured with the 5s timeout.
        role: The load generator role (container name).

    Returns:
        Parsed JSON dict from the health response.

    Raises:
        httpx.HTTPError: On connection/timeout failures.
        ValueError: On non-200 response.
    """
    url = f"http://{role}:8080/health"
    response = await client.get(url)
    if response.status_code != 200:
        raise ValueError(
            f"Health query for '{role}' returned HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )
    return response.json()


def _parse_timestamp(value: str | None) -> datetime | None:
    """Parse an ISO 8601 timestamp string to a datetime, or return None."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
