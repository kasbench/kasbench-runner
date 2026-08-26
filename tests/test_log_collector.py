"""Property-based tests for LogCollector service.

Uses hypothesis to validate correctness properties defined in the design document.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given
from hypothesis import strategies as st

from kasbench_runner.services.log_collector import LogCollector, LogCollectionResult
from kasbench_runner.services.s3_client import S3Client, S3OperationError


# Strategy for identifiers: alphanumeric + hyphens, non-empty
identifier_strategy = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789-"),
    min_size=1,
    max_size=30,
)


class TestS3KeyPathConstruction:
    """Property 5: S3 key path construction.

    **Validates: Requirements 6.1**

    For any combination of run_identifier, trial_identifier, namespace,
    and filename, the S3 upload key SHALL be
    `{run_identifier}/{trial_identifier}/logs/{namespace}/{filename}`.
    """

    @given(
        run_id=identifier_strategy,
        trial_id=identifier_strategy,
        namespace=identifier_strategy,
        pod_name=identifier_strategy,
    )
    async def test_s3_key_matches_expected_format(
        self, run_id: str, trial_id: str, namespace: str, pod_name: str
    ):
        """The S3 key passed to upload_bytes follows the prescribed path structure."""
        # Arrange: mock S3Client to capture the key argument
        mock_s3_client = AsyncMock(spec=S3Client)
        mock_s3_client.upload_bytes = AsyncMock()

        collector = LogCollector(s3_client=mock_s3_client)

        # Create a mock pod with a single container that returns logs
        mock_pod = MagicMock()
        mock_pod.name = pod_name
        mock_pod.raw = {"spec": {"containers": [{"name": "main"}]}}
        mock_pod.logs = AsyncMock(return_value="some log content")

        # Mock kr8s to return our pod
        with patch("kasbench_runner.services.log_collector.kr8s") as mock_kr8s:
            mock_api = AsyncMock()
            mock_kr8s.asyncio.api = AsyncMock(return_value=mock_api)

            # Make api.get return an async iterable with our mock pod
            async def mock_get(*args, **kwargs):
                yield mock_pod

            mock_api.get = MagicMock(return_value=mock_get())

            result = await collector.collect_and_upload(
                namespace=namespace,
                run_identifier=run_id,
                trial_identifier=trial_id,
            )

        # Assert: verify the S3 key format
        expected_filename = f"{pod_name}.log"  # single container → pod_name.log
        expected_key = f"{run_id}/{trial_id}/logs/{namespace}/{expected_filename}"

        mock_s3_client.upload_bytes.assert_called_once_with(
            key=expected_key,
            data=b"some log content",
            content_type="text/plain",
        )

    @given(
        run_id=identifier_strategy,
        trial_id=identifier_strategy,
        namespace=identifier_strategy,
    )
    async def test_s3_prefix_matches_expected_format(
        self, run_id: str, trial_id: str, namespace: str
    ):
        """LogCollectionResult.s3_prefix follows the prescribed path structure."""
        # Arrange: mock S3Client (no uploads needed for this check)
        mock_s3_client = AsyncMock(spec=S3Client)

        collector = LogCollector(s3_client=mock_s3_client)

        # Mock kr8s to return an empty pod list
        with patch("kasbench_runner.services.log_collector.kr8s") as mock_kr8s:
            mock_api = AsyncMock()
            mock_kr8s.asyncio.api = AsyncMock(return_value=mock_api)

            async def mock_get(*args, **kwargs):
                return
                yield  # make this an async generator

            mock_api.get = MagicMock(return_value=mock_get())

            result = await collector.collect_and_upload(
                namespace=namespace,
                run_identifier=run_id,
                trial_identifier=trial_id,
            )

        # Assert: s3_prefix matches expected format
        expected_prefix = f"{run_id}/{trial_id}/logs/{namespace}/"
        assert result.s3_prefix == expected_prefix

    @given(
        run_id=identifier_strategy,
        trial_id=identifier_strategy,
        namespace=identifier_strategy,
        pod_name=identifier_strategy,
        container1=identifier_strategy,
        container2=identifier_strategy,
    )
    async def test_s3_key_multi_container_pod(
        self,
        run_id: str,
        trial_id: str,
        namespace: str,
        pod_name: str,
        container1: str,
        container2: str,
    ):
        """S3 key for multi-container pods uses {pod_name}-{container_name}.log."""
        # Arrange: mock S3Client to capture keys
        mock_s3_client = AsyncMock(spec=S3Client)
        mock_s3_client.upload_bytes = AsyncMock()

        collector = LogCollector(s3_client=mock_s3_client)

        # Create a mock pod with two containers
        mock_pod = MagicMock()
        mock_pod.name = pod_name
        mock_pod.raw = {
            "spec": {
                "containers": [
                    {"name": container1},
                    {"name": container2},
                ]
            }
        }
        mock_pod.logs = AsyncMock(return_value="log output")

        # Mock kr8s to return our pod
        with patch("kasbench_runner.services.log_collector.kr8s") as mock_kr8s:
            mock_api = AsyncMock()
            mock_kr8s.asyncio.api = AsyncMock(return_value=mock_api)

            async def mock_get(*args, **kwargs):
                yield mock_pod

            mock_api.get = MagicMock(return_value=mock_get())

            result = await collector.collect_and_upload(
                namespace=namespace,
                run_identifier=run_id,
                trial_identifier=trial_id,
            )

        # Assert: both containers uploaded with correct key format
        expected_key1 = f"{run_id}/{trial_id}/logs/{namespace}/{pod_name}-{container1}.log"
        expected_key2 = f"{run_id}/{trial_id}/logs/{namespace}/{pod_name}-{container2}.log"

        call_keys = [
            call.kwargs["key"] for call in mock_s3_client.upload_bytes.call_args_list
        ]
        assert expected_key1 in call_keys
        assert expected_key2 in call_keys
        assert len(call_keys) == 2


# ---------------------------------------------------------------------------
# Unit tests for LogCollector (Task 1.4)
# Requirements: 5.1, 5.2, 8.1, 8.2, 8.3
# ---------------------------------------------------------------------------


class TestDetermineFilename:
    """Unit tests for _determine_filename with single and multi-container pods."""

    def _make_collector(self) -> LogCollector:
        s3_client = object.__new__(S3Client)
        return LogCollector(s3_client=s3_client)

    def test_single_container_returns_pod_name_dot_log(self):
        """Single container pod: filename is {pod_name}.log."""
        collector = self._make_collector()
        result = collector._determine_filename("web-server-abc123", "main", container_count=1)
        assert result == "web-server-abc123.log"

    def test_multi_container_returns_pod_dash_container_dot_log(self):
        """Multi-container pod: filename is {pod_name}-{container_name}.log."""
        collector = self._make_collector()
        result = collector._determine_filename("api-def456", "sidecar", container_count=2)
        assert result == "api-def456-sidecar.log"

    def test_multi_container_three_containers(self):
        """With 3 containers, each gets {pod_name}-{container_name}.log."""
        collector = self._make_collector()
        result = collector._determine_filename("worker-xyz", "init-container", container_count=3)
        assert result == "worker-xyz-init-container.log"


class TestCollectAndUploadEmptyNamespace:
    """Test collect_and_upload with 0 pods in namespace."""

    @pytest.mark.asyncio
    async def test_empty_namespace_returns_zero_files(self):
        """When namespace has no pods, returns files_exported=0, empty errors."""
        mock_s3_client = AsyncMock(spec=S3Client)
        collector = LogCollector(s3_client=mock_s3_client)

        with patch("kasbench_runner.services.log_collector.kr8s") as mock_kr8s:
            mock_api = AsyncMock()
            mock_kr8s.asyncio.api = AsyncMock(return_value=mock_api)

            async def mock_get(*args, **kwargs):
                return
                yield  # async generator that yields nothing

            mock_api.get = MagicMock(return_value=mock_get())

            result = await collector.collect_and_upload(
                namespace="empty-ns",
                run_identifier="run001",
                trial_identifier="trial001",
            )

        assert result.files_exported == 0
        assert result.errors == []
        assert result.s3_prefix == "run001/trial001/logs/empty-ns/"
        mock_s3_client.upload_bytes.assert_not_called()


class TestBestEffortCollectionErrors:
    """Best-effort: one container log failure doesn't block others.

    Requirements: 8.1, 8.2, 8.3
    """

    @pytest.mark.asyncio
    async def test_one_pod_fails_logs_other_succeeds(self):
        """When one pod's logs are unavailable, the other pod still gets uploaded."""
        mock_s3_client = AsyncMock(spec=S3Client)
        mock_s3_client.upload_bytes = AsyncMock()

        collector = LogCollector(s3_client=mock_s3_client)

        # Pod 1: logs succeed
        pod_ok = MagicMock()
        pod_ok.name = "healthy-pod"
        pod_ok.raw = {"spec": {"containers": [{"name": "main"}]}}
        pod_ok.logs = AsyncMock(return_value="healthy pod logs")

        # Pod 2: logs fail (returns None → recorded as error)
        pod_fail = MagicMock()
        pod_fail.name = "failing-pod"
        pod_fail.raw = {"spec": {"containers": [{"name": "app"}]}}
        pod_fail.logs = AsyncMock(return_value=None)

        with patch("kasbench_runner.services.log_collector.kr8s") as mock_kr8s:
            mock_api = AsyncMock()
            mock_kr8s.asyncio.api = AsyncMock(return_value=mock_api)

            async def mock_get(*args, **kwargs):
                yield pod_ok
                yield pod_fail

            mock_api.get = MagicMock(return_value=mock_get())

            result = await collector.collect_and_upload(
                namespace="test-ns",
                run_identifier="run001",
                trial_identifier="trial001",
            )

        # The healthy pod's log was uploaded
        assert result.files_exported == 1
        mock_s3_client.upload_bytes.assert_called_once_with(
            key="run001/trial001/logs/test-ns/healthy-pod.log",
            data=b"healthy pod logs",
            content_type="text/plain",
        )

        # The failing pod's error was recorded
        assert len(result.errors) == 1
        assert result.errors[0]["pod"] == "failing-pod"
        assert result.errors[0]["container"] == "app"
        assert result.errors[0]["phase"] == "collection"

    @pytest.mark.asyncio
    async def test_exception_in_logs_treated_as_unavailable(self):
        """When pod.logs() raises an exception, it's treated as unavailable (not fatal)."""
        mock_s3_client = AsyncMock(spec=S3Client)
        mock_s3_client.upload_bytes = AsyncMock()

        collector = LogCollector(s3_client=mock_s3_client)

        # Pod that raises exception on logs
        pod_exception = MagicMock()
        pod_exception.name = "crashing-pod"
        pod_exception.raw = {"spec": {"containers": [{"name": "main"}]}}
        pod_exception.logs = AsyncMock(side_effect=RuntimeError("container not ready"))

        # Pod that works fine
        pod_ok = MagicMock()
        pod_ok.name = "working-pod"
        pod_ok.raw = {"spec": {"containers": [{"name": "app"}]}}
        pod_ok.logs = AsyncMock(return_value="working logs")

        with patch("kasbench_runner.services.log_collector.kr8s") as mock_kr8s:
            mock_api = AsyncMock()
            mock_kr8s.asyncio.api = AsyncMock(return_value=mock_api)

            async def mock_get(*args, **kwargs):
                yield pod_exception
                yield pod_ok

            mock_api.get = MagicMock(return_value=mock_get())

            result = await collector.collect_and_upload(
                namespace="test-ns",
                run_identifier="run002",
                trial_identifier="trial003",
            )

        # Working pod uploaded successfully
        assert result.files_exported == 1
        # Exception pod recorded as collection error
        assert len(result.errors) == 1
        assert result.errors[0]["pod"] == "crashing-pod"
        assert result.errors[0]["phase"] == "collection"


