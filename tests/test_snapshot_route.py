"""Tests for POST /snapshot endpoint.

Validates state guards, concurrency protection, error handling,
and successful snapshot collection flow.

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from kasbench_runner.models.state import BenchmarkStatus
from kasbench_runner.services.snapshot_collector import SnapshotResult


@pytest.mark.asyncio
async def test_snapshot_rejects_not_initialized(app, mock_benchmark_state):
    """Returns 409 when benchmark is not initialized."""
    mock_benchmark_state.status = BenchmarkStatus.NOT_INITIALIZED

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/snapshot", json={"phase": "pre"})

    assert response.status_code == 409
    body = response.json()
    assert body["error"] == "not_initialized"


@pytest.mark.asyncio
async def test_snapshot_rejects_when_already_in_progress(app, mock_benchmark_state):
    """Returns 409 when a snapshot is already in progress."""
    mock_benchmark_state.status = BenchmarkStatus.NOT_STARTED
    mock_benchmark_state.snapshot_in_progress = True

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/snapshot", json={"phase": "pre"})

    assert response.status_code == 409
    body = response.json()
    assert body["error"] == "snapshot_in_progress"


@pytest.mark.asyncio
async def test_snapshot_success(app, mock_benchmark_state):
    """Returns 200 with snapshot result on success."""
    mock_benchmark_state.status = BenchmarkStatus.NOT_STARTED

    mock_result = SnapshotResult(files_uploaded=42, s3_prefix="run001/trial001/pre/")

    with patch(
        "kasbench_runner.routes.snapshot.SnapshotCollector"
    ) as mock_collector_cls, patch(
        "kasbench_runner.routes.snapshot.S3Client"
    ):
        mock_collector = AsyncMock()
        mock_collector.collect_snapshot.return_value = mock_result
        mock_collector_cls.return_value = mock_collector

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.post("/snapshot", json={"phase": "pre"})

    assert response.status_code == 200
    body = response.json()
    assert body["phase"] == "pre"
    assert body["filesUploaded"] == 42
    assert body["s3Prefix"] == "run001/trial001/pre/"


@pytest.mark.asyncio
async def test_snapshot_resets_flag_on_success(app, mock_benchmark_state):
    """Snapshot flag is reset to False after successful collection."""
    mock_benchmark_state.status = BenchmarkStatus.NOT_STARTED

    mock_result = SnapshotResult(files_uploaded=1, s3_prefix="run001/trial001/pre/")

    with patch(
        "kasbench_runner.routes.snapshot.SnapshotCollector"
    ) as mock_collector_cls, patch(
        "kasbench_runner.routes.snapshot.S3Client"
    ):
        mock_collector = AsyncMock()
        mock_collector.collect_snapshot.return_value = mock_result
        mock_collector_cls.return_value = mock_collector

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            await client.post("/snapshot", json={"phase": "post"})

    assert mock_benchmark_state.snapshot_in_progress is False


@pytest.mark.asyncio
async def test_snapshot_resets_flag_on_error(app, mock_benchmark_state):
    """Snapshot flag is reset to False even when collection raises."""
    mock_benchmark_state.status = BenchmarkStatus.RUNNING

    from kasbench_runner.errors import SnapshotCollectionError

    with patch(
        "kasbench_runner.routes.snapshot.SnapshotCollector"
    ) as mock_collector_cls, patch(
        "kasbench_runner.routes.snapshot.S3Client"
    ):
        mock_collector = AsyncMock()
        mock_collector.collect_snapshot.side_effect = SnapshotCollectionError(
            resource="nodes", exception_class="ApiError", exception_message="timeout"
        )
        mock_collector_cls.return_value = mock_collector

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.post("/snapshot", json={"phase": "pre"})

    assert response.status_code == 500
    assert mock_benchmark_state.snapshot_in_progress is False


@pytest.mark.asyncio
async def test_snapshot_invalid_phase_error(app, mock_benchmark_state):
    """Returns 422 when InvalidPhaseError is raised."""
    mock_benchmark_state.status = BenchmarkStatus.NOT_STARTED

    from kasbench_runner.errors import InvalidPhaseError

    with patch(
        "kasbench_runner.routes.snapshot.SnapshotCollector"
    ) as mock_collector_cls, patch(
        "kasbench_runner.routes.snapshot.S3Client"
    ):
        mock_collector = AsyncMock()
        mock_collector.collect_snapshot.side_effect = InvalidPhaseError(phase="invalid")
        mock_collector_cls.return_value = mock_collector

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.post("/snapshot", json={"phase": "pre"})

    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "invalid_phase"


@pytest.mark.asyncio
async def test_snapshot_s3_operation_error(app, mock_benchmark_state):
    """Returns 500 when S3OperationError is raised."""
    mock_benchmark_state.status = BenchmarkStatus.NOT_STARTED

    from kasbench_runner.services.s3_client import S3OperationError

    with patch(
        "kasbench_runner.routes.snapshot.SnapshotCollector"
    ) as mock_collector_cls, patch(
        "kasbench_runner.routes.snapshot.S3Client"
    ):
        mock_collector = AsyncMock()
        mock_collector.collect_snapshot.side_effect = S3OperationError(
            bucket="test-bucket",
            key="some/key",
            exception_class="ClientError",
            exception_message="Access Denied",
        )
        mock_collector_cls.return_value = mock_collector

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.post("/snapshot", json={"phase": "post"})

    assert response.status_code == 500
    body = response.json()
    assert body["error"] == "s3_operation_failed"
