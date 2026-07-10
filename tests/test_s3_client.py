"""Tests for S3Client upload_bytes and upload_directory methods."""

import os
import tempfile

import pytest

from kasbench_runner.services.s3_client import S3Client, S3OperationError

TEST_BUCKET = "test-bucket"


@pytest.fixture
def s3_client(mock_s3) -> S3Client:
    """Create an S3Client backed by the moto mock."""
    client = S3Client(bucket=TEST_BUCKET)
    # Replace the internal boto3 client with the mock one
    client._s3 = mock_s3
    return client


class TestUploadBytes:
    """Tests for S3Client.upload_bytes."""

    @pytest.mark.asyncio
    async def test_upload_bytes_success(self, s3_client: S3Client, mock_s3):
        """upload_bytes stores data with the correct content type."""
        key = "run001/trial001/output/trader-output.txt"
        data = b"some output content"
        content_type = "text/plain"

        await s3_client.upload_bytes(key, data, content_type)

        # Verify the object was created in S3
        response = mock_s3.get_object(Bucket=TEST_BUCKET, Key=key)
        assert response["Body"].read() == data
        assert response["ContentType"] == content_type

    @pytest.mark.asyncio
    async def test_upload_bytes_binary_content(self, s3_client: S3Client, mock_s3):
        """upload_bytes handles binary data correctly."""
        key = "run001/trial001/db/trader.db"
        data = b"\x00\x01\x02\xff\xfe\xfd"
        content_type = "application/octet-stream"

        await s3_client.upload_bytes(key, data, content_type)

        response = mock_s3.get_object(Bucket=TEST_BUCKET, Key=key)
        assert response["Body"].read() == data
        assert response["ContentType"] == content_type

    @pytest.mark.asyncio
    async def test_upload_bytes_empty_data(self, s3_client: S3Client, mock_s3):
        """upload_bytes handles empty byte data."""
        key = "run001/trial001/empty.txt"
        data = b""
        content_type = "text/plain"

        await s3_client.upload_bytes(key, data, content_type)

        response = mock_s3.get_object(Bucket=TEST_BUCKET, Key=key)
        assert response["Body"].read() == data

    @pytest.mark.asyncio
    async def test_upload_bytes_raises_s3_operation_error_on_failure(self, mock_s3):
        """upload_bytes raises S3OperationError when upload fails."""
        # Use a non-existent bucket to trigger failure
        client = S3Client(bucket="nonexistent-bucket")
        client._s3 = mock_s3

        with pytest.raises(S3OperationError):
            await client.upload_bytes("key", b"data", "text/plain")


class TestUploadDirectory:
    """Tests for S3Client.upload_directory."""

    @pytest.mark.asyncio
    async def test_upload_directory_success(self, s3_client: S3Client, mock_s3):
        """upload_directory uploads all files and returns keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            os.makedirs(os.path.join(tmpdir, "subdir"))
            with open(os.path.join(tmpdir, "file1.txt"), "wb") as f:
                f.write(b"content1")
            with open(os.path.join(tmpdir, "subdir", "file2.txt"), "wb") as f:
                f.write(b"content2")

            prefix = "run001/trial001/tsdb-snapshots"
            keys = await s3_client.upload_directory(prefix, tmpdir)

        assert len(keys) == 2
        assert f"{prefix}/file1.txt" in keys
        assert f"{prefix}/subdir/file2.txt" in keys

        # Verify file contents in S3
        resp1 = mock_s3.get_object(Bucket=TEST_BUCKET, Key=f"{prefix}/file1.txt")
        assert resp1["Body"].read() == b"content1"
        resp2 = mock_s3.get_object(Bucket=TEST_BUCKET, Key=f"{prefix}/subdir/file2.txt")
        assert resp2["Body"].read() == b"content2"

    @pytest.mark.asyncio
    async def test_upload_directory_empty_dir(self, s3_client: S3Client):
        """upload_directory returns empty list for empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            keys = await s3_client.upload_directory("prefix", tmpdir)

        assert keys == []

    @pytest.mark.asyncio
    async def test_upload_directory_raises_s3_operation_error_on_failure(self, mock_s3):
        """upload_directory raises S3OperationError when upload fails."""
        client = S3Client(bucket="nonexistent-bucket")
        client._s3 = mock_s3

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "file.txt"), "wb") as f:
                f.write(b"data")

            with pytest.raises(S3OperationError):
                await client.upload_directory("prefix", tmpdir)
