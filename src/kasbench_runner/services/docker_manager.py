"""Docker CLI operations for managing containers and networks.

Provides async wrappers around Docker CLI commands using
asyncio.create_subprocess_exec. Operations include network verification,
container creation, and container inspection.

Requirements: 15.1, 15.2, 15.3, 15.4, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6
"""

import asyncio
import json
import random

import structlog

from kasbench_runner.errors import DockerError

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Transient error detection
# ---------------------------------------------------------------------------
# Substrings that indicate a transient failure worth retrying. These are
# matched case-insensitively against the Docker CLI stderr output. Most of
# these relate to registry/network hiccups while pulling an image (Docker
# auto-pulls when the image is not present locally).
_TRANSIENT_ERROR_MARKERS: tuple[str, ...] = (
    "502 bad gateway",
    "503 service unavailable",
    "504 gateway timeout",
    "500 internal server error",
    "429 too many requests",
    "toomanyrequests",
    "rate limit",
    "httpreadseeker",
    "failed to copy",
    "timeout",
    "timed out",
    "temporary failure",
    "temporarily unavailable",
    "connection reset",
    "connection refused",
    "eof",
    "i/o timeout",
    "tls handshake",
    "no route to host",
    "no such host",
    "dial tcp",
    "unexpected status from",
    "manifest unknown",
    "manifest unknown: retry",
    "manifest for",
    "not found: manifest",
    "registry",
    # Docker Hub can transiently return these for images that DO exist and
    # are public (registry hiccups / rate limiting). Treat them as retryable
    # so a real, published image is not abandoned on the first flaky pull.
    "pull access denied",
    "repository does not exist",
    "unable to find image",
    "error response from daemon",
    "received unexpected http status",
    "read: connection",
    "context deadline exceeded",
)


def _is_transient_error(error_output: str) -> bool:
    """Return True if the Docker error output looks transient/retryable."""
    lowered = error_output.lower()
    return any(marker in lowered for marker in _TRANSIENT_ERROR_MARKERS)


