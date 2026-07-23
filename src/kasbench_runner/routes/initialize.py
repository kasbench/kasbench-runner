"""POST /initialize endpoint for the KASBench Benchmark Runner.

Orchestrates the full initialization flow: request validation, S3 trial
reservation, Kubernetes cluster installation, manifest deployment, and
load generator deployment.

Requirements: 1.2, 1.7, 2.1–2.5, 3.1–3.3, 4.1–4.14, 5.1–5.13, 6.1–6.12
"""

from __future__ import annotations

import asyncio

import httpx
import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from kasbench_runner.config import (
    MANIFEST_REPOS,
    ROLE_PORTS,
    VALID_ROLES,
    RunnerConfig,
)
from kasbench_runner.errors import HelmInstallError, ManifestError, build_error_response
from kasbench_runner.models.requests import InitializeRequest
from kasbench_runner.models.state import BenchmarkState, BenchmarkStatus
from kasbench_runner.services.docker_manager import DockerManager
from kasbench_runner.services.health_checker import check_health
from kasbench_runner.services.kubernetes_manager import KubernetesManager
from kasbench_runner.services.manifest_parser import ManifestOperation, parse_manifest_list
from kasbench_runner.services.s3_client import (
    S3Client,
    S3OperationError,
    S3ReservationConflictError,
)
from kasbench_runner.services.ssh_client import SSHClient

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.post("/initialize")
async def initialize(body: InitializeRequest, request: Request) -> JSONResponse:
    """Initialize the benchmark environment.

    Orchestrates: state check → S3 reservation → Kubernetes install →
    manifest install → load generator deployment → state transition.
    """
    state: BenchmarkState = request.app.state.benchmark_state
    config: RunnerConfig = request.app.state.config

    # Step 1: Check state is not_initialized (Req 1.7)
    if state.status != BenchmarkStatus.NOT_INITIALIZED:
        return build_error_response(
            error="already_initialized",
            message="Runner has already been initialized",
            status_code=409,
            current_status=state.status.value,
        )

    # Step 2: Reserve S3 trial (Req 3.1, 3.2, 3.3)
    s3_client = S3Client(bucket=body.s3_bucket)
    try:
        await s3_client.reserve_trial(
            run_identifier=body.run_identifier,
            trial_identifier=body.trial_identifier,
        )
    except S3ReservationConflictError as exc:
        return build_error_response(
            error=exc.error,
            message=exc.message,
            status_code=409,
            **exc.context,
        )
    except S3OperationError as exc:
        return build_error_response(
            error=exc.error,
            message=exc.message,
            status_code=500,
            **exc.context,
        )

    # Step 3: Kubernetes install (Req 4.1–4.14)
    if body.skip_kubernetes_install:
        logger.info("kubernetes_install_skipped")
        state.kubernetes_installed = True
    else:
        ssh_client = SSHClient(
            username=config.ssh_user,
            connect_timeout=config.ssh_connect_timeout,
        )
        k8s_manager = KubernetesManager(
            ssh_client=ssh_client,
            readiness_timeout_seconds=config.node_readiness_timeout_seconds,
            poll_interval_seconds=config.node_readiness_poll_interval,
        )
        try:
            await k8s_manager.install_cluster(
                control_plane=body.control_plane_node,
                amd_workers=body.amd_worker_nodes,
                arm_workers=body.arm_worker_nodes,
                k8s_version=body.kubernetes_version,
                cidr=body.cluster_cidr_range,
            )
            state.kubernetes_installed = True
        except Exception as exc:
            from kasbench_runner.errors import RunnerError

            if isinstance(exc, RunnerError):
                return build_error_response(
                    error=exc.error,
                    message=exc.message,
                    status_code=500,
                    **exc.context,
                )
            return build_error_response(
                error="kubernetes_install_failed",
                message=str(exc),
                status_code=500,
                exception_class=type(exc).__name__,
            )

    # Step 4: GlobeCo Helm install (Req 6)
    if body.skip_manifest_install:
        logger.info("helm_install_skipped")
        state.globeco_installed = True
    else:
        try:
            await _install_helm_chart(config, body.autoscaler, body.execution_data_fs)
            state.globeco_installed = True
        except HelmInstallError as exc:
            return build_error_response(
                error=exc.error,
                message=exc.message,
                status_code=500,
                **exc.context,
            )
        except Exception as exc:
            from kasbench_runner.errors import RunnerError

            if isinstance(exc, RunnerError):
                return build_error_response(
                    error=exc.error,
                    message=exc.message,
                    status_code=500,
                    **exc.context,
                )
            return build_error_response(
                error="helm_install_failed",
                message=str(exc),
                status_code=500,
                exception_class=type(exc).__name__,
            )

    # Step 5: Load generator deployment (Req 6.1–6.12)
    try:
        await _deploy_load_generators(body, config)
        state.load_generators_installed = True
    except Exception as exc:
        from kasbench_runner.errors import RunnerError

        if isinstance(exc, RunnerError):
            return build_error_response(
                error=exc.error,
                message=exc.message,
                status_code=500,
                **exc.context,
            )
        return build_error_response(
            error="load_generator_deployment_failed",
            message=str(exc),
            status_code=500,
            exception_class=type(exc).__name__,
        )

    # Step 6: Set state flags and transition to not-started (Req 1.2)
    state.config = body
    state.status = BenchmarkStatus.NOT_STARTED

    logger.info(
        "initialization_complete",
        kubernetes_installed=state.kubernetes_installed,
        globeco_installed=state.globeco_installed,
        load_generators_installed=state.load_generators_installed,
    )

    return JSONResponse(
        status_code=200,
        content={
            "message": "Initialization complete",
            "status": "not-started",
        },
    )


