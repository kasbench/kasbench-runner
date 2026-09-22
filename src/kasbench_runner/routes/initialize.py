"""POST /initialize endpoint for the KASBench Benchmark Runner.

Orchestrates the full initialization flow: request validation, S3 trial
reservation, Kubernetes cluster installation, manifest deployment, and
load generator deployment.

Requirements: 1.2, 1.7, 2.1–2.5, 3.1–3.3, 4.1–4.14, 5.1–5.13, 6.1–6.12
"""

from __future__ import annotations

import asyncio
import os
import random

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
from kasbench_runner.routes.images import ImagesExportError, export_images
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


# ---------------------------------------------------------------------------
# Transient error detection for Helm operations
# ---------------------------------------------------------------------------
# Helm repo add/update/install reach out to remote chart repositories and
# container registries, so they are subject to the same transient network and
# registry failures as Docker image pulls. Matched case-insensitively against
# the Helm CLI stderr output.
_HELM_TRANSIENT_ERROR_MARKERS: tuple[str, ...] = (
    "502 bad gateway",
    "503 service unavailable",
    "504 gateway timeout",
    "500 internal server error",
    "429 too many requests",
    "toomanyrequests",
    "rate limit",
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
    "context deadline exceeded",
    "received unexpected http status",
    "could not download",
    "failed to fetch",
    "failed to download",
    "read: connection",
    "unexpected eof",
)


def _is_transient_helm_error(error_output: str) -> bool:
    """Return True if the Helm error output looks transient/retryable."""
    lowered = error_output.lower()
    return any(marker in lowered for marker in _HELM_TRANSIENT_ERROR_MARKERS)


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
                autoscaler=body.autoscaler,
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

    # Step 4b: Capture the name, url, and version of every installed Helm chart
    # (from both the Kubernetes install in step 3 and the GlobeCo install in
    # step 4) and upload them to {run_id}/{trial_id}/helm_versions.json.
    #
    # This is best-effort: a failure to capture or upload this metadata must
    # not abort initialization.
    await _capture_helm_versions(body)

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

    # Step 5b: Export pre-benchmark container images to S3 (pre-images.json)
    try:
        await export_images(
            run_identifier=body.run_identifier,
            trial_identifier=body.trial_identifier,
            s3_bucket=body.s3_bucket,
            filename="pre-images.json",
        )
    except ImagesExportError as exc:
        return build_error_response(
            error=exc.error,
            message=exc.message,
            status_code=exc.status_code,
            **exc.context,
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
            "--debug",
            "--timeout", f"{config.helm_install_timeout}s",
            "--set", f"autoscaler={autoscaler}",
            "--set", f"executionDataFs={execution_data_fs}",
        ],
    ]

    for cmd in commands:
        cmd_str = " ".join(cmd)
        await _run_helm_command_with_retry(
            cmd,
            cmd_str,
            max_attempts=config.docker_run_max_attempts,
            initial_backoff_seconds=config.docker_run_initial_backoff_seconds,
            backoff_multiplier=config.docker_run_backoff_multiplier,
            max_backoff_seconds=config.docker_run_max_backoff_seconds,
        )


async def _run_helm_command_with_retry(
    cmd: list[str],
    cmd_str: str,
    *,
    max_attempts: int,
    initial_backoff_seconds: float,
    backoff_multiplier: float,
    max_backoff_seconds: float,
) -> None:
    """Run a single Helm CLI command, retrying transient failures.

    Uses exponential backoff with full jitter. Transient failures (registry
    or network hiccups) are retried up to ``max_attempts`` times; a missing
    Helm binary or any non-transient failure is raised immediately.

    Raises:
        HelmInstallError: If the command fails with a non-transient error or
            all retry attempts are exhausted.
    """
    backoff = initial_backoff_seconds

    for attempt in range(1, max(1, max_attempts) + 1):
        logger.info("helm_command_start", command=cmd_str, attempt=attempt)

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

        if proc.returncode == 0:
            logger.info(
                "helm_command_success",
                command=cmd_str,
                attempt=attempt,
                stdout=stdout.decode()[:200],
            )
            return

        error_output = stderr.decode().strip()
        transient = _is_transient_helm_error(error_output)
        attempts_remaining = max(1, max_attempts) - attempt

        if transient and attempts_remaining > 0:
            delay = min(backoff, max_backoff_seconds)
            sleep_for = random.uniform(0, delay)
            logger.warning(
                "helm_command_transient_failure",
                command=cmd_str,
                attempt=attempt,
                max_attempts=max_attempts,
                retry_in_seconds=round(sleep_for, 2),
                stderr=error_output,
            )
            await asyncio.sleep(sleep_for)
            backoff = min(backoff * backoff_multiplier, max_backoff_seconds)
            continue

        logger.error(
            "helm_command_failed",
            command=cmd_str,
            exit_code=proc.returncode,
            attempt=attempt,
            transient=transient,
            stderr=error_output,
        )
        raise HelmInstallError(command=cmd_str, stderr=error_output)


