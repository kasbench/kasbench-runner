"""Reusable health check retry logic for the KASBench Benchmark Runner.

Implements a configurable health check function that polls a URL with
retry logic, matching expected HTTP status and JSON field-value pairs.

Requirements: 14.1, 14.2, 14.3, 14.4, 14.5
"""

import asyncio
from dataclasses import dataclass

import httpx
import structlog

logger = structlog.get_logger()


@dataclass
class HealthCheckResult:
    """Result of a health check operation.

    Attributes:
        success: Whether the health check matched all expected conditions.
        last_status: The HTTP status code from the last attempt, or None if connection failed.
        last_body: The response body from the last attempt (parsed JSON dict or raw string),
            or None if connection failed.
        attempts: Total number of attempts made.
        error: Description of the failure reason, or None on success.
    """

    success: bool
    last_status: int | None
    last_body: dict | str | None
    attempts: int
    error: str | None


async def check_health(
    url: str,
    max_attempts: int,
    interval_seconds: float,
    timeout_seconds: float,
    expected_status: int,
    expected_fields: dict[str, str],
) -> HealthCheckResult:
    """Perform a health check with configurable retry logic.

    Sends HTTP GET requests to the target URL, checking that the response
    matches the expected status code and contains the expected JSON field-value
    pairs. Retries up to max_attempts with interval_seconds between failed attempts.

    Args:
        url: The target URL to check.
        max_attempts: Maximum number of attempts (first call = attempt 1).
        interval_seconds: Seconds to wait between non-matching attempts.
        timeout_seconds: Per-attempt connection/read timeout in seconds.
        expected_status: The HTTP status code that indicates a healthy response.
        expected_fields: JSON field-value pairs that must all be present and match
            in the response body for the check to succeed.

    Returns:
        HealthCheckResult with success/failure details, last status, last body,
        and attempt count.
    """
    last_status: int | None = None
    last_body: dict | str | None = None
    error: str | None = None

    for attempt in range(1, max_attempts + 1):
        match = False
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(timeout_seconds)
            ) as client:
                response = await client.get(url)

            last_status = response.status_code

            # Try to parse body as JSON
            try:
                last_body = response.json()
            except (ValueError, TypeError):
                last_body = response.text

            # Check if response matches expected conditions
            if last_status == expected_status:
                if isinstance(last_body, dict):
                    match = all(
                        last_body.get(key) == value
                        for key, value in expected_fields.items()
                    )
                else:
                    # If no expected_fields, status match is sufficient
                    match = len(expected_fields) == 0

            if match:
                await logger.ainfo(
                    "health_check_attempt",
                    attempt=f"{attempt}/{max_attempts}",
                    url=url,
                    status_code=last_status,
                    match=True,
                )
                return HealthCheckResult(
                    success=True,
                    last_status=last_status,
                    last_body=last_body,
                    attempts=attempt,
                    error=None,
                )

            # Log non-matching attempt
            error = (
                f"Response did not match expected conditions: "
                f"status={last_status} (expected {expected_status})"
            )
            if isinstance(last_body, dict):
                mismatches = {
                    key: f"got {last_body.get(key)!r}, expected {value!r}"
                    for key, value in expected_fields.items()
                    if last_body.get(key) != value
                }
                if mismatches:
                    error += f", field mismatches: {mismatches}"

        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError) as exc:
            last_status = None
            last_body = None
            error = f"Connection error: {type(exc).__name__}: {exc}"

        await logger.ainfo(
            "health_check_attempt",
            attempt=f"{attempt}/{max_attempts}",
            url=url,
            status_code=last_status,
            match=False,
        )

        # Wait before next attempt (but not after the last attempt)
        if attempt < max_attempts:
            await asyncio.sleep(interval_seconds)

    return HealthCheckResult(
        success=False,
        last_status=last_status,
        last_body=last_body,
        attempts=max_attempts,
        error=error,
    )
