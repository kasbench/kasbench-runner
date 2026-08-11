"""POST /rollout/wait and POST /rollout/all endpoints for the KASBench Benchmark Runner.

Orchestrates Kubernetes Deployment rollout monitoring via the RolloutMonitor
service. Supports waiting for a single deployment or all configured deployments.

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.9, 2.1, 2.4, 2.5, 2.7,
              4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8,
              5.1, 5.2, 5.3, 5.4, 5.5
"""

from __future__ import annotations

import time

import structlog
from fastapi import APIRouter, Request

from kasbench_runner.errors import (
    DeploymentNotFoundError,
    KubernetesApiError,
    RolloutTimeoutError,
    RolloutUnrecoverableError,
    build_error_response,
)
from kasbench_runner.models.requests import RolloutAllRequest, RolloutWaitRequest
from kasbench_runner.models.responses import RolloutAllResponse, RolloutWaitResponse
from kasbench_runner.services.rollout_monitor import RolloutMonitor

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.post("/rollout/wait")
async def wait_for_rollout(
    request: Request, body: RolloutWaitRequest
) -> RolloutWaitResponse:
    """Wait for a single deployment rollout to complete."""
    log = logger.bind(
        deployment_name=body.deployment_name,
        namespace=body.namespace,
        timeout=body.timeout,
    )
    log.info("rollout_wait_start")

    monitor = RolloutMonitor()

    try:
        elapsed = await monitor.wait_for_rollout(
            body.deployment_name, body.namespace, body.timeout
        )
        return RolloutWaitResponse(
            deployment_name=body.deployment_name,
            namespace=body.namespace,
            elapsed_seconds=elapsed,
        )
    except DeploymentNotFoundError as exc:
        log.warning("rollout_deployment_not_found", error=exc.message)
        return build_error_response(
            error=exc.error,
            message=exc.message,
            status_code=404,
            **exc.context,
        )
    except (RolloutTimeoutError, RolloutUnrecoverableError, KubernetesApiError) as exc:
        log.error("rollout_wait_failed", error=exc.error, message=exc.message)
        return build_error_response(
            error=exc.error,
            message=exc.message,
            status_code=500,
            **exc.context,
        )


@router.post("/rollout/all")
async def wait_for_all_rollouts(
    request: Request, body: RolloutAllRequest
) -> RolloutAllResponse:
    """Wait for all configured deployments and statefulsets to roll out."""
    config = request.app.state.config
    state = request.app.state.benchmark_state
    deployments = config.rollout_deployments
    statefulsets = config.rollout_statefulsets

    # When autoscaler is KEDA, exclude scale-to-zero deployments from rollout checks
    if state.config and state.config.autoscaler.lower() == "keda":
        scale_to_zero = set(
            (d.name, d.namespace) for d in config.scale_to_zero_deployments
        )
        skipped = [d for d in deployments if (d.name, d.namespace) in scale_to_zero]
        deployments = [d for d in deployments if (d.name, d.namespace) not in scale_to_zero]
        if skipped:
            logger.info(
                "rollout_all_skip_scale_to_zero",
                skipped=[f"{d.namespace}/{d.name}" for d in skipped],
                reason="autoscaler=keda",
            )

    log = logger.bind(
        deployment_count=len(deployments),
        statefulset_count=len(statefulsets),
        timeout=body.timeout,
    )
    log.info("rollout_all_start")

    monitor = RolloutMonitor()
    start_time = time.monotonic()

    try:
        await monitor.wait_for_all_rollouts(deployments, body.timeout, statefulsets=statefulsets)
        elapsed = time.monotonic() - start_time
        total_checked = len(deployments) + len(statefulsets)
        log.info(
            "rollout_all_complete",
            deployments_checked=total_checked,
            elapsed_seconds=round(elapsed, 1),
        )
        return RolloutAllResponse(
            deployments_checked=total_checked,
            elapsed_seconds=elapsed,
        )
    except (RolloutTimeoutError, RolloutUnrecoverableError, KubernetesApiError) as exc:
        log.error("rollout_all_failed", error=exc.error, message=exc.message)
        return build_error_response(
            error=exc.error,
            message=exc.message,
            status_code=500,
            **exc.context,
        )
