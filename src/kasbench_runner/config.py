"""Configuration module for KASBench Benchmark Runner.

Loads all configuration from environment variables with sensible defaults.
Invalid numeric values fall back to defaults with a WARNING log.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import structlog
from pydantic import Field, model_validator
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


@dataclass(frozen=True)
class DeploymentSpec:
    """Identifies a Kubernetes Deployment to monitor."""

    name: str
    namespace: str


@dataclass(frozen=True)
class StatefulSetSpec:
    """Identifies a Kubernetes StatefulSet to monitor."""

    name: str
    namespace: str


# ---------------------------------------------------------------------------
# Default deployment list for /rollout/all
# Loaded from ROLLOUT_DEPLOYMENTS env var (JSON) or defaults below
# ---------------------------------------------------------------------------
DEFAULT_ROLLOUT_DEPLOYMENTS: list[dict[str, str]] = [
    # elasticsearch namespace (1)
    {"name": "elasticsearch", "namespace": "elasticsearch"},
    # globeco namespace (12)
    {"name": "globeco-allocation-service", "namespace": "globeco"},
    {"name": "globeco-confirmation-service", "namespace": "globeco"},
    {"name": "globeco-execution-service", "namespace": "globeco"},
    {"name": "globeco-fix-engine", "namespace": "globeco"},
    {"name": "globeco-order-generation-service", "namespace": "globeco"},
    {"name": "globeco-order-service", "namespace": "globeco"},
    {"name": "globeco-portfolio-accounting-service", "namespace": "globeco"},
    {"name": "globeco-portfolio-management-portal", "namespace": "globeco"},
    {"name": "globeco-portfolio-service", "namespace": "globeco"},
    {"name": "globeco-pricing-service", "namespace": "globeco"},
    {"name": "globeco-security-service", "namespace": "globeco"},
    {"name": "globeco-trade-service", "namespace": "globeco"},
    # kube-system namespace (3)
    {"name": "coredns", "namespace": "kube-system"},
    {"name": "ebs-csi-controller", "namespace": "kube-system"},
    {"name": "metrics-server", "namespace": "kube-system"},
    # monitoring namespace (5)k
    {"name": "otel-collector", "namespace": "monitoring"},
    {"name": "prometheus-server", "namespace": "monitoring"},
    {"name": "prometheus-kube-state-metrics", "namespace": "monitoring"},
    {"name": "prometheus-prometheus-pushgateway", "namespace": "monitoring"},
    # observability namespace (1)
    {"name": "jaeger", "namespace": "observability"},
    # opentelemetry-operator-system namespace (1)
    {"name": "opentelemetry-operator-controller-manager", "namespace": "opentelemetry-operator-system"},
]


# ---------------------------------------------------------------------------
# Default statefulset list for /rollout/all
# Loaded from ROLLOUT_STATEFULSETS env var (JSON) or defaults below
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Default scale-to-zero deployments (skipped during rollout when autoscaler=keda)
# Loaded from SCALE_TO_ZERO_DEPLOYMENTS env var (JSON) or defaults below
# ---------------------------------------------------------------------------
DEFAULT_SCALE_TO_ZERO_DEPLOYMENTS: list[dict[str, str]] = [
    {"name": "globeco-confirmation-service", "namespace": "globeco"},
    {"name": "globeco-fix-engine", "namespace": "globeco"},
]


DEFAULT_ROLLOUT_STATEFULSETS: list[dict[str, str]] = [
    # globeco namespace (12)
    {"name": "globeco-allocation-service-postgresql", "namespace": "globeco"},
    {"name": "globeco-execution-service-kafka", "namespace": "globeco"},
    {"name": "globeco-fix-engine-postgresql", "namespace": "globeco"},
    {"name": "globeco-order-generation-service-mongodb", "namespace": "globeco"},
    {"name": "globeco-order-generation-service-redis", "namespace": "globeco"},
    {"name": "globeco-order-service-postgresql", "namespace": "globeco"},
    {"name": "globeco-portfolio-accounting-service-postgresql", "namespace": "globeco"},
    {"name": "globeco-portfolio-accounting-service-redis", "namespace": "globeco"},
    {"name": "globeco-portfolio-service-mongodb", "namespace": "globeco"},
    {"name": "globeco-pricing-service-postgresql", "namespace": "globeco"},
    {"name": "globeco-security-service-mongodb", "namespace": "globeco"},
    {"name": "globeco-trade-service-postgresql", "namespace": "globeco"},
    # monitoring namespace (1)
    {"name": "prometheus-alertmanager", "namespace": "monitoring"},
]


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
    prometheus_values_url: str = "https://raw.githubusercontent.com/kasbench/globeco-observability/v1.1.5/k8s_aws/values_prometheus.yaml"

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

    # Helm
    helm_install_timeout: int = 1200
    helm_repo_name: str = "globeco-repo"
    helm_repo_url: str = "https://kasbench.github.io/globeco-helm"
    helm_chart_name: str = "globeco"
    helm_release_name: str = "globeco"
    helm_namespace: str = "globeco"

    # Rollout configuration
    rollout_deployments_json: str = Field(default="", alias="ROLLOUT_DEPLOYMENTS")
    rollout_statefulsets_json: str = Field(default="", alias="ROLLOUT_STATEFULSETS")
    scale_to_zero_deployments_json: str = Field(default="", alias="SCALE_TO_ZERO_DEPLOYMENTS")

    model_config = {"env_prefix": "", "case_sensitive": False, "populate_by_name": True}

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

    @property
    def rollout_deployments(self) -> list[DeploymentSpec]:
        """Parse deployment list from JSON env var or use defaults."""
        if self.rollout_deployments_json:
            parsed = json.loads(self.rollout_deployments_json)
            return [
                DeploymentSpec(name=d["name"], namespace=d["namespace"])
                for d in parsed
            ]
        return [
            DeploymentSpec(name=d["name"], namespace=d["namespace"])
            for d in DEFAULT_ROLLOUT_DEPLOYMENTS
        ]

    @property
    def rollout_statefulsets(self) -> list[StatefulSetSpec]:
        """Parse statefulset list from JSON env var or use defaults."""
        if self.rollout_statefulsets_json:
            parsed = json.loads(self.rollout_statefulsets_json)
            return [
                StatefulSetSpec(name=s["name"], namespace=s["namespace"])
                for s in parsed
            ]
        return [
            StatefulSetSpec(name=s["name"], namespace=s["namespace"])
            for s in DEFAULT_ROLLOUT_STATEFULSETS
        ]

    @property
    def scale_to_zero_deployments(self) -> list[DeploymentSpec]:
        """Parse scale-to-zero deployment list from JSON env var or use defaults."""
        if self.scale_to_zero_deployments_json:
            parsed = json.loads(self.scale_to_zero_deployments_json)
            return [
                DeploymentSpec(name=d["name"], namespace=d["namespace"])
                for d in parsed
            ]
        return [
            DeploymentSpec(name=d["name"], namespace=d["namespace"])
            for d in DEFAULT_SCALE_TO_ZERO_DEPLOYMENTS
        ]


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
    "back-office": RoleParameters(100, 80, 10),
    "portfolio-manager": RoleParameters(100, 80, 10),
    "trader": RoleParameters(100, 80, 10),
    "investor": RoleParameters(10, 80, 10),
    "it-operations": RoleParameters(100, 100, 1),
}

MANIFEST_REPOS: list[dict[str, str]] = [
    {"owner": "kasbench", "repo": "globeco-observability", "tag": "v1.1.5"},
    {"owner": "kasbench", "repo": "globeco-gateway", "tag": "v1.1.5"},
    {"owner": "kasbench", "repo": "globeco-kafka", "tag": "v1.1.5"},
    {"owner": "kasbench", "repo": "globeco-order-generation-service", "tag": "v1.1.5"},
    {"owner": "kasbench", "repo": "globeco-order-service", "tag": "v1.1.5"},
    {"owner": "kasbench", "repo": "globeco-portfolio-accounting-service", "tag": "v1.1.5"},
    {"owner": "kasbench", "repo": "globeco-portfolio-management-portal", "tag": "v1.1.5"},
    {"owner": "kasbench", "repo": "globeco-portfolio-service", "tag": "v1.1.5"},
    {"owner": "kasbench", "repo": "globeco-pricing-service", "tag": "v1.1.5"},
    {"owner": "kasbench", "repo": "globeco-security-service", "tag": "v1.1.5"},
    {"owner": "kasbench", "repo": "globeco-trade-service", "tag": "v1.1.5"},
    {"owner": "kasbench", "repo": "globeco-execution-service", "tag": "v1.1.5"},
    {"owner": "kasbench", "repo": "globeco-fix-engine", "tag": "v1.1.5"},
    {"owner": "kasbench", "repo": "globeco-allocation-service", "tag": "v1.1.5"},
    {"owner": "kasbench", "repo": "globeco-confirmation-service", "tag": "v1.1.5"},
]