class TestBestEffortUploadErrors:
    """S3 upload failure is recorded but doesn't abort remaining uploads.

    Requirements: 8.1, 8.2
    """

    @pytest.mark.asyncio
    async def test_s3_upload_failure_recorded_others_succeed(self):
        """When one S3 upload fails, remaining uploads still proceed."""
        mock_s3_client = AsyncMock(spec=S3Client)

        # First upload raises S3OperationError, second succeeds
        mock_s3_client.upload_bytes = AsyncMock(
            side_effect=[
                S3OperationError(
                    bucket="test-bucket",
                    key="run001/trial001/logs/ns/pod-a.log",
                    exception_class="ClientError",
                    exception_message="Access Denied",
                ),
                None,  # second upload succeeds
            ]
        )

        collector = LogCollector(s3_client=mock_s3_client)

        # Two pods, both with available logs
        pod_a = MagicMock()
        pod_a.name = "pod-a"
        pod_a.raw = {"spec": {"containers": [{"name": "main"}]}}
        pod_a.logs = AsyncMock(return_value="logs from pod a")

        pod_b = MagicMock()
        pod_b.name = "pod-b"
        pod_b.raw = {"spec": {"containers": [{"name": "main"}]}}
        pod_b.logs = AsyncMock(return_value="logs from pod b")

        with patch("kasbench_runner.services.log_collector.kr8s") as mock_kr8s:
            mock_api = AsyncMock()
            mock_kr8s.asyncio.api = AsyncMock(return_value=mock_api)

            async def mock_get(*args, **kwargs):
                yield pod_a
                yield pod_b

            mock_api.get = MagicMock(return_value=mock_get())

            result = await collector.collect_and_upload(
                namespace="ns",
                run_identifier="run001",
                trial_identifier="trial001",
            )

        # One upload succeeded, one failed
        assert result.files_exported == 1

        # The upload failure was recorded
        assert len(result.errors) == 1
        assert result.errors[0]["pod"] == "pod-a"
        assert result.errors[0]["container"] == "main"
        assert result.errors[0]["phase"] == "upload"
        assert "Access Denied" in result.errors[0]["error"]

        # Both uploads were attempted (upload_bytes called twice)
        assert mock_s3_client.upload_bytes.call_count == 2
