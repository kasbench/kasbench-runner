"""POST /start endpoint for the KASBench Benchmark Runner.

Starts benchmark execution by sending /start to all five Load Generators
concurrently, then verifying they all transition to running status.

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9, 7.10
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Request

from kasbench_runner.config import ROLE_PARAMS, VALID_ROLES, RunnerConfig
from kasbench_runner.errors import LoadGeneratorError, build_error_response
from kasbench_runner.models.requests import StartRequest
from kasbench_runner.models.responses import StartResponse
from kasbench_runner.models.state import BenchmarkState, BenchmarkStatus
from kasbench_runner.services.health_checker import check_health
from kasbench_runner.services.load_generator_client import LoadGeneratorClient

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.post("/start")
async def start_benchmark(request: Request, body: StartRequest | None = None) -> StartResponse:
    """Start the benchmark run across all load generators.

    Validates state guards, sends concurrent /start requests to all five
    Load Generators, verifies each transitions to running, and updates state.
    """
    state: BenchmarkState = request.app.state.benchmark_state
    config: RunnerConfig = request.app.state.config

    # Req 7.1: Check initialization_complete
    if not state.initialization_complete:
        return build_error_response(
            error="initialization_incomplete",
            message="Cannot start benchmark: initialization has not completed",
            status_code=409,
            initialization_complete=False,
            kubernetes_installed=state.kubernetes_installed,
            globeco_installed=state.globeco_installed,
            load_generators_installed=state.load_generators_installed,
        )

    # Req 7.2: Check not already running
    if state.status == BenchmarkStatus.RUNNING:
        return build_error_response(
            error="benchmark_already_running",
            message="A benchmark is already in progress",
            status_code=409,
            current_status=state.status.value,
        )

    # Req 7.3: Record benchmark_start_time as UTC now
    start_time = datetime.now(timezone.utc)

    # Req 7.4 & 7.5: POST /start to all five Load Generators concurrently
    init_config = state.config
    kasbench_url = f"{init_config.globeco_url}:{init_config.globeco_port}"

    # Use override if provided, otherwise fall back to init_config value
    benchmark_length_minutes = (
        body.benchmark_length_minutes
        if body and body.benchmark_length_minutes is not None
        else init_config.run_duration_minutes
    )

    lg_client = LoadGeneratorClient()

    async def start_role(role: str) -> None:
        params = ROLE_PARAMS[role]
        payload = {
            "Role": role,
            "BenchmarkLengthMinutes": benchmark_length_minutes,
            "BaseLoadIntensity": params.base_load_intensity,
            "SpawnRate": params.spawn_rate,
            "BaseDelayPercentage": params.base_delay_percentage,
            "KasbenchUrl": kasbench_url,
        }
        await lg_client.start(role, payload)

    try:
        await asyncio.gather(*(start_role(role) for role in VALID_ROLES))
    except LoadGeneratorError as exc:
        # Req 7.6: Non-200 from any → 500 with failed role, status, body
        return build_error_response(
            error="load_generator_start_failed",
            message=f"Failed to start load generator: {exc.message}",
            status_code=500,
            url=exc.context.get("url"),
            method=exc.context.get("method"),
            status_code_received=exc.context.get("status_code"),
            response_body=exc.context.get("response_body", "")[:1000],
        )

    # Req 7.7, 7.8, 7.9: Verify each reports running/healthy via health check
    for role in VALID_ROLES:
        health_url = f"http://{role}:8080/health"
        result = await check_health(
            url=health_url,
            max_attempts=config.health_check_max_attempts,
            interval_seconds=config.health_check_interval_seconds,
            timeout_seconds=config.http_connect_timeout,
            expected_status=200,
            expected_fields={"Status": "running", "Health": "healthy"},
        )

        if not result.success:
            return build_error_response(
                error="load_generator_not_running",
                message=(
                    f"Load generator '{role}' did not report running status "
                    f"after {result.attempts} health check attempts"
                ),
                status_code=500,
                role=role,
                last_status=result.last_status,
                last_body=str(result.last_body)[:1000] if result.last_body else None,
                attempts=result.attempts,
                error_detail=result.error,
            )

        logger.info("load_generator_running_confirmed", role=role)

    # Req 7.10: Set status to running and return start timestamp
    state.status = BenchmarkStatus.RUNNING
    state.start_time = start_time

    logger.info("benchmark_started", start_time=start_time.isoformat())

    return StartResponse(start_time=start_time)