async def _install_helm_chart(config: RunnerConfig, autoscaler: str, execution_data_fs: str = "none") -> None:
    """Deploy GlobeCo via Helm chart install.

    Executes three commands sequentially:
    1. helm repo add {repo_name} {repo_url}
    2. helm repo update
    3. helm install {release} {repo_name}/{chart} --namespace {ns} --create-namespace --wait --timeout {t}s --set autoscaler={autoscaler} --set executionDataFs={execution_data_fs}

    Args:
        config: Runner configuration with Helm settings.
        autoscaler: The autoscaler type to pass to the Helm chart.
        execution_data_fs: The execution data filesystem type. Defaults to "none".

    Raises:
        HelmInstallError: If any Helm command fails.
    """
    commands = [
        ["helm", "repo", "add", config.helm_repo_name, config.helm_repo_url],
        ["helm", "repo", "update"],
        [
            "helm", "install", config.helm_release_name,
            f"{config.helm_repo_name}/{config.helm_chart_name}",
            "--namespace", config.helm_namespace,
            "--create-namespace",
            "--wait",
            "--timeout", f"{config.helm_install_timeout}s",
            "--set", f"autoscaler={autoscaler}",
            "--set", f"executionDataFs={execution_data_fs}",
        ],
    ]

    for cmd in commands:
        cmd_str = " ".join(cmd)
        logger.info("helm_command_start", command=cmd_str)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
        except FileNotFoundError:
            raise HelmInstallError(
                command=cmd_str,
                stderr="Helm CLI binary not found. Ensure helm is installed and on PATH.",
            )

        if proc.returncode != 0:
            error_output = stderr.decode().strip()
            logger.error(
                "helm_command_failed",
                command=cmd_str,
                exit_code=proc.returncode,
                stderr=error_output,
            )
            raise HelmInstallError(command=cmd_str, stderr=error_output)

        logger.info(
            "helm_command_success",
            command=cmd_str,
            stdout=stdout.decode()[:200],
        )


async def _install_manifests(body: InitializeRequest, config: RunnerConfig) -> list[dict[str, str]]:
    """Fetch and execute manifest operations from all configured repos.

    .. deprecated::
        Retained for backward compatibility. Use _install_helm_chart instead.

    Iterates MANIFEST_REPOS, fetches k8s.lst from each, parses operations,
    and executes them in sequence.

    Returns:
        A list of error dicts accumulated during forced execution (empty if no errors).

    Raises:
        ManifestError: If any manifest operation fails and forceManifestInstall is False.
    """
    all_errors: list[dict[str, str]] = []

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(config.manifest_fetch_timeout)
    ) as http_client:
        for repo_info in MANIFEST_REPOS:
            owner = repo_info["owner"]
            repo = repo_info["repo"]
            tag = repo_info["tag"]

            k8s_lst_url = (
                f"https://raw.githubusercontent.com/{owner}/{repo}/{tag}/k8s_aws/k8s.lst"
            )

            logger.info("manifest_fetch_start", repo=repo, url=k8s_lst_url)

            try:
                response = await http_client.get(k8s_lst_url)
            except httpx.HTTPError as exc:
                raise ManifestError(
                    repo=repo,
                    command=f"GET {k8s_lst_url}",
                    stderr=f"HTTP request failed: {type(exc).__name__}: {exc}",
                ) from exc

            if response.status_code != 200:
                raise ManifestError(
                    repo=repo,
                    command=f"GET {k8s_lst_url}",
                    stderr=f"HTTP {response.status_code}: {response.text[:500]}",
                )

            # Parse the k8s.lst content
            operations = parse_manifest_list(response.text)

            logger.info(
                "manifest_parsed",
                repo=repo,
                operation_count=len(operations),
            )

            # Execute operations
            errors = await _execute_manifest_operations(
                operations=operations,
                owner=owner,
                repo=repo,
                tag=tag,
                force=body.force_manifest_install,
            )
            all_errors.extend(errors)

    logger.info("all_manifests_installed", error_count=len(all_errors))
    return all_errors