async def _capture_helm_versions(body: InitializeRequest) -> None:
    """Capture all installed Helm charts and upload their metadata to S3.

    Queries the cluster for every installed Helm release (across all
    namespaces) plus the configured Helm repositories, then builds a JSON
    document describing each chart's name, source repository URL, and version
    and uploads it to ``{run_id}/{trial_id}/helm_versions.json``.

    Chart versions come from ``helm list`` (the ``chart`` field is
    ``"<name>-<version>"``). Repository URLs are resolved by matching each
    release's chart name against the entries returned by ``helm repo list``;
    when the repo cannot be determined the URL is left as ``None``.

    This step is intentionally non-fatal: any failure (missing Helm binary,
    command error, JSON parsing, or S3 upload) is logged in detail and
    swallowed so that initialization can continue.
    """
    import json
    from datetime import datetime, timezone

    s3_key = f"{body.run_identifier}/{body.trial_identifier}/helm_versions.json"
    log = logger.bind(
        run_identifier=body.run_identifier,
        trial_identifier=body.trial_identifier,
        s3_key=s3_key,
    )
    log.info("helm_versions_capture_start")

    try:
        releases = await _run_helm_json(["helm", "list", "--all-namespaces", "-o", "json"])
        repos = await _run_helm_json(["helm", "repo", "list", "-o", "json"])

        # Map repo name -> url and build a chart-name -> url lookup by probing
        # each repo's chart index is unnecessary; instead we match the release
        # chart name against repo names heuristically below.
        repo_url_by_name = {
            str(r.get("name", "")): str(r.get("url", "")) for r in (repos or [])
        }

        charts: list[dict[str, str | None]] = []
        for release in releases or []:
            chart_field = str(release.get("chart", ""))
            # chart field is "<chartName>-<version>"; split on the last hyphen.
            chart_name, _, version = chart_field.rpartition("-")
            if not chart_name:
                chart_name, version = chart_field, ""

            # Resolve the repository URL. Helm's `list` output does not include
            # the source repo, so we match on the configured GlobeCo repo and
            # otherwise fall back to any repo whose name is a prefix of the
            # release name (the common `helm install <name> <repo>/<chart>`
            # convention leaves the repo unrecorded, so this is best-effort).
            url: str | None = repo_url_by_name.get(chart_name)
            if url is None:
                for repo_name, repo_url in repo_url_by_name.items():
                    if chart_name in repo_name or repo_name in chart_name:
                        url = repo_url
                        break

            charts.append(
                {
                    "name": chart_name,
                    "release": str(release.get("name", "")),
                    "namespace": str(release.get("namespace", "")),
                    "url": url,
                    "version": version,
                }
            )

        document = {
            "runIdentifier": body.run_identifier,
            "trialIdentifier": body.trial_identifier,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "repositories": [
                {"name": name, "url": url} for name, url in repo_url_by_name.items()
            ],
            "charts": charts,
        }
        serialized = json.dumps(document, indent=2, sort_keys=False)

        s3_client = S3Client(bucket=body.s3_bucket)
        await s3_client.upload_json(key=s3_key, data=serialized.encode("utf-8"))

        log.info("helm_versions_capture_success", chart_count=len(charts))
    except Exception as exc:
        # Non-fatal: log full detail and continue with initialization.
        log.error(
            "helm_versions_capture_failed",
            error=str(exc),
            exception_class=type(exc).__name__,
        )


