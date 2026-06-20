"""Shared test fixtures for KASBench Runner test suite.

Provides reusable fixtures for:
- Mock BenchmarkState with realistic time bounds and config
- FastAPI test client with mocked application state
- Moto-based S3 mock with pre-created bucket
- Respx-based Prometheus HTTP mock

Requirements: 2.4, 6.2, 7.1
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import boto3
import httpx
import pytest
import respx
from moto import mock_aws

from kasbench_runner.app import create_app
from kasbench_runner.models.requests import InitializeRequest
from kasbench_runner.models.state import BenchmarkState, BenchmarkStatus

TEST_BUCKET = "test-bucket"
TEST_RUN_IDENTIFIER = "run001"
TEST_TRIAL_IDENTIFIER = "trial001"
TEST_CONTROL_PLANE_NODE = "cp-node"


@pytest.fixture
def mock_config() -> InitializeRequest:
    """Create a minimal InitializeRequest for testing."""
    return InitializeRequest(
        autoscaler="karpenter",
        controlPlaneNode=TEST_CONTROL_PLANE_NODE,
        amdWorkerNodes=["worker-1"],
        s3Bucket=TEST_BUCKET,
        globecoUrl="http://globeco:8080",
        runIdentifier=TEST_RUN_IDENTIFIER,
        trialIdentifier=TEST_TRIAL_IDENTIFIER,
    )


@pytest.fixture
def mock_benchmark_state(mock_config: InitializeRequest) -> BenchmarkState:
    """Create a BenchmarkState in SUCCESS status with realistic time bounds.

    The state has:
    - status = SUCCESS (terminal, allows metrics collection)
    - start_time = 2024-06-10T12:00:00 UTC
    - end_time = 2024-06-10T12:05:00 UTC (5 minutes later)
    - config = InitializeRequest with run001/trial001/test-bucket/cp-node
    """
    return BenchmarkState(
        status=BenchmarkStatus.SUCCESS,
        config=mock_config,
        start_time=datetime(2024, 6, 10, 12, 0, 0, tzinfo=timezone.utc),
        end_time=datetime(2024, 6, 10, 12, 5, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def app(mock_benchmark_state: BenchmarkState):
    """Create a FastAPI test app with mocked benchmark state.

    Bypasses the lifespan (which reads env vars and creates real state)
    and injects the mock state directly onto app.state.
    """
    application = create_app()

    # Override the lifespan-initialized state with our mock
    application.state.benchmark_state = mock_benchmark_state

    return application


@pytest.fixture
async def test_client(app) -> httpx.AsyncClient:
    """Create an async httpx test client bound to the FastAPI app.

    Uses httpx.ASGITransport for in-process async testing without
    starting a real server.
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        yield client


@pytest.fixture
def mock_s3():
    """Provide a moto-based S3 mock with the test bucket pre-created.

    Sets AWS credentials to dummy values and creates the test bucket
    before yielding the boto3 S3 client. Teardown is handled by moto.
    """
    # Set dummy AWS credentials for moto
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"

    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=TEST_BUCKET)
        yield s3


@pytest.fixture
def mock_prometheus() -> respx.MockRouter:
    """Provide a respx mock router for Prometheus HTTP calls.

    Mocks GET requests to the Prometheus range query endpoint on the
    test control plane node. By default, all requests return a successful
    Prometheus response. Tests can customize route behavior as needed.

    Usage in tests:
        def test_something(mock_prometheus):
            mock_prometheus.get(
                f"http://{TEST_CONTROL_PLANE_NODE}:80/api/v1/query_range"
            ).respond(200, json={...})
    """
    with respx.mock(assert_all_called=False) as router:
        yield router
