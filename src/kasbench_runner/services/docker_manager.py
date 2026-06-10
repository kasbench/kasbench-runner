"""Docker CLI operations for managing containers and networks.

Provides async wrappers around Docker CLI commands using
asyncio.create_subprocess_exec. Operations include network verification,
container creation, and container inspection.

Requirements: 15.1, 15.2, 15.3, 15.4, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6
"""

import asyncio
import json

import structlog

from kasbench_runner.errors import DockerError

logger = structlog.get_logger(__name__)


class DockerManager:
    """Manages Docker operations via CLI subprocess calls.

    All methods use asyncio.create_subprocess_exec to invoke Docker CLI
    commands. Each operation is logged at INFO level and raises DockerError
    on failure.
    """

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

        if process.returncode != 0:
            error_output = stderr.decode().strip()

            if "already in use" in error_output:
                logger.warning(
                    "docker.container_already_exists",
                    container_name=name,
                    image=image,
                )
                return

            raise DockerError(
                container_name=name,
                image=image,
                operation="run",
                error_output=error_output,
            )

        logger.info("docker.container_started", container_name=name, image=image)

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
