"""Property tests for POST /logs/{namespace}/export endpoint.

Task 2.2 - Property 1: State guard accepts all initialized states
Task 2.3 - Property 6: Response status code correctness

Validates: Requirements 2.2, 7.1, 7.2
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from kasbench_runner.models.state import BenchmarkStatus
from kasbench_runner.services.log_collector import LogCollectionResult


# -- Strategies --

# All statuses that should be accepted (not NOT_INITIALIZED)
initialized_statuses = st.sampled_from([
    BenchmarkStatus.NOT_STARTED,
    BenchmarkStatus.RUNNING,
    BenchmarkStatus.SUCCESS,
    BenchmarkStatus.FAILED,
    BenchmarkStatus.ABORTED,
])

# Namespace strategy: non-empty strings that form valid URL path segments
namespace_st = st.from_regex(r"[a-z][a-z0-9\-]{0,20}", fullmatch=True)


# -- Task 2.2: Property 1 - State guard accepts all initialized states --


@pytest.mark.asyncio
@settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(status=initialized_statuses, namespace=namespace_st)
async def test_state_guard_accepts_initialized_states(
    app, mock_benchmark_state, status, namespace
):
    """Property 1: For any BenchmarkState status in {NOT_STARTED, RUNNING,
    SUCCESS, FAILED, ABORTED}, the endpoint SHALL accept the request
    (not return 409 with not_initialized).

    **Validates: Requirements 2.2**
    """
    mock_benchmark_state.status = status

    mock_result = LogCollectionResult(
        files_exported=0,
        s3_prefix=f"run001/trial001/logs/{namespace}/",
        errors=[],
    )

    with patch(
        "kasbench_runner.routes.logs.LogCollector"
    ) as mock_collector_cls, patch(
        "kasbench_runner.routes.logs.S3Client"
    ):
        mock_collector = AsyncMock()
        mock_collector.collect_and_upload.return_value = mock_result
        mock_collector_cls.return_value = mock_collector

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.post(f"/logs/{namespace}/export")

    assert response.status_code != 409
    assert response.status_code in (200, 207)


@pytest.mark.asyncio
async def test_state_guard_rejects_not_initialized(app, mock_benchmark_state):
    """State guard: when status is NOT_INITIALIZED, return 409 with
    error 'not_initialized'.

    **Validates: Requirements 2.2**
    """
    mock_benchmark_state.status = BenchmarkStatus.NOT_INITIALIZED

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/logs/default/export")

    assert response.status_code == 409
    body = response.json()
    assert body["error"] == "not_initialized"


# -- Task 2.3: Property 6 - Response status code correctness --


@pytest.mark.asyncio
@settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(files_exported=st.integers(min_value=1, max_value=100))
async def test_response_200_when_no_errors(
    app, mock_benchmark_state, files_exported
):
    """Property 6: When all collected logs are uploaded successfully (no errors),
    the response SHALL be HTTP 200.

    **Validates: Requirements 7.1, 7.2**
    """
    mock_benchmark_state.status = BenchmarkStatus.SUCCESS

    mock_result = LogCollectionResult(
        files_exported=files_exported,
        s3_prefix="run001/trial001/logs/default/",
        errors=[],
    )

    with patch(
        "kasbench_runner.routes.logs.LogCollector"
    ) as mock_collector_cls, patch(
        "kasbench_runner.routes.logs.S3Client"
    ):
        mock_collector = AsyncMock()
        mock_collector.collect_and_upload.return_value = mock_result
        mock_collector_cls.return_value = mock_collector

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.post("/logs/default/export")

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "Logs exported successfully"
    assert body["filesExported"] == files_exported


@pytest.mark.asyncio
@settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    files_exported=st.integers(min_value=1, max_value=50),
    error_count=st.integers(min_value=1, max_value=10),
)
async def test_response_207_when_partial_errors(
    app, mock_benchmark_state, files_exported, error_count
):
    """Property 6: When at least one operation fails but at least one succeeds,
    the response SHALL be HTTP 207 with an errors array.

    **Validates: Requirements 7.1, 7.2**
    """
    mock_benchmark_state.status = BenchmarkStatus.SUCCESS

    errors = [
        {
            "pod": f"pod-{i}",
            "container": "main",
            "phase": "collection",
            "error": "container logs not available",
        }
        for i in range(error_count)
    ]

    mock_result = LogCollectionResult(
        files_exported=files_exported,
        s3_prefix="run001/trial001/logs/default/",
        errors=errors,
    )

    with patch(
        "kasbench_runner.routes.logs.LogCollector"
    ) as mock_collector_cls, patch(
        "kasbench_runner.routes.logs.S3Client"
    ):
        mock_collector = AsyncMock()
        mock_collector.collect_and_upload.return_value = mock_result
        mock_collector_cls.return_value = mock_collector

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.post("/logs/default/export")

    assert response.status_code == 207
    body = response.json()
    assert "errors" in body
    assert len(body["errors"]) == error_count
    assert body["filesExported"] == files_exported


@pytest.mark.asyncio
async def test_response_200_zero_files_no_errors(app, mock_benchmark_state):
    """Edge case: zero files exported with no errors still returns 200.

    **Validates: Requirements 7.1**
    """
    mock_benchmark_state.status = BenchmarkStatus.RUNNING

    mock_result = LogCollectionResult(
        files_exported=0,
        s3_prefix="run001/trial001/logs/empty-ns/",
        errors=[],
    )

    with patch(
        "kasbench_runner.routes.logs.LogCollector"
    ) as mock_collector_cls, patch(
        "kasbench_runner.routes.logs.S3Client"
    ):
        mock_collector = AsyncMock()
        mock_collector.collect_and_upload.return_value = mock_result
        mock_collector_cls.return_value = mock_collector

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.post("/logs/empty-ns/export")

    assert response.status_code == 200
    body = response.json()
    assert body["filesExported"] == 0
    assert body["message"] == "Logs exported successfully"
