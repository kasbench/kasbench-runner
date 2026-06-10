"""Pydantic models for API response bodies."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


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