async def _run_helm_json(cmd: list[str]) -> list[dict]:
    """Run a Helm command that emits JSON and return the parsed list.

    Args:
        cmd: The Helm CLI argument vector (e.g. ``["helm", "list", "-o", "json"]``).

    Returns:
        The parsed JSON list. An empty list is returned when Helm prints
        nothing (e.g. no releases/repos configured).

    Raises:
        RuntimeError: If the Helm binary is missing or the command exits
            non-zero.
    """
    import json

    cmd_str = " ".join(cmd)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Helm CLI binary not found. Ensure helm is installed and on PATH."
        ) from exc

    if proc.returncode != 0:
        raise RuntimeError(
            f"Command '{cmd_str}' failed with exit code {proc.returncode}: "
            f"{stderr.decode().strip()}"
        )

    output = stdout.decode().strip()
    if not output:
        return []

    parsed = json.loads(output)
    return parsed if isinstance(parsed, list) else []


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
    docker = DockerManager(
        run_max_attempts=config.docker_run_max_attempts,
        run_initial_backoff_seconds=config.docker_run_initial_backoff_seconds,
        run_backoff_multiplier=config.docker_run_backoff_multiplier,
        run_max_backoff_seconds=config.docker_run_max_backoff_seconds,
    )

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

    # Step 6.5: Copy kubeconfig to each load generator container
    local_kube_config = os.path.join(os.environ.get("HOME", "/home/ubuntu"), ".kube", "config")
    for role in VALID_ROLES:
        await docker.copy_to_container(
            container_name=role,
            src_path=local_kube_config,
            dest_path="/root/.kube/config",
        )
        logger.info("kubeconfig_copied_to_container", role=role)

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

    # Step 6.11: Capture the load generator image id and record the image
    # name (with tag) and image id to S3 at
    # {run_id}/{trial_id}/images/load_runner_image.json.
    #
    # This is best-effort: a failure to capture or upload this metadata must
    # not abort initialization. We log the outcome in detail so any failure
    # can be diagnosed and corrected.
    await _capture_load_generator_image(body, docker)


async def _capture_load_generator_image(
    body: InitializeRequest, docker: DockerManager
) -> None:
    """Capture the load generator image id and upload the metadata to S3.

    Inspects the load generator image to resolve its content-addressable image
    id, then stores a JSON document containing the image name (with tag) and
    the resolved image id at
    ``{run_id}/{trial_id}/images/load_runner_image.json``.

    This step is intentionally non-fatal: any failure (image inspect, JSON
    serialization, or S3 upload) is logged in detail and swallowed so that
    initialization can continue.
    """
    import json
    from datetime import datetime, timezone

    image = body.load_generator_image
    s3_key = (
        f"{body.run_identifier}/{body.trial_identifier}/images/load_runner_image.json"
    )
    log = logger.bind(
        image=image,
        run_identifier=body.run_identifier,
        trial_identifier=body.trial_identifier,
        s3_key=s3_key,
    )
    log.info("load_generator_image_capture_start")

    try:
        # Resolve the image id via `docker image inspect`.
        inspected = await docker.inspect_image(image)
        image_id = inspected.get("Id", "")
        repo_tags = inspected.get("RepoTags") or []

        if not image_id:
            log.warning(
                "load_generator_image_id_missing",
                repo_tags=repo_tags,
                inspect_keys=sorted(inspected.keys()),
            )

        document = {
            "runIdentifier": body.run_identifier,
            "trialIdentifier": body.trial_identifier,
            "image": image,
            "imageId": image_id,
            "repoTags": repo_tags,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        serialized = json.dumps(document, indent=2, sort_keys=False)

        s3_client = S3Client(bucket=body.s3_bucket)
        await s3_client.upload_bytes(
            key=s3_key,
            data=serialized.encode("utf-8"),
            content_type="application/json",
        )

        log.info(
            "load_generator_image_capture_success",
            image_id=image_id,
            repo_tags=repo_tags,
        )
    except Exception as exc:
        # Non-fatal: log full detail and continue with initialization.
        log.error(
            "load_generator_image_capture_failed",
            error=str(exc),
            exception_class=type(exc).__name__,
        )
