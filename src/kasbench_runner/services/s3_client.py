"""S3 client service for trial reservation and artifact operations."""

import asyncio

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
