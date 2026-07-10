"""POST /shutdown endpoint for the KASBench Benchmark Runner.

Deletes Kubernetes namespaces sequentially to release claimed storage volumes
before cluster destruction.

Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import kr8s
import structlog
from fastapi import APIRouter, Request

from kasbench_runner.errors import build_error_response
from kasbench_runner.models.responses import NamespaceResult, ShutdownResponse
from kasbench_runner.models.state import BenchmarkState, BenchmarkStatus

logger = structlog.get_logger(__name__)

router = APIRouter()

SHUTDOWN_NAMESPACES = ["globeco", "elasticsearch", "observability", "monitoring"]
NAMESPACE_DELETION_TIMEOUT = 60  # seconds per namespace


async def _delete_namespace(name: str) -> NamespaceResult:
    """Delete a single Kubernetes namespace with a 60s timeout.

    Returns a NamespaceResult indicating success or failure with error detail.
    """
    try:

        async def _do_delete() -> None:
            api = await kr8s.asyncio.api()
            namespaces = await api.get("namespaces", field_selector=f"metadata.name={name}")
            if namespaces:
                ns = namespaces[0]
                await ns.delete()
                logger.info("namespace_deletion_initiated", namespace=name)
            else:
                logger.info("namespace_not_found_skipping", namespace=name)

        await asyncio.wait_for(_do_delete(), timeout=NAMESPACE_DELETION_TIMEOUT)
        return NamespaceResult(namespace=name, status="deleted")

    except asyncio.TimeoutError:
        error_msg = "Namespace deletion timed out after 60 seconds"
        logger.warning("namespace_deletion_timeout", namespace=name)
        return NamespaceResult(namespace=name, status="failed", error=error_msg)

    except Exception as exc:
        error_msg = str(exc)
        logger.warning("namespace_deletion_failed", namespace=name, error=error_msg)
        return NamespaceResult(namespace=name, status="failed", error=error_msg)


@router.post("/shutdown")
async def shutdown(request: Request) -> ShutdownResponse:
    """Delete benchmark namespaces sequentially to release storage volumes.

    Deletes namespaces in order: globeco, elasticsearch, observability, monitoring.
    Each deletion has a 60s timeout. Failures are recorded but do not stop
    processing of remaining namespaces.
    """
    state: BenchmarkState = request.app.state.benchmark_state

    # Req 9.5: Reject if NOT_INITIALIZED
    if state.status == BenchmarkStatus.NOT_INITIALIZED:
        return build_error_response(
            error="benchmark_not_initialized",
            message="Cannot shutdown: benchmark has not been initialized",
            status_code=409,
            current_status=state.status.value,
        )

    # Req 9.6: Reject if RUNNING
    if state.status == BenchmarkStatus.RUNNING:
        return build_error_response(
            error="benchmark_running",
            message="Cannot shutdown: benchmark is currently running",
            status_code=409,
            current_status=state.status.value,
        )

    # Req 9.1, 9.2: Delete namespaces sequentially with 60s timeout each
    results: list[NamespaceResult] = []
    for ns_name in SHUTDOWN_NAMESPACES:
        logger.info("deleting_namespace", namespace=ns_name)
        result = await _delete_namespace(ns_name)
        results.append(result)

    timestamp = datetime.now(timezone.utc)

    logger.info(
        "shutdown_complete",
        results=[r.model_dump() for r in results],
        timestamp=timestamp.isoformat(),
    )

    # Req 9.4: Return 200 with per-namespace results and timestamp
    return ShutdownResponse(results=results, timestamp=timestamp)
