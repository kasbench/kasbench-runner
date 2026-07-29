"""POST /shutdown endpoint for the KASBench Benchmark Runner.

Performs Helm uninstalls of GlobeCo and Prometheus releases to free EBS volumes
before cluster destruction.

Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Request

from kasbench_runner.errors import build_error_response
from kasbench_runner.models.responses import HelmUninstallResult, ShutdownResponse
from kasbench_runner.models.state import BenchmarkState, BenchmarkStatus

logger = structlog.get_logger(__name__)

router = APIRouter()

# Helm releases to uninstall (in order): GlobeCo first, then Prometheus
HELM_RELEASES = [
    {"release": "globeco", "namespace": "globeco"},
    {"release": "prometheus", "namespace": "monitoring"},
]

HELM_UNINSTALL_TIMEOUT = 120  # seconds per release


async def _helm_uninstall(release: str, namespace: str) -> HelmUninstallResult:
    """Uninstall a single Helm release with a timeout.

    Returns a HelmUninstallResult indicating success or failure with error detail.
    """
    cmd = ["helm", "uninstall", release, "--namespace", namespace]

    try:

        async def _do_uninstall() -> tuple[int, str, str]:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            return proc.returncode, stdout.decode().strip(), stderr.decode().strip()

        returncode, stdout, stderr = await asyncio.wait_for(
            _do_uninstall(), timeout=HELM_UNINSTALL_TIMEOUT
        )

        if returncode != 0:
            logger.warning(
                "helm_uninstall_failed",
                release=release,
                namespace=namespace,
                exit_code=returncode,
                stderr=stderr,
            )
            return HelmUninstallResult(
                release=release,
                namespace=namespace,
                status="failed",
                error=stderr or f"Exit code {returncode}",
            )

        logger.info(
            "helm_uninstall_success",
            release=release,
            namespace=namespace,
            stdout=stdout[:200],
        )
        return HelmUninstallResult(
            release=release, namespace=namespace, status="uninstalled"
        )

    except asyncio.TimeoutError:
        error_msg = f"Helm uninstall timed out after {HELM_UNINSTALL_TIMEOUT} seconds"
        logger.warning(
            "helm_uninstall_timeout", release=release, namespace=namespace
        )
        return HelmUninstallResult(
            release=release, namespace=namespace, status="failed", error=error_msg
        )

    except Exception as exc:
        error_msg = str(exc)
        logger.warning(
            "helm_uninstall_error",
            release=release,
            namespace=namespace,
            error=error_msg,
        )
        return HelmUninstallResult(
            release=release, namespace=namespace, status="failed", error=error_msg
        )


PVC_DELETE_TIMEOUT = 60  # seconds


async def _delete_alertmanager_pvc() -> None:
    """Best-effort deletion of the Prometheus Alertmanager PVC.

    This PVC (storage-prometheus-alertmanager-0 in the monitoring namespace)
    is not cleaned up automatically by `helm uninstall`. We attempt to delete
    it here so the underlying EBS volume is released before cluster teardown.
    Failures are logged but never propagate — shutdown proceeds regardless.
    """
    pvc_name = "storage-prometheus-alertmanager-0"
    namespace = "monitoring"
    cmd = ["kubectl", "delete", "pvc", pvc_name, "--namespace", namespace]

    try:

        async def _do_delete() -> tuple[int, str, str]:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            return proc.returncode, stdout.decode().strip(), stderr.decode().strip()

        returncode, stdout, stderr = await asyncio.wait_for(
            _do_delete(), timeout=PVC_DELETE_TIMEOUT
        )

        if returncode == 0:
            logger.info(
                "pvc_delete_success",
                pvc=pvc_name,
                namespace=namespace,
                stdout=stdout[:200],
            )
        else:
            logger.warning(
                "pvc_delete_failed",
                pvc=pvc_name,
                namespace=namespace,
                exit_code=returncode,
                stderr=stderr,
            )

    except asyncio.TimeoutError:
        logger.warning(
            "pvc_delete_timeout",
            pvc=pvc_name,
            namespace=namespace,
            timeout=PVC_DELETE_TIMEOUT,
        )
    except Exception as exc:
        logger.warning(
            "pvc_delete_error",
            pvc=pvc_name,
            namespace=namespace,
            error=str(exc),
        )


@router.post("/shutdown")
async def shutdown(request: Request) -> ShutdownResponse:
    """Uninstall Helm releases to free EBS volumes before cluster destruction.

    Uninstalls GlobeCo first, then Prometheus. Each uninstall has a timeout.
    Failures are recorded but do not stop processing of remaining releases.
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

    # Uninstall Helm releases sequentially (GlobeCo then Prometheus)
    results: list[HelmUninstallResult] = []
    for rel in HELM_RELEASES:
        logger.info(
            "helm_uninstall_starting",
            release=rel["release"],
            namespace=rel["namespace"],
        )
        result = await _helm_uninstall(rel["release"], rel["namespace"])
        results.append(result)

    # Best-effort cleanup of the Prometheus Alertmanager PVC that doesn't
    # get removed automatically by the Helm uninstall.
    await _delete_alertmanager_pvc()

    timestamp = datetime.now(timezone.utc)

    logger.info(
        "shutdown_complete",
        results=[r.model_dump() for r in results],
        timestamp=timestamp.isoformat(),
    )

    # Req 9.4: Return 200 with per-release results and timestamp
    return ShutdownResponse(results=results, timestamp=timestamp)
