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


class HelmInstallError(RunnerError):
    """Helm chart installation failure."""

    def __init__(self, command: str, stderr: str):
        super().__init__(
            error="helm_install_failed",
            message=f"Helm operation failed: {command}",
            command=command,
            stderr=stderr,
        )


class RolloutTimeoutError(RunnerError):
    """Deployment rollout timed out."""

    def __init__(self, deployment_name: str, namespace: str, elapsed_seconds: float):
        super().__init__(
            error="rollout_timeout",
            message=f"Rollout timed out for {namespace}/{deployment_name} after {elapsed_seconds:.1f}s",
            deployment_name=deployment_name,
            namespace=namespace,
            elapsed_seconds=elapsed_seconds,
        )


class RolloutUnrecoverableError(RunnerError):
    """Deployment encountered an unrecoverable condition."""

    def __init__(self, deployment_name: str, namespace: str, reason: str, **kwargs):
        super().__init__(
            error="rollout_unrecoverable",
            message=f"Unrecoverable condition for {namespace}/{deployment_name}: {reason}",
            deployment_name=deployment_name,
            namespace=namespace,
            reason=reason,
            **kwargs,
        )


class DeploymentNotFoundError(RunnerError):
    """Deployment does not exist in the specified namespace."""

    def __init__(self, deployment_name: str, namespace: str):
        super().__init__(
            error="deployment_not_found",
            message=f"Deployment '{deployment_name}' not found in namespace '{namespace}'",
            deployment_name=deployment_name,
            namespace=namespace,
        )


class KubernetesApiError(RunnerError):
    """Kubernetes API unreachable or returned unexpected error."""

    def __init__(self, message: str, **kwargs):
        super().__init__(
            error="kubernetes_api_error",
            message=message,
            **kwargs,
        )


class SnapshotCollectionError(RunnerError):
    """Required Kubernetes resource collection failed."""

    def __init__(self, resource: str, exception_class: str, exception_message: str):
        super().__init__(
            error="kubernetes_error",
            message=f"Failed to collect {resource}: {exception_class}: {exception_message}",
            resource=resource,
            exception_class=exception_class,
            exception_message=exception_message,
        )


class InvalidPhaseError(RunnerError):
    """Invalid snapshot phase value."""

    def __init__(self, phase: str):
        super().__init__(
            error="invalid_phase",
            message=f"Invalid phase '{phase}'. Allowed values: 'pre', 'post'",
            phase=phase,
            allowed_values=["pre", "post"],
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
