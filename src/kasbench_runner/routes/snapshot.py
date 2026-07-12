"""POST /snapshot endpoint for the KASBench Benchmark Runner.

Orchestrates cluster state snapshot collection and S3 upload via
the SnapshotCollector service.

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Request

from kasbench_runner.errors import (
    InvalidPhaseError,
    SnapshotCollectionError,
    build_error_response,
)
from kasbench_runner.models.requests import SnapshotRequest
from kasbench_runner.models.responses import SnapshotResponse
from kasbench_runner.models.state import BenchmarkStatus
from kasbench_runner.services.s3_client import S3Client, S3OperationError
from kasbench_runner.services.snapshot_collector import SnapshotCollector

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.post("/snapshot")
async def take_snapshot(request: Request, body: SnapshotRequest) -> SnapshotResponse:
    """Collect cluster snapshot and upload to S3."""
    state = request.app.state.benchmark_state

    # Check benchmark is initialized (not NOT_INITIALIZED)
    if state.status == BenchmarkStatus.NOT_INITIALIZED:
        return build_error_response(
            error="not_initialized",
            message="Benchmark must be initialized before taking a snapshot",
            status_code=409,
        )

    # Check snapshot not already in progress
    if state.snapshot_in_progress:
        return build_error_response(
            error="snapshot_in_progress",
            message="A snapshot operation is already in progress",
            status_code=409,
        )

    state.snapshot_in_progress = True
    try:
        s3_client = S3Client(bucket=state.config.s3_bucket)
        collector = SnapshotCollector(s3_client=s3_client)
        result = await collector.collect_snapshot(
            phase=body.phase,
            run_identifier=state.config.run_identifier,
            trial_identifier=state.config.trial_identifier,
        )
        return SnapshotResponse(
            phase=body.phase,
            files_uploaded=result.files_uploaded,
            s3_prefix=result.s3_prefix,
        )
    except InvalidPhaseError as exc:
        return build_error_response(
            error=exc.error, message=exc.message, status_code=422, **exc.context
        )
    except SnapshotCollectionError as exc:
        return build_error_response(
            error=exc.error, message=exc.message, status_code=500, **exc.context
        )
    except S3OperationError as exc:
        return build_error_response(
            error=exc.error, message=exc.message, status_code=500, **exc.context
        )
    finally:
        state.snapshot_in_progress = False
