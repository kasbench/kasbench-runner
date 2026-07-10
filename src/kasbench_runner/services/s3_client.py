"""S3 client service for trial reservation and artifact operations."""

import asyncio
import os
from pathlib import Path

import boto3
import structlog
from botocore.exceptions import ClientError

from kasbench_runner.errors import RunnerError

logger = structlog.get_logger()


class S3ReservationConflictError(RunnerError):
    """Raised when a trial reservation already exists in S3 (HTTP 409)."""

    def __init__(self, bucket: str, key: str, run_identifier: str, trial_identifier: str):
        super().__init__(
            error="trial_already_reserved",
            message=(
                f"Trial '{trial_identifier}' is already reserved for run '{run_identifier}'"
            ),
            bucket=bucket,
            key=key,
            run_identifier=run_identifier,
            trial_identifier=trial_identifier,
        )


class S3OperationError(RunnerError):
    """Raised when an S3 operation fails unexpectedly (HTTP 500)."""

    def __init__(
        self, bucket: str, key: str, exception_class: str, exception_message: str
    ):
        super().__init__(
            error="s3_operation_failed",
            message=f"S3 operation failed: {exception_class}: {exception_message}",
            bucket=bucket,
            key=key,
            exception_class=exception_class,
            exception_message=exception_message,
        )


class S3Client:
    """Client for S3 operations including trial reservation."""

    def __init__(self, bucket: str) -> None:
        self._bucket = bucket
        self._s3 = boto3.client("s3")

    async def reserve_trial(self, run_identifier: str, trial_identifier: str) -> None:
        """Reserve a trial by writing an empty file with a conditional put.

        Uses IfNoneMatch="*" to ensure the key does not already exist,
        preventing duplicate trial reservations.

        Args:
            run_identifier: The run identifier (e.g. "run001").
            trial_identifier: The trial identifier (e.g. "trial001").

        Raises:
            S3ReservationConflictError: If the trial is already reserved (maps to HTTP 409).
            S3OperationError: If any other S3 error occurs (maps to HTTP 500).
        """
        key = f"{run_identifier}/{trial_identifier}/reserved"

        log = logger.bind(bucket=self._bucket, key=key)
        log.info("s3_reserve_trial_start")

        try:
            await asyncio.to_thread(
                self._s3.put_object,
                Bucket=self._bucket,
                Key=key,
                Body=b"",
                IfNoneMatch="*",
            )
            log.info("s3_reserve_trial_success")
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code == "PreconditionFailed":
                log.warning("s3_reserve_trial_conflict", error_code=error_code)
                raise S3ReservationConflictError(
                    bucket=self._bucket,
                    key=key,
                    run_identifier=run_identifier,
                    trial_identifier=trial_identifier,
                ) from exc
            else:
                log.error(
                    "s3_reserve_trial_error",
                    exception_class=type(exc).__name__,
                    exception_message=str(exc),
                )
                raise S3OperationError(
                    bucket=self._bucket,
                    key=key,
                    exception_class=type(exc).__name__,
                    exception_message=str(exc),
                ) from exc
        except Exception as exc:
            log.error(
                "s3_reserve_trial_error",
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            )
            raise S3OperationError(
                bucket=self._bucket,
                key=key,
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            ) from exc

    async def check_objects_exist(self, keys: list[str]) -> list[str]:
        """Check which S3 keys already exist.

        Uses head_object for each key. Returns only those that exist.

        Args:
            keys: List of S3 object keys to check.

        Returns:
            List of keys that already exist in the bucket.

        Raises:
            S3OperationError: If a head_object call fails for reasons other than 404.
        """
        existing: list[str] = []
        for key in keys:
            try:
                await asyncio.to_thread(
                    self._s3.head_object,
                    Bucket=self._bucket,
                    Key=key,
                )
                existing.append(key)
            except ClientError as exc:
                error_code = exc.response.get("Error", {}).get("Code", "")
                if error_code == "404":
                    continue
                else:
                    raise S3OperationError(
                        bucket=self._bucket,
                        key=key,
                        exception_class=type(exc).__name__,
                        exception_message=str(exc),
                    ) from exc
        return existing

    async def upload_json(self, key: str, data: bytes) -> None:
        """Upload JSON bytes to S3 with ContentType application/json.

        Args:
            key: The S3 object key.
            data: JSON content as bytes.

        Raises:
            S3OperationError: If the upload fails.
        """
        log = logger.bind(bucket=self._bucket, key=key)
        log.info("s3_upload_json_start")

        try:
            await asyncio.to_thread(
                self._s3.put_object,
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType="application/json",
            )
            log.info("s3_upload_json_success")
        except Exception as exc:
            log.error(
                "s3_upload_json_error",
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            )
            raise S3OperationError(
                bucket=self._bucket,
                key=key,
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            ) from exc

    async def upload_bytes(self, key: str, data: bytes, content_type: str) -> None:
        """Upload arbitrary bytes to S3 with the specified content type.

        Args:
            key: The S3 object key.
            data: Content as bytes.
            content_type: The MIME content type for the object.

        Raises:
            S3OperationError: If the upload fails.
        """
        log = logger.bind(bucket=self._bucket, key=key)
        log.info("s3_upload_bytes_start", content_type=content_type)

        try:
            await asyncio.to_thread(
                self._s3.put_object,
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
            log.info("s3_upload_bytes_success")
        except Exception as exc:
            log.error(
                "s3_upload_bytes_error",
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            )
            raise S3OperationError(
                bucket=self._bucket,
                key=key,
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            ) from exc

    async def upload_directory(self, prefix: str, local_dir: str) -> list[str]:
        """Walk a local directory and upload each file to S3 under the given prefix.

        The directory structure is preserved relative to local_dir. For example,
        if local_dir contains `subdir/file.txt` and prefix is `run001/trial001/tsdb`,
        the file is uploaded to `run001/trial001/tsdb/subdir/file.txt`.

        Args:
            prefix: The S3 key prefix (no trailing slash required).
            local_dir: Path to the local directory to upload.

        Returns:
            List of S3 keys that were uploaded.

        Raises:
            S3OperationError: If any upload fails.
        """
        log = logger.bind(bucket=self._bucket, prefix=prefix, local_dir=local_dir)
        log.info("s3_upload_directory_start")

        uploaded_keys: list[str] = []
        local_path = Path(local_dir)

        try:
            for root, _dirs, files in os.walk(local_dir):
                for filename in files:
                    file_path = Path(root) / filename
                    relative_path = file_path.relative_to(local_path)
                    key = f"{prefix}/{relative_path}"

                    file_data = await asyncio.to_thread(file_path.read_bytes)
                    await asyncio.to_thread(
                        self._s3.put_object,
                        Bucket=self._bucket,
                        Key=key,
                        Body=file_data,
                    )
                    uploaded_keys.append(key)

            log.info("s3_upload_directory_success", files_uploaded=len(uploaded_keys))
            return uploaded_keys
        except Exception as exc:
            log.error(
                "s3_upload_directory_error",
                exception_class=type(exc).__name__,
                exception_message=str(exc),
                files_uploaded_before_error=len(uploaded_keys),
            )
            raise S3OperationError(
                bucket=self._bucket,
                key=prefix,
                exception_class=type(exc).__name__,
                exception_message=str(exc),
            ) from exc
