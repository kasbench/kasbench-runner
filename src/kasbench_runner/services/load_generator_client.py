"""HTTP client for communicating with Load Generator containers."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import structlog

from kasbench_runner.errors import LoadGeneratorError

logger = structlog.get_logger(__name__)


class LoadGeneratorClient:
    """Async HTTP client for Load Generator /start, /health, /abort, /download-* endpoints.

    Addresses generators by container name (role) on port 8080 within the
    kasbench Docker bridge network.
    """

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0),
        )

    def _base_url(self, role: str) -> str:
        """Return the base URL for a load generator addressed by role (container name)."""
        return f"http://{role}:8080"

    async def start(self, role: str, payload: dict) -> None:
        """POST /start with JSON body to begin a benchmark run on the given role.

        Raises LoadGeneratorError on non-200 response or connection failure.
        """
        url = f"{self._base_url(role)}/start"
        log = logger.bind(role=role, url=url)
        log.info("sending_start_request", payload_keys=list(payload.keys()))

        try:
            response = await self._client.post(url, json=payload)
        except httpx.HTTPError as exc:
            log.error("start_request_connection_error", error=str(exc))
            raise LoadGeneratorError(
                url=url,
                method="POST",
                status_code=None,
                response_body=str(exc),
            ) from exc

        if response.status_code != 200:
            body = response.text
            log.error(
                "start_request_failed",
                status_code=response.status_code,
                response_body=body[:500],
            )
            raise LoadGeneratorError(
                url=url,
                method="POST",
                status_code=response.status_code,
                response_body=body,
            )

        log.info("start_request_success")

    async def health(self, role: str) -> dict:
        """GET /health and return parsed JSON response.

        Raises LoadGeneratorError on non-200 response or connection failure.
        """
        url = f"{self._base_url(role)}/health"
        log = logger.bind(role=role, url=url)
        log.debug("checking_health")

        try:
            response = await self._client.get(url)
        except httpx.HTTPError as exc:
            log.error("health_request_connection_error", error=str(exc))
            raise LoadGeneratorError(
                url=url,
                method="GET",
                status_code=None,
                response_body=str(exc),
            ) from exc

        if response.status_code != 200:
            body = response.text
            log.error(
                "health_request_failed",
                status_code=response.status_code,
                response_body=body[:500],
            )
            raise LoadGeneratorError(
                url=url,
                method="GET",
                status_code=response.status_code,
                response_body=body,
            )

        return response.json()

    async def abort(self, role: str) -> dict:
        """POST /abort to stop a running benchmark on the given role.

        Returns the response dict. Raises LoadGeneratorError on failure.
        """
        url = f"{self._base_url(role)}/abort"
        log = logger.bind(role=role, url=url)
        log.info("sending_abort_request")

        try:
            response = await self._client.post(url)
        except httpx.HTTPError as exc:
            log.error("abort_request_connection_error", error=str(exc))
            raise LoadGeneratorError(
                url=url,
                method="POST",
                status_code=None,
                response_body=str(exc),
            ) from exc

        if response.status_code != 200:
            body = response.text
            log.error(
                "abort_request_failed",
                status_code=response.status_code,
                response_body=body[:500],
            )
            raise LoadGeneratorError(
                url=url,
                method="POST",
                status_code=response.status_code,
                response_body=body,
            )

        return response.json()

    @asynccontextmanager
    async def stream_output(self, role: str) -> AsyncIterator[AsyncIterator[bytes]]:
        """GET /download-output with streaming response. Yields byte chunks.

        Usage:
            async with client.stream_output(role) as chunks:
                async for chunk in chunks:
                    ...

        Raises LoadGeneratorError on non-200 response or connection failure.
        """
        url = f"{self._base_url(role)}/download-output"
        log = logger.bind(role=role, url=url)
        log.info("streaming_output")

        try:
            async with self._client.stream("GET", url) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    log.error(
                        "stream_output_failed",
                        status_code=response.status_code,
                    )
                    raise LoadGeneratorError(
                        url=url,
                        method="GET",
                        status_code=response.status_code,
                        response_body=body.decode(errors="replace"),
                    )
                yield response.aiter_bytes()
        except httpx.HTTPError as exc:
            log.error("stream_output_connection_error", error=str(exc))
            raise LoadGeneratorError(
                url=url,
                method="GET",
                status_code=None,
                response_body=str(exc),
            ) from exc

    @asynccontextmanager
    async def stream_db(self, role: str) -> AsyncIterator[AsyncIterator[bytes]]:
        """GET /download-db with streaming response. Yields byte chunks.

        Usage:
            async with client.stream_db(role) as chunks:
                async for chunk in chunks:
                    ...

        Raises LoadGeneratorError on non-200 response or connection failure.
        """
        url = f"{self._base_url(role)}/download-db"
        log = logger.bind(role=role, url=url)
        log.info("streaming_db")

        try:
            async with self._client.stream("GET", url) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    log.error(
                        "stream_db_failed",
                        status_code=response.status_code,
                    )
                    raise LoadGeneratorError(
                        url=url,
                        method="GET",
                        status_code=response.status_code,
                        response_body=body.decode(errors="replace"),
                    )
                yield response.aiter_bytes()
        except httpx.HTTPError as exc:
            log.error("stream_db_connection_error", error=str(exc))
            raise LoadGeneratorError(
                url=url,
                method="GET",
                status_code=None,
                response_body=str(exc),
            ) from exc

    async def close(self) -> None:
        """Close the underlying HTTP client and release resources."""
        await self._client.aclose()
        logger.info("load_generator_client_closed")
