"""POST /metadata/export endpoint for the KASBench Benchmark Runner.

Constructs a run_details.json document with full benchmark configuration,
role parameters, manifest repositories, and current status, then uploads
it to S3.

Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Request

from kasbench_runner.config import MANIFEST_REPOS, ROLE_PARAMS, RunnerConfig
from kasbench_runner.errors import build_error_response
from kasbench_runner.models.responses import ExportResponse
from kasbench_runner.models.state import BenchmarkState, BenchmarkStatus
from kasbench_runner.services.s3_client import S3Client, S3OperationError

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.post("/metadata/export")
async def post_metadata_export(request: Request) -> ExportResponse:
    """Export run metadata document to S3.

    Constructs a comprehensive run_details.json containing:
    - timestamp (ISO 8601 UTC)
    - environment (all 12 RunnerConfig fields)
    - initialization (all 15 InitializeRequest fields)
    - roles (per-role parameters from ROLE_PARAMS)
    - manifests (from MANIFEST_REPOS)
    - status (current benchmark status equivalent to GET /status)

    Returns 200 with s3Key and timestamp on success.
    Returns 409 if benchmark is NOT_INITIALIZED.
    Returns 500 if S3 upload fails.
    """
    state: BenchmarkState = request.app.state.benchmark_state
    config: RunnerConfig = request.app.state.config

    # State guard: reject if NOT_INITIALIZED
    if state.status == BenchmarkStatus.NOT_INITIALIZED:
        return build_error_response(  # type: ignore[return-value]
            error="benchmark_not_initialized",
            message="The system has not been initialized. Call POST /initialize first.",
            status_code=409,
            current_status=state.status.value,
        )

    init_config = state.config
    run_identifier = init_config.run_identifier
    trial_identifier = init_config.trial_identifier
    s3_bucket = init_config.s3_bucket

    timestamp = datetime.now(timezone.utc)

    # Build the run_details document
    run_details = _build_run_details(state, config, timestamp)

    # Upload to S3
    s3_key = f"{run_identifier}/{trial_identifier}/run_details.json"
    s3_client = S3Client(bucket=s3_bucket)

    log = logger.bind(
        run_identifier=run_identifier,
        trial_identifier=trial_identifier,
        s3_key=s3_key,
    )
    log.info("metadata_export_start")

    try:
        data = json.dumps(run_details, default=str).encode("utf-8")
        await s3_client.upload_json(key=s3_key, data=data)
    except S3OperationError as exc:
        log.error(
            "metadata_export_s3_failed",
            exception_class=type(exc).__name__,
            exception_message=str(exc),
        )
        return build_error_response(  # type: ignore[return-value]
            error="s3_operation_failed",
            message=f"S3 operation failed: {exc.message}",
            status_code=500,
            bucket=s3_bucket,
            key=s3_key,
        )

    log.info("metadata_export_success")

    return ExportResponse(
        message="Metadata exported successfully",
        s3_key=s3_key,
        timestamp=timestamp,
    )


def _build_run_details(
    state: BenchmarkState,
    config: RunnerConfig,
    timestamp: datetime,
) -> dict:
    """Construct the run_details.json document.

    Args:
        state: Current benchmark state with initialization config.
        config: Runner environment configuration.
        timestamp: The generation timestamp.

    Returns:
        Dictionary representing the full run_details document.
    """
    init_config = state.config

    # Environment section: all 12 RunnerConfig fields
    environment = {
        "HOST": config.host,
        "PORT": config.port,
        "SSH_USER": config.ssh_user,
        "SSH_CONNECT_TIMEOUT": config.ssh_connect_timeout,
        "NODE_READINESS_TIMEOUT_SECONDS": config.node_readiness_timeout_seconds,
        "NODE_READINESS_POLL_INTERVAL": config.node_readiness_poll_interval,
        "HEALTH_CHECK_MAX_ATTEMPTS": config.health_check_max_attempts,
        "HEALTH_CHECK_INTERVAL_SECONDS": config.health_check_interval_seconds,
        "RABBITMQ_IMAGE": config.rabbitmq_image,
        "HTTP_CONNECT_TIMEOUT": config.http_connect_timeout,
        "HTTP_READ_TIMEOUT": config.http_read_timeout,
        "MANIFEST_FETCH_TIMEOUT": config.manifest_fetch_timeout,
    }

    # Initialization section: all 15 InitializeRequest fields
    initialization = {
        "autoscaler": init_config.autoscaler,
        "controlPlaneNode": init_config.control_plane_node,
        "amdWorkerNodes": init_config.amd_worker_nodes,
        "armWorkerNodes": init_config.arm_worker_nodes,
        "s3Bucket": init_config.s3_bucket,
        "globecoUrl": init_config.globeco_url,
        "runIdentifier": init_config.run_identifier,
        "trialIdentifier": init_config.trial_identifier,
        "clusterCidrRange": init_config.cluster_cidr_range,
        "kubernetesVersion": init_config.kubernetes_version,
        "loadGeneratorImage": init_config.load_generator_image,
        "runDurationMinutes": init_config.run_duration_minutes,
        "globecoPort": init_config.globeco_port,
        "skipKubernetesInstall": init_config.skip_kubernetes_install,
        "skipManifestInstall": init_config.skip_manifest_install,
        "forceManifestInstall": init_config.force_manifest_install,
    }

    # Roles section: per-role parameters from ROLE_PARAMS
    roles = {}
    for role_name, params in ROLE_PARAMS.items():
        roles[role_name] = {
            "base_load_intensity": params.base_load_intensity,
            "base_delay_percentage": params.base_delay_percentage,
            "spawn_rate": params.spawn_rate,
        }

    # Manifests section: from MANIFEST_REPOS
    manifests = [
        {"owner": repo["owner"], "repo": repo["repo"], "tag": repo["tag"]}
        for repo in MANIFEST_REPOS
    ]

    # Status section: equivalent to GET /status response
    load_generators = []
    if state.status != BenchmarkStatus.NOT_INITIALIZED:
        # Include load generator status if available
        # Note: This provides the last-known status from state;
        # a live query would require hitting the LG /health endpoints
        pass

    status_section = {
        "status": state.status.value,
        "startTime": state.start_time.isoformat() if state.start_time else None,
        "endTime": state.end_time.isoformat() if state.end_time else None,
        "loadGenerators": load_generators,
    }

    return {
        "timestamp": timestamp.isoformat(),
        "environment": environment,
        "initialization": initialization,
        "roles": roles,
        "manifests": manifests,
        "status": status_section,
    }
