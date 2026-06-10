"""Custom exception classes and error response builder for KASBench Runner."""

from datetime import datetime, timezone

from fastapi.responses import JSONResponse


class RunnerError(Exception):
    """Base exception for all Runner operations."""

    def __init__(self, error: str, message: str, **context):
        self.error = error
        self.message = message
        self.context = context
        super().__init__(message)


class SSHError(RunnerError):
    """SSH command execution failure."""

    def __init__(self, hostname: str, command: str, exit_code: int, stderr: str):
        super().__init__(
            error="ssh_command_failed",
            message=f"Command failed on {hostname} with exit code {exit_code}",
            hostname=hostname,
            command=command,
            exit_code=exit_code,
            stderr=stderr,
        )


class DockerError(RunnerError):
    """Docker operation failure."""

    def __init__(self, container_name: str, image: str, operation: str, error_output: str):
        super().__init__(
            error="docker_operation_failed",
            message=f"Docker {operation} failed for container {container_name}",
            container_name=container_name,
            image=image,
            operation=operation,
            error_output=error_output,
        )


class LoadGeneratorError(RunnerError):
    """HTTP communication failure with a Load Generator."""

    def __init__(self, url: str, method: str, status_code: int | None, response_body: str):
        super().__init__(
            error="load_generator_request_failed",
            message=f"{method} {url} failed",
            url=url,
            method=method,
            status_code=status_code,
            response_body=response_body[:10000],
        )


class ManifestError(RunnerError):
    """Manifest installation failure."""

    def __init__(self, repo: str, command: str, stderr: str):
        super().__init__(
            error="manifest_install_failed",
            message=f"Manifest operation failed in repository {repo}",
            repository=repo,
            command=command,
            stderr=stderr,
        )


def build_error_response(
    error: str,
    message: str,
    status_code: int,
    **context_fields,
) -> JSONResponse:
    """Build a structured error response with full diagnostic context."""
    return JSONResponse(
        status_code=status_code,
        content={
            "error": error,
            "message": message,
            "context": context_fields,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
