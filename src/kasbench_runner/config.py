"""Configuration module for KASBench Benchmark Runner.

Loads all configuration from environment variables with sensible defaults.
Invalid numeric values fall back to defaults with a WARNING log.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from pydantic import model_validator
from pydantic_settings import BaseSettings

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Validation ranges for numeric environment variables
# Maps field name -> (default, min, max)
# ---------------------------------------------------------------------------
_RANGE_VALIDATED_FIELDS: dict[str, tuple[int, int, int]] = {
    "NODE_READINESS_TIMEOUT_SECONDS": (300, 60, 1800),
    "HEALTH_CHECK_MAX_ATTEMPTS": (3, 1, 10),
    "HEALTH_CHECK_INTERVAL_SECONDS": (5, 1, 60),
}


class RunnerConfig(BaseSettings):
    """Application configuration loaded from environment variables."""

    # Server
    host: str = "0.0.0.0"
    port: int = 8080

    # SSH
    ssh_user: str = "ubuntu"
    ssh_connect_timeout: int = 30

    # Kubernetes
    node_readiness_timeout_seconds: int = 300
    node_readiness_poll_interval: int = 10

    # Health checks
    health_check_max_attempts: int = 3
    health_check_interval_seconds: int = 5

    # Docker
    rabbitmq_image: str = "rabbitmq:4-management"

    # HTTP client
    http_connect_timeout: int = 10
    http_read_timeout: int = 30

    # Manifest fetching
    manifest_fetch_timeout: int = 30

    model_config = {"env_prefix": "", "case_sensitive": False}

    @model_validator(mode="before")
    @classmethod
    def _validate_ranges(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Validate numeric env vars are within range; fallback to default with WARNING."""
        for env_name, (default, min_val, max_val) in _RANGE_VALIDATED_FIELDS.items():
            # Check both the env alias (uppercase) and the Python field name (lowercase)
            field_name = env_name.lower()
            # pydantic-settings may pass the value under either key
            raw_value = values.get(env_name) or values.get(field_name)

            if raw_value is None:
                # Not set — pydantic will apply the field default
                continue

            # Try to parse as integer
            try:
                int_value = int(raw_value)
            except (ValueError, TypeError):
                structlog.get_logger().warning(
                    "invalid_config_value",
                    variable=env_name,
                    value=raw_value,
                    reason="not a valid integer",
                    default_applied=default,
                )
                values[field_name] = default
                # Remove the alias key if present to avoid conflicts
                values.pop(env_name, None)
                continue

            # Check range
            if int_value < min_val or int_value > max_val:
                structlog.get_logger().warning(
                    "invalid_config_value",
                    variable=env_name,
                    value=int_value,
                    reason=f"outside valid range [{min_val}, {max_val}]",
                    default_applied=default,
                )
                values[field_name] = default
                # Remove the alias key if present to avoid conflicts
                values.pop(env_name, None)
                continue

        return values


# ---------------------------------------------------------------------------
# Role constants
# ---------------------------------------------------------------------------

VALID_ROLES: tuple[str, ...] = (
    "back-office",
    "portfolio-manager",
    "trader",
    "investor",
    "it-operations",
)

ROLE_PORTS: dict[str, int] = {
    "back-office": 8081,
    "portfolio-manager": 8082,
    "trader": 8083,
    "investor": 8084,
    "it-operations": 8085,
}


@dataclass(frozen=True)
class RoleParameters:
    """Per-role parameters for load generation."""

    base_load_intensity: int
    base_delay_percentage: int
    spawn_rate: int


ROLE_PARAMS: dict[str, RoleParameters] = {
    "back-office": RoleParameters(100, 100, 10),
    "portfolio-manager": RoleParameters(100, 100, 10),
    "trader": RoleParameters(100, 100, 10),
    "investor": RoleParameters(10, 100, 10),
    "it-operations": RoleParameters(100, 100, 1),
}

MANIFEST_REPOS: list[dict[str, str]] = [
    {"owner": "kasbench", "repo": "globeco-kafka", "tag": "v1.1.1"},
    {"owner": "kasbench", "repo": "globeco-confirmation-service", "tag": "v1.1.1"},
    {"owner": "kasbench", "repo": "globeco-execution-service", "tag": "v1.1.1"},
    {"owner": "kasbench", "repo": "globeco-fix-engine", "tag": "v1.1.1"},
    {"owner": "kasbench", "repo": "globeco-order-generation-service", "tag": "v1.1.1"},
    {"owner": "kasbench", "repo": "globeco-order-service", "tag": "v1.1.1"},
    {"owner": "kasbench", "repo": "globeco-portfolio-accounting-service", "tag": "v1.1.1"},
    {"owner": "kasbench", "repo": "globeco-portfolio-management-portal", "tag": "v1.1.1"},
    {"owner": "kasbench", "repo": "globeco-portfolio-service", "tag": "v1.1.1"},
    {"owner": "kasbench", "repo": "globeco-pricing-service", "tag": "v1.1.1"},
    {"owner": "kasbench", "repo": "globeco-security-service", "tag": "v1.1.1"},
    {"owner": "kasbench", "repo": "globeco-trade-service", "tag": "v1.1.1"},
    {"owner": "kasbench", "repo": "globeco-observability", "tag": "v1.1.2"},
]
