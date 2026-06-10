"""Internal state models for benchmark lifecycle management."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from kasbench_runner.models.requests import InitializeRequest


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

    # Internal flags
    kubernetes_installed: bool = False
    globeco_installed: bool = False
    load_generators_installed: bool = False

    @property
    def initialization_complete(self) -> bool:
        """True when all installation steps have completed successfully."""
        return (
            self.kubernetes_installed
            and self.globeco_installed
            and self.load_generators_installed
        )
