"""Tests for rollout deployment configuration.

Validates that DEFAULT_ROLLOUT_DEPLOYMENTS and the RunnerConfig
rollout_deployments property work correctly.
"""

import json

from kasbench_runner.config import (
    DEFAULT_ROLLOUT_DEPLOYMENTS,
    DeploymentSpec,
    RunnerConfig,
)


def test_default_rollout_deployments_count():
    """DEFAULT_ROLLOUT_DEPLOYMENTS should have exactly 24 entries."""
    assert len(DEFAULT_ROLLOUT_DEPLOYMENTS) == 24


def test_default_rollout_deployments_structure():
    """Each entry should have 'name' and 'namespace' keys."""
    for entry in DEFAULT_ROLLOUT_DEPLOYMENTS:
        assert "name" in entry
        assert "namespace" in entry
        assert isinstance(entry["name"], str)
        assert isinstance(entry["namespace"], str)


def test_default_rollout_deployments_namespaces():
    """Verify expected namespace distribution."""
    namespaces = [d["namespace"] for d in DEFAULT_ROLLOUT_DEPLOYMENTS]
    assert namespaces.count("elasticsearch") == 1
    assert namespaces.count("globeco") == 14
    assert namespaces.count("kube-system") == 2
    assert namespaces.count("monitoring") == 5
    assert namespaces.count("observability") == 1
    assert namespaces.count("opentelemetry-operator-system") == 1


def test_deployment_spec_frozen():
    """DeploymentSpec should be immutable."""
    spec = DeploymentSpec(name="test", namespace="default")
    try:
        spec.name = "other"
        raise AssertionError("Should have raised AttributeError")
    except AttributeError:
        pass


def test_runner_config_default_rollout_deployments():
    """RunnerConfig.rollout_deployments returns defaults when env var not set."""
    config = RunnerConfig()
    deployments = config.rollout_deployments
    assert len(deployments) == 24
    assert all(isinstance(d, DeploymentSpec) for d in deployments)
    assert deployments[0] == DeploymentSpec(
        name="elasticsearch-master", namespace="elasticsearch"
    )


def test_runner_config_custom_rollout_deployments():
    """RunnerConfig.rollout_deployments parses JSON when env var is set."""
    custom = [
        {"name": "my-app", "namespace": "default"},
        {"name": "my-db", "namespace": "data"},
    ]
    config = RunnerConfig(ROLLOUT_DEPLOYMENTS=json.dumps(custom))
    deployments = config.rollout_deployments
    assert len(deployments) == 2
    assert deployments[0] == DeploymentSpec(name="my-app", namespace="default")
    assert deployments[1] == DeploymentSpec(name="my-db", namespace="data")


def test_runner_config_empty_string_returns_defaults():
    """Empty ROLLOUT_DEPLOYMENTS env var should return defaults."""
    config = RunnerConfig(ROLLOUT_DEPLOYMENTS="")
    assert len(config.rollout_deployments) == 24