class DockerManager:
    """Manages Docker operations via CLI subprocess calls.

    All methods use asyncio.create_subprocess_exec to invoke Docker CLI
    commands. Each operation is logged at INFO level and raises DockerError
    on failure.

    Container start operations that fail with a transient error (e.g. a
    registry 502 while pulling the image) are retried with exponential
    backoff.
    """

    def __init__(
        self,
        run_max_attempts: int = 5,
        run_initial_backoff_seconds: float = 2.0,
        run_backoff_multiplier: float = 2.0,
        run_max_backoff_seconds: float = 30.0,
    ) -> None:
        """Initialize the manager with retry settings for run operations.

        Args:
            run_max_attempts: Total number of attempts for a container start
                before giving up (including the first attempt).
            run_initial_backoff_seconds: Delay before the first retry.
            run_backoff_multiplier: Factor applied to the backoff after each
                failed attempt.
            run_max_backoff_seconds: Upper bound on the backoff delay.
        """
        self._run_max_attempts = max(1, run_max_attempts)
        self._run_initial_backoff_seconds = run_initial_backoff_seconds
        self._run_backoff_multiplier = run_backoff_multiplier
        self._run_max_backoff_seconds = run_max_backoff_seconds

    async def verify_network(self, name: str) -> None:
        """Verify that a Docker network exists.

        Runs `docker network inspect <name>` to check if the network exists.
        Does NOT attempt to create the network if it doesn't exist.

        Args:
            name: The Docker network name to verify.

        Raises:
            DockerError: If the network does not exist or the Docker daemon
                is not accessible.
        """
        logger.info("docker.verify_network", network=name)

        try:
            process = await asyncio.create_subprocess_exec(
                "docker", "network", "inspect", name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
        except OSError as exc:
            raise DockerError(
                container_name="",
                image="",
                operation="network_inspect",
                error_output=f"Cannot connect to Docker daemon: {exc}",
            ) from exc

        if process.returncode != 0:
            error_output = stderr.decode().strip()

            if "Cannot connect" in error_output or "permission denied" in error_output.lower():
                raise DockerError(
                    container_name="",
                    image="",
                    operation="network_inspect",
                    error_output=f"Cannot connect to Docker daemon: {error_output}",
                )

            raise DockerError(
                container_name="",
                image="",
                operation="network_inspect",
                error_output=f"Docker network '{name}' does not exist: {error_output}",
            )

        logger.info("docker.network_verified", network=name)

    async def run_container(
        self,
        name: str,
        image: str,
        network: str,
        ports: dict[int, int],
        env: dict[str, str] | None = None,
    ) -> None:
        """Start a Docker container in detached mode.

        Runs `docker run -d --name <name> --network <network>` with the
        specified port mappings and environment variables.

        If the container already exists (name already in use), a warning
        is logged and the method returns without raising.

        Args:
            name: Container name.
            image: Docker image to run.
            network: Docker network to attach the container to.
            ports: Mapping of host_port -> container_port.
            env: Optional mapping of environment variable key -> value.

        Raises:
            DockerError: If the docker run command fails for reasons other
                than the container already existing.
        """
        logger.info(
            "docker.run_container",
            container_name=name,
            image=image,
            network=network,
            ports=ports,
        )

        cmd: list[str] = [
            "docker", "run", "-d",
            "--name", name,
            "--network", network,
        ]

        for host_port, container_port in ports.items():
            cmd.extend(["-p", f"{host_port}:{container_port}"])

        if env:
            for key, value in env.items():
                cmd.extend(["-e", f"{key}={value}"])

        cmd.append(image)

        backoff = self._run_initial_backoff_seconds

        for attempt in range(1, self._run_max_attempts + 1):
            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await process.communicate()
            except OSError as exc:
                raise DockerError(
                    container_name=name,
                    image=image,
                    operation="run",
                    error_output=f"Cannot connect to Docker daemon: {exc}",
                ) from exc

            if process.returncode == 0:
                logger.info(
                    "docker.container_started",
                    container_name=name,
                    image=image,
                    attempt=attempt,
                )
                return

            error_output = stderr.decode().strip()

            if "already in use" in error_output:
                logger.warning(
                    "docker.container_already_exists",
                    container_name=name,
                    image=image,
                )
                return

            transient = _is_transient_error(error_output)
            attempts_remaining = self._run_max_attempts - attempt

            # Retry only transient failures that still have attempts left.
            if transient and attempts_remaining > 0:
                # Full jitter: sleep for a random duration up to the current
                # backoff to avoid thundering-herd retries.
                delay = min(backoff, self._run_max_backoff_seconds)
                sleep_for = random.uniform(0, delay)
                logger.warning(
                    "docker.run_container_transient_failure",
                    container_name=name,
                    image=image,
                    attempt=attempt,
                    max_attempts=self._run_max_attempts,
                    retry_in_seconds=round(sleep_for, 2),
                    error_output=error_output,
                )
                await asyncio.sleep(sleep_for)
                backoff = min(
                    backoff * self._run_backoff_multiplier,
                    self._run_max_backoff_seconds,
                )
                continue

            # Non-transient error, or we've exhausted our retries.
            if transient:
                logger.error(
                    "docker.run_container_retries_exhausted",
                    container_name=name,
                    image=image,
                    attempts=self._run_max_attempts,
                    error_output=error_output,
                )
            raise DockerError(
                container_name=name,
                image=image,
                operation="run",
                error_output=error_output,
            )

    async def copy_to_container(
        self,
        container_name: str,
        src_path: str,
        dest_path: str,
    ) -> None:
        """Copy a file or directory from the host into a running container.

        Runs `docker cp <src_path> <container_name>:<dest_path>`.
        Creates parent directories inside the container before copying.

        Args:
            container_name: Name of the target container.
            src_path: Host path to the file or directory to copy.
            dest_path: Destination path inside the container.

        Raises:
            DockerError: If the docker cp command fails.
        """
        logger.info(
            "docker.copy_to_container",
            container_name=container_name,
            src_path=src_path,
            dest_path=dest_path,
        )

        # Ensure parent directory exists inside the container
        import os

        dest_dir = os.path.dirname(dest_path)
        if dest_dir:
            try:
                mkdir_proc = await asyncio.create_subprocess_exec(
                    "docker", "exec", container_name,
                    "mkdir", "-p", dest_dir,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await mkdir_proc.communicate()
            except OSError as exc:
                raise DockerError(
                    container_name=container_name,
                    image="",
                    operation="copy_to_container",
                    error_output=f"Cannot connect to Docker daemon: {exc}",
                ) from exc

        # Copy file into container
        try:
            process = await asyncio.create_subprocess_exec(
                "docker", "cp", src_path,
                f"{container_name}:{dest_path}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
        except OSError as exc:
            raise DockerError(
                container_name=container_name,
                image="",
                operation="copy_to_container",
                error_output=f"Cannot connect to Docker daemon: {exc}",
            ) from exc

        if process.returncode != 0:
            error_output = stderr.decode().strip()
            raise DockerError(
                container_name=container_name,
                image="",
                operation="copy_to_container",
                error_output=error_output,
            )

        logger.info(
            "docker.file_copied",
            container_name=container_name,
            dest_path=dest_path,
        )

    async def inspect_container(self, name: str) -> dict:
        """Inspect a Docker container and return its state.

        Runs `docker inspect <name>` and returns the parsed JSON output.

        Args:
            name: The container name to inspect.

        Returns:
            Parsed JSON output from docker inspect (first element of the array).

        Raises:
            DockerError: If the inspect command fails.
        """
        logger.info("docker.inspect_container", container_name=name)

        try:
            process = await asyncio.create_subprocess_exec(
                "docker", "inspect", name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
        except OSError as exc:
            raise DockerError(
                container_name=name,
                image="",
                operation="inspect",
                error_output=f"Cannot connect to Docker daemon: {exc}",
            ) from exc

        if process.returncode != 0:
            error_output = stderr.decode().strip()
            raise DockerError(
                container_name=name,
                image="",
                operation="inspect",
                error_output=error_output,
            )

        try:
            result = json.loads(stdout.decode())
        except json.JSONDecodeError as exc:
            raise DockerError(
                container_name=name,
                image="",
                operation="inspect",
                error_output=f"Failed to parse docker inspect output: {exc}",
            ) from exc

        # docker inspect returns a list; return the first element
        if isinstance(result, list) and len(result) > 0:
            return result[0]

        return result
