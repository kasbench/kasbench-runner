"""SSH client service for remote command execution via asyncssh.

Provides async SSH connection management, command execution with stdout/stderr
capture, and SCP file transfers.

Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6
"""

import os
from dataclasses import dataclass
from pathlib import Path

import asyncssh
import structlog

from kasbench_runner.errors import SSHError

logger = structlog.get_logger()


@dataclass
class SSHResult:
    """Result of an SSH command execution."""

    stdout: str
    stderr: str
    exit_code: int


class SSHClient:
    """Async SSH client for remote command execution and file transfer.

    Uses asyncssh to connect to remote hosts as a configurable user
    (default: ubuntu) with a configurable connection timeout (default: 30s).
    """

    def __init__(self, username: str = "ubuntu", connect_timeout: int = 30) -> None:
        """Initialize SSH client configuration.

        Args:
            username: SSH username for connections. Defaults to "ubuntu".
            connect_timeout: Connection timeout in seconds. Defaults to 30.
        """
        self._username = username
        self._connect_timeout = connect_timeout
        self._connection: asyncssh.SSHClientConnection | None = None
        self._hostname: str | None = None

    async def connect(self, hostname: str) -> None:
        """Establish an SSH connection to the specified hostname.

        Args:
            hostname: The remote host to connect to.

        Raises:
            SSHError: If the connection cannot be established within the timeout.
        """
        try:
            self._connection = await asyncssh.connect(
                hostname,
                username=self._username,
                connect_timeout=self._connect_timeout,
                known_hosts=None,
            )
            self._hostname = hostname
            logger.info(
                "ssh_connected",
                hostname=hostname,
                username=self._username,
            )
        except (OSError, asyncssh.Error) as exc:
            raise SSHError(
                hostname=hostname,
                command="connect",
                exit_code=-1,
                stderr=str(exc),
            ) from exc

    async def execute(self, command: str) -> SSHResult:
        """Execute a command on the connected remote host.

        Args:
            command: The shell command to execute remotely.

        Returns:
            SSHResult with captured stdout, stderr, and exit code.

        Raises:
            SSHError: If the command returns a non-zero exit code or
                      the connection is not established.
        """
        if self._connection is None or self._hostname is None:
            raise SSHError(
                hostname="unknown",
                command=command,
                exit_code=-1,
                stderr="Not connected. Call connect() first.",
            )

        result = await self._connection.run(command, check=False)

        exit_code = result.exit_status if result.exit_status is not None else -1
        stdout = result.stdout or ""
        stderr = result.stderr or ""

        if exit_code == 0:
            logger.info(
                "ssh_command_executed",
                hostname=self._hostname,
                command=command,
                exit_code=exit_code,
                outcome="success",
            )
        else:
            logger.info(
                "ssh_command_executed",
                hostname=self._hostname,
                command=command,
                exit_code=exit_code,
                outcome="failure",
                stderr_summary=stderr[:200],
            )
            raise SSHError(
                hostname=self._hostname,
                command=command,
                exit_code=exit_code,
                stderr=stderr,
            )

        return SSHResult(stdout=stdout, stderr=stderr, exit_code=exit_code)

    async def copy_from_remote(self, remote_path: str, local_path: str) -> None:
        """Copy a file from the remote host to the local filesystem via SCP.

        Creates the local destination directory if it does not exist.

        Args:
            remote_path: Path to the file on the remote host.
            local_path: Destination path on the local filesystem.

        Raises:
            SSHError: If the connection is not established or the copy fails.
        """
        if self._connection is None or self._hostname is None:
            raise SSHError(
                hostname="unknown",
                command=f"scp {remote_path} -> {local_path}",
                exit_code=-1,
                stderr="Not connected. Call connect() first.",
            )

        # Create local destination directory if it doesn't exist
        local_dir = os.path.dirname(local_path)
        if local_dir:
            Path(local_dir).mkdir(parents=True, exist_ok=True)

        try:
            await asyncssh.scp(
                (self._connection, remote_path),
                local_path,
            )
            logger.info(
                "ssh_scp_completed",
                hostname=self._hostname,
                remote_path=remote_path,
                local_path=local_path,
                outcome="success",
            )
        except (OSError, asyncssh.Error) as exc:
            raise SSHError(
                hostname=self._hostname,
                command=f"scp {remote_path} -> {local_path}",
                exit_code=-1,
                stderr=str(exc),
            ) from exc

    async def close(self) -> None:
        """Close the SSH connection."""
        if self._connection is not None:
            self._connection.close()
            logger.info(
                "ssh_disconnected",
                hostname=self._hostname,
            )
            self._connection = None
            self._hostname = None
