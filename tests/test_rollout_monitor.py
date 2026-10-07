"""Tests for the RolloutMonitor pod-readiness gate.

Reproduces the bug where a rollout was reported successful based solely on the
controller's replica counters even though an individual pod was not actually
Ready (failing probe / CrashLoopBackOff). The monitor must only succeed when
every pod belonging to the workload is genuinely healthy.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from kasbench_runner.config import StatefulSetSpec
from kasbench_runner.errors import RolloutTimeoutError
from kasbench_runner.services.rollout_monitor import DeploymentSpec, RolloutMonitor


class FakeWorkload:
    """Minimal stand-in for a kr8s Deployment/StatefulSet object."""

    def __init__(self, name: str, status: dict, spec: dict) -> None:
        self.name = name
        self.status = status
        self.spec = spec


class FakePodStatus:
    """Pod status wrapper exposing the dict-style .get used by the monitor."""

    def __init__(self, data: dict) -> None:
        self._data = data

    def get(self, key, default=None):
        return self._data.get(key, default)


class FakePod:
    """Minimal stand-in for a kr8s Pod object."""

    def __init__(self, name: str, status: dict) -> None:
        self.name = name
        self.status = FakePodStatus(status)


async def _async_iter(items):
    """Yield items the way kr8s api.get(...) is consumed (async for)."""
    for item in items:
        yield item


def _complete_deployment_status() -> dict:
    """A deployment .status that satisfies _is_rollout_complete."""
    return {
        "updatedReplicas": 1,
        "readyReplicas": 1,
        "conditions": [
            {"type": "Progressing", "reason": "NewReplicaSetAvailable"},
        ],
    }


def _ready_statefulset_status() -> dict:
    """A statefulset .status that satisfies _is_statefulset_ready."""
    return {
        "readyReplicas": 1,
        "updatedReplicas": 1,
        "currentRevision": "rev-1",
        "updateRevision": "rev-1",
    }


def _ready_pod_status() -> dict:
    return {
        "conditions": [{"type": "Ready", "status": "True"}],
        "containerStatuses": [{"name": "app", "ready": True}],
    }


def _not_ready_pod_status() -> dict:
    return {
        "conditions": [{"type": "Ready", "status": "False"}],
        "containerStatuses": [{"name": "app", "ready": False}],
    }


def _make_fake_api(workload_kind: str, workload: FakeWorkload, pods: list[FakePod]):
    """Build a fake kr8s api whose .get dispatches on resource kind."""

    def _get(resource, *args, **kwargs):
        if resource == "pods":
            return _async_iter(pods)
        if resource in (workload_kind, "deployments", "statefulsets"):
            return _async_iter([workload])
        return _async_iter([])

    fake_api = AsyncMock()
    fake_api.get = _get
    return fake_api


@pytest.fixture(autouse=True)
def fast_poll(monkeypatch):
    """Make the poll loop resolve the timeout path quickly."""
    monkeypatch.setattr(RolloutMonitor, "POLL_INTERVAL", 0)


@pytest.mark.asyncio
async def test_deployment_not_ready_pod_does_not_succeed():
    """Controller status complete but pod not Ready => times out, no success."""
    workload = FakeWorkload(
        name="app",
        status=_complete_deployment_status(),
        spec={"replicas": 1},
    )
    pods = [FakePod("app-0", _not_ready_pod_status())]
    fake_api = _make_fake_api("deployments", workload, pods)

    monitor = RolloutMonitor()
    with patch(
        "kasbench_runner.services.rollout_monitor.kr8s.asyncio.api",
        AsyncMock(return_value=fake_api),
    ):
        with pytest.raises(RolloutTimeoutError):
            await monitor.wait_for_all_rollouts(
                [DeploymentSpec("app", "ns")], timeout_seconds=1
            )


@pytest.mark.asyncio
async def test_deployment_all_pods_ready_succeeds():
    """Controller status complete AND pod Ready => returns without raising."""
    workload = FakeWorkload(
        name="app",
        status=_complete_deployment_status(),
        spec={"replicas": 1},
    )
    pods = [FakePod("app-0", _ready_pod_status())]
    fake_api = _make_fake_api("deployments", workload, pods)

    monitor = RolloutMonitor()
    with patch(
        "kasbench_runner.services.rollout_monitor.kr8s.asyncio.api",
        AsyncMock(return_value=fake_api),
    ):
        result = await monitor.wait_for_all_rollouts(
            [DeploymentSpec("app", "ns")], timeout_seconds=1
        )

    assert result is None


@pytest.mark.asyncio
async def test_statefulset_not_ready_pod_does_not_succeed():
    """StatefulSet controller ready but pod not Ready => times out, no success."""
    workload = FakeWorkload(
        name="sts",
        status=_ready_statefulset_status(),
        spec={"replicas": 1},
    )
    pods = [FakePod("sts-0", _not_ready_pod_status())]
    fake_api = _make_fake_api("statefulsets", workload, pods)

    monitor = RolloutMonitor()
    with patch(
        "kasbench_runner.services.rollout_monitor.kr8s.asyncio.api",
        AsyncMock(return_value=fake_api),
    ):
        with pytest.raises(RolloutTimeoutError):
            await monitor.wait_for_all_rollouts(
                [], timeout_seconds=1, statefulsets=[StatefulSetSpec("sts", "ns")]
            )


@pytest.mark.asyncio
async def test_all_pods_ready_empty_pod_list_with_replicas_is_false():
    """No pods found while replicas > 0 is not considered ready."""
    fake_api = _make_fake_api(
        "deployments",
        FakeWorkload("app", {}, {"replicas": 1}),
        [],
    )
    monitor = RolloutMonitor()
    with patch(
        "kasbench_runner.services.rollout_monitor.kr8s.asyncio.api",
        AsyncMock(return_value=fake_api),
    ):
        assert await monitor._all_pods_ready("app", "ns", 1) is False


@pytest.mark.asyncio
async def test_all_pods_ready_healthy_pods_is_true():
    """All pods Ready with all containers ready => True."""
    pods = [FakePod("app-0", _ready_pod_status())]
    fake_api = _make_fake_api(
        "deployments",
        FakeWorkload("app", {}, {"replicas": 1}),
        pods,
    )
    monitor = RolloutMonitor()
    with patch(
        "kasbench_runner.services.rollout_monitor.kr8s.asyncio.api",
        AsyncMock(return_value=fake_api),
    ):
        assert await monitor._all_pods_ready("app", "ns", 1) is True
