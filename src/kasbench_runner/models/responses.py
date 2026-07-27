"""Pydantic models for API response bodies."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Export-related response models
# ---------------------------------------------------------------------------


class ExportResultEntry(BaseModel):
    """Per-role export result."""

    role: str
    status: str  # "success" or "failed"
    s3_key: Optional[str] = Field(default=None, alias="s3Key")
    error: Optional[str] = None

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class ExportResponse(BaseModel):
    """Generic export response for output/db/metadata exports."""

    message: str
    files_exported: Optional[int] = Field(default=None, alias="filesExported")
    results: Optional[list[ExportResultEntry]] = None
    s3_prefix: Optional[str] = Field(default=None, alias="s3Prefix")
    s3_key: Optional[str] = Field(default=None, alias="s3Key")
    s3_path: Optional[str] = Field(default=None, alias="s3Path")
    timestamp: datetime

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class HelmUninstallResult(BaseModel):
    """Per-release Helm uninstall result."""

    release: str
    namespace: str
    status: str  # "uninstalled" or "failed"
    error: Optional[str] = None


class ShutdownResponse(BaseModel):
    """POST /shutdown response."""

    results: list[HelmUninstallResult]
    timestamp: datetime

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


# ---------------------------------------------------------------------------
# Existing response models
# ---------------------------------------------------------------------------


class ErrorResponse(BaseModel):
    """Standard error response with full diagnostic context."""

    error: str
    message: str
    context: dict
    timestamp: datetime

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class LoadGeneratorStatus(BaseModel):
    """Individual load generator status within GET /status response."""

    role: str
    status: str
    start_time: Optional[datetime] = Field(default=None, alias="startTime")
    end_time: Optional[datetime] = Field(default=None, alias="endTime")

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class StatusResponse(BaseModel):
    """GET /status response."""

    status: str
    start_time: Optional[datetime] = Field(default=None, alias="startTime")
    end_time: Optional[datetime] = Field(default=None, alias="endTime")
    load_generators: list[LoadGeneratorStatus] = Field(
        default_factory=list, alias="loadGenerators"
    )

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class StartResponse(BaseModel):
    """POST /start response."""

    start_time: datetime = Field(alias="startTime")

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class AbortResponse(BaseModel):
    """POST /abort response."""

    abort_time: datetime = Field(alias="abortTime")
    results: dict[str, str]  # role -> "success" | error message

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class MetricsErrorEntry(BaseModel):
    """A single error from metrics collection."""

    metric_name: str = Field(alias="metricName")
    phase: str  # "query" or "upload"
    error: str

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class MetricsResponse(BaseModel):
    """POST /metrics response body."""

    message: str
    metrics_uploaded: int = Field(alias="metricsUploaded")
    metrics_total: int = Field(alias="metricsTotal")
    s3_prefix: str = Field(alias="s3Prefix")
    errors: list[MetricsErrorEntry] = Field(default_factory=list)
    timestamp: datetime

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


# ---------------------------------------------------------------------------
# Rollout and Snapshot response models
# ---------------------------------------------------------------------------


class RolloutWaitResponse(BaseModel):
    """POST /rollout/wait success response."""

    deployment_name: str = Field(alias="deploymentName")
    namespace: str
    elapsed_seconds: float = Field(alias="elapsedSeconds")

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class RolloutAllResponse(BaseModel):
    """POST /rollout/all success response."""

    deployments_checked: int = Field(alias="deploymentsChecked")
    elapsed_seconds: float = Field(alias="elapsedSeconds")

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class SnapshotResponse(BaseModel):
    """POST /snapshot success response."""

    phase: str
    files_uploaded: int = Field(alias="filesUploaded")
    s3_prefix: str = Field(alias="s3Prefix")

    model_config = {"populate_by_name": True, "serialize_by_alias": True}