async def _execute_manifest_operations(
    operations: list[ManifestOperation],
    owner: str,
    repo: str,
    tag: str,
    force: bool,
) -> list[dict[str, str]]:
    """Execute a list of parsed manifest operations.

    .. deprecated::
        Retained for backward compatibility. Use _install_helm_chart instead.

    Args:
        operations: Parsed operations from k8s.lst.
        owner: GitHub repo owner.
        repo: GitHub repo name.
        tag: Git tag/branch.
        force: If True, continue on errors; if False, raise on first error.

    Returns:
        A list of error dicts accumulated during forced execution (empty if no errors).

    Raises:
        ManifestError: If an operation fails and force is False.
    """
    errors: list[dict[str, str]] = []

    for op in operations:
        if op.op_type in ("noop", "comment"):
            continue

        if op.op_type == "command":
            command = str(op.value)
            logger.info("manifest_command_execute", repo=repo, command=command)

            proc = await asyncio.create_subprocess_exec(
                "bash", "-c", command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                error_output = stderr.decode().strip()
                logger.error(
                    "manifest_command_failed",
                    repo=repo,
                    command=command,
                    exit_code=proc.returncode,
                    stderr=error_output,
                )
                if not force:
                    raise ManifestError(
                        repo=repo,
                        command=command,
                        stderr=error_output,
                    )
                errors.append({
                    "repo": repo,
                    "type": "command",
                    "command": command,
                    "error": error_output,
                })
            else:
                logger.info(
                    "manifest_command_success",
                    repo=repo,
                    command=command,
                    stdout=stdout.decode()[:200],
                )

        elif op.op_type == "sleep":
            seconds = int(op.value)  # type: ignore[arg-type]
            logger.info("manifest_sleep", repo=repo, seconds=seconds)
            await asyncio.sleep(seconds)

        elif op.op_type == "manifest":
            filename = str(op.value)
            manifest_url = (
                f"https://raw.githubusercontent.com/{owner}/{repo}/{tag}"
                f"/k8s_aws/{filename}"
            )
            command = f"kubectl apply --validate=false -f {manifest_url}"

            logger.info(
                "manifest_apply",
                repo=repo,
                filename=filename,
                url=manifest_url,
            )

            proc = await asyncio.create_subprocess_exec(
                "bash", "-c", command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                error_output = stderr.decode().strip()
                logger.error(
                    "manifest_apply_failed",
                    repo=repo,
                    filename=filename,
                    exit_code=proc.returncode,
                    stderr=error_output,
                )
                if not force:
                    raise ManifestError(
                        repo=repo,
                        command=command,
                        stderr=error_output,
                    )
                errors.append({
                    "repo": repo,
                    "type": "manifest_apply",
                    "command": command,
                    "filename": filename,
                    "error": error_output,
                })
            else:
                logger.info(
                    "manifest_apply_success",
                    repo=repo,
                    filename=filename,
                )

    return errors


async def _deploy_load_generators(body: InitializeRequest, config: RunnerConfig) -> None:
    """Deploy RabbitMQ and five load generator containers, then health-check each.

    Raises:
        DockerError: If network verification or container start fails.
        RunnerError: If any load generator fails health checks.
    """
    docker = DockerManager()

    # Step 6.1: Verify kasbench Docker network exists
    await docker.verify_network("kasbench")

    # Step 6.3: Start RabbitMQ container
    await docker.run_container(
        name="rabbitmq",
        image=config.rabbitmq_image,
        network="kasbench",
        ports={5672: 5672, 15672: 15672},
    )

    logger.info("rabbitmq_started", image=config.rabbitmq_image)

    # Step 6.4: Start five load generator containers
    for role in VALID_ROLES:
        host_port = ROLE_PORTS[role]
        await docker.run_container(
            name=role,
            image=body.load_generator_image,
            network="kasbench",
            ports={host_port: 8080},
            env={"RABBITMQ_HOST": "rabbitmq"},
        )
        logger.info("load_generator_started", role=role, host_port=host_port)

    # Step 6.7–6.10: Health check each load generator
    for role in VALID_ROLES:
        health_url = f"http://{role}:8080/health"
        result = await check_health(
            url=health_url,
            max_attempts=config.health_check_max_attempts,
            interval_seconds=config.health_check_interval_seconds,
            timeout_seconds=config.http_connect_timeout,
            expected_status=200,
            expected_fields={"Status": "not-started", "Health": "healthy"},
        )

        if not result.success:
            from kasbench_runner.errors import RunnerError

            raise RunnerError(
                error="load_generator_health_check_failed",
                message=(
                    f"Load generator '{role}' failed health check after "
                    f"{result.attempts} attempts"
                ),
                role=role,
                last_status=result.last_status,
                last_body=str(result.last_body)[:1000] if result.last_body else None,
                attempts=result.attempts,
                error_detail=result.error,
            )

        logger.info("load_generator_verified", role=role)

    logger.info("all_load_generators_deployed")
