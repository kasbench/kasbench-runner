"""POST /abort endpoint for the KASBench Benchmark Runner.

Aborts a running benchmark by sending /abort to all five Load Generators
concurrently (best-effort), then updating state to aborted.

Requirements: 16.1, 16.2, 16.3, 16.4, 16.5
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Request

from kasbench_runner.config import VALID_ROLES
from kasbench_runner.errors import LoadGeneratorError, build_error_response
from kasbench_runner.models.responses import AbortResponse
from kasbench_runner.models.state import BenchmarkState, BenchmarkStatus
from kasbench_runner.services.load_generator_client import LoadGeneratorClient

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.post("/abort")
async def abort_benchmark(request: Request) -> AbortResponse:
    """Abort the currently running benchmark.

    Sends POST /abort to all five Load Generators concurrently (best-effort),
    collects per-role results, sets state to aborted, and returns the abort
    timestamp with per-role outcome.
    """
    state: BenchmarkState = request.app.state.benchmark_state

    # Req 16.5: If status not running → 409
    if state.status != BenchmarkStatus.RUNNING:
        return build_error_response(
            error="benchmark_not_running",
            message="Cannot abort: benchmark is not currently running",
            status_code=409,
            current_status=state.status.value,
        )

    # Req 16.1: POST /abort to all 5 LGs concurrently, best-effort
    lg_client = LoadGeneratorClient()
    results: dict[str, str] = {}

    async def abort_role(role: str) -> tuple[str, str]:
        """Attempt to abort a single role; return (role, result_string)."""
        try:
            await lg_client.abort(role)
            return (role, "success")
        except LoadGeneratorError as exc:
            # Req 16.3: Non-200 from any → log warning but don't fail
            logger.warning(
                "abort_request_failed",
                role=role,
                error=exc.message,
                status_code=exc.context.get("status_code"),
            )
            return (role, exc.message)
        except Exception as exc:
            logger.warning(
                "abort_request_unexpected_error",
                role=role,
                error=str(exc),
            )
            return (role, str(exc))

    # Gather all results concurrently (return_exceptions=False since we handle inside)
    role_results = await asyncio.gather(
        *(abort_role(role) for role in VALID_ROLES)
    )

    for role, result in role_results:
        results[role] = result

    # Req 16.2: Set status to aborted, record end_time as UTC now
    abort_time = datetime.now(timezone.utc)
    state.status = BenchmarkStatus.ABORTED
    state.end_time = abort_time

    logger.info(
        "benchmark_aborted",
        abort_time=abort_time.isoformat(),
        results=results,
    )

    # Req 16.4: Return 200 with abort timestamp and per-role results
    return AbortResponse(abort_time=abort_time, results=results)
