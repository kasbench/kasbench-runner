"""Internal state models for benchmark lifecycle management."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from kasbench_runner.models.requests import InitializeRequest


@dataclass
class EffectiveRoleParameters:
    """Actual per-role parameters used for a benchmark trial.

    Captures the values sent to a Load Generator at /start time, after
    applying any overrides from the request's roleParams field on top of
    the ROLE_PARAMS defaults.
    """

    base_load_intensity: int
    base_delay_percentage: int
    spawn_rate: int
    fixed: Optional[int] = None


class BenchmarkStatus(str, Enum):
    """Benchmark lifecycle states."""

    NOT_INITIALIZED = "not-initialized"
    NOT_STARTED = "not-started"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    ABORTED = "aborted"


@dataclass
class BenchmarkState:
    """Mutable singleton holding the entire benchmark lifecycle state."""

    status: BenchmarkStatus = BenchmarkStatus.NOT_INITIALIZED
    config: Optional[InitializeRequest] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    # Effective per-role parameters actually used at /start time (overrides
    # applied on top of ROLE_PARAMS defaults). Empty until a benchmark starts.
    effective_role_params: dict[str, EffectiveRoleParameters] = field(
        default_factory=dict
    )

    # Internal flags
    kubernetes_installed: bool = False
    globeco_installed: bool = False
    load_generators_installed: bool = False

    # Snapshot concurrency guard
    snapshot_in_progress: bool = False

    @property
    def initialization_complete(self) -> bool:
        """True when all installation steps have completed successfully."""
        return (
            self.kubernetes_installed
            and self.globeco_installed
            and self.load_generators_installed
        )
