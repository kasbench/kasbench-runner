"""Pydantic models for API request bodies."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class InitializeRequest(BaseModel):
    """POST /initialize request body."""

    # Required fields — all must be non-empty
    autoscaler: str = Field(..., min_length=1)
    control_plane_node: str = Field(..., alias="controlPlaneNode", min_length=1)
    amd_worker_nodes: list[str] = Field(..., alias="amdWorkerNodes", min_length=1)
    arm_worker_nodes: list[str] = Field(default_factory=list, alias="armWorkerNodes")
    s3_bucket: str = Field(..., alias="s3Bucket", min_length=1)
    globeco_url: str = Field(..., alias="globecoUrl", min_length=1)

    @field_validator("amd_worker_nodes", "arm_worker_nodes", mode="after")
    @classmethod
    def filter_empty_hostnames(cls, v: list[str]) -> list[str]:
        """Remove empty strings from worker node lists."""
        return [hostname for hostname in v if hostname.strip()]

    # Optional with defaults
    run_identifier: str = Field(default="run001", alias="runIdentifier")
    trial_identifier: str = Field(default="trial001", alias="trialIdentifier")
    cluster_cidr_range: str = Field(default="10.244.0.0/16", alias="clusterCidrRange")
    kubernetes_version: str = Field(default="1.36.1", alias="kubernetesVersion")
    load_generator_image: str = Field(
        default="kasbench/kasbench-load-generator:latest",
        alias="loadGeneratorImage",
    )
    run_duration_minutes: int = Field(default=5, alias="runDurationMinutes", ge=1)
    globeco_port: int = Field(default=8080, alias="globecoPort", ge=1, le=65535)
    execution_data_fs: str = Field(default="none", alias="executionDataFs")
    skip_kubernetes_install: bool = Field(default=False, alias="skipKubernetesInstall")
    skip_manifest_install: bool = Field(default=False, alias="skipManifestInstall")
    force_manifest_install: bool = Field(default=False, alias="forceManifestInstall")

    model_config = {"populate_by_name": True}


class MetricsExportRequest(BaseModel):
    """POST /metrics/export request body."""

    overwrite: bool = False
    interval: str = "60s"
    step: str = "15s"
    prometheus_port: int = Field(default=31565, alias="prometheusPort", ge=1, le=65535)

    model_config = {"extra": "ignore", "populate_by_name": True}


class TsdbExportRequest(BaseModel):
    """POST /prometheus/tsdb/export request body."""

    prometheus_port: int = Field(default=31565, alias="prometheusPort", ge=1, le=65535)

    model_config = {"extra": "ignore", "populate_by_name": True}


class RolloutWaitRequest(BaseModel):
    """POST /rollout/wait request body."""

    deployment_name: str = Field(
        ..., alias="deploymentName", min_length=1, max_length=253
    )
    namespace: str = Field(..., alias="namespace", min_length=1, max_length=63)
    timeout: int = Field(..., ge=1, le=1800)

    model_config = {"populate_by_name": True}


class RolloutAllRequest(BaseModel):
    """POST /rollout/all request body."""

    timeout: int = Field(..., ge=1, le=3600)

    model_config = {"populate_by_name": True}


class SnapshotRequest(BaseModel):
    """POST /snapshot request body."""

    phase: Literal["pre", "post"]

    model_config = {"populate_by_name": True}
