# Verification note — pod-readiness gate for rollout success determination

This note records the exact commands run and their results so the reviewer can
read the evidence without re-running the suites. It addresses the blocking
review finding "Missing full-suite / lint verification evidence" and confirms
the non-blocking init-container finding.

Environment: Python 3.14.2 (`.venv`), uv-managed. Linter present: `ruff 0.11.12`.
`mypy` is NOT installed and is NOT configured in `pyproject.toml` (the README
notes mypy only "if mypy is added"), so ruff is the project's active linter and
was used here.

## Root cause (confirmed)

`wait_for_all_rollouts` fans out to `wait_for_rollout` (deployments) and
`wait_for_statefulset` (statefulsets). Each declared "done" solely from the
controller's replica counters: `_is_rollout_complete` (updatedReplicas ==
replicas, readyReplicas == replicas, Progressing reason
`NewReplicaSetAvailable`) and `_is_statefulset_ready` (readyReplicas ==
replicas, updatedReplicas == replicas, currentRevision == updateRevision).
Those counters can be satisfied while an individual pod is Running-but-not-Ready
(failing readiness probe) or in CrashLoopBackOff — and `CrashLoopBackOff` is
commented out of `UNRECOVERABLE_POD_CONDITIONS` — so an unhealthy pod reached
HTTP 200.

## Fix (already implemented in working tree)

Added private helper `_all_pods_ready(workload_name, namespace,
expected_replicas)` in `src/kasbench_runner/services/rollout_monitor.py`,
mirroring the pod-discovery pattern of `_check_pod_conditions`
(`kr8s.asyncio.api()` + `api.get("pods", namespace=..., label_selector=f"app={name}")`).
A pod is ready only when its `status.conditions` has `type == "Ready"` with
`status == "True"` AND every `status.containerStatuses[*].ready` is `True`.
It fails closed: empty pod list with `expected_replicas > 0`, any not-ready pod,
or any pod-query exception returns `False`, so the poll loop keeps waiting.
Both success branches now AND the controller check with
`desired_replicas == 0 or await self._all_pods_ready(...)` (the `== 0` guard
preserves scale-to-zero "done" semantics). No route, response-model, or
exception-type changes.

## Commands run and results

### 1. Focused new tests — PASS (5/5)

```
uv run pytest tests/test_rollout_monitor.py -v
```
Result: 5 passed, 1 warning in 2.29s.
- test_deployment_not_ready_pod_does_not_succeed PASSED
- test_deployment_all_pods_ready_succeeds PASSED
- test_statefulset_not_ready_pod_does_not_succeed PASSED
- test_all_pods_ready_empty_pod_list_with_replicas_is_false PASSED
- test_all_pods_ready_healthy_pods_is_true PASSED

### 2. Lint (ruff) — PASS (no findings)

```
uv run ruff check src/kasbench_runner/services/rollout_monitor.py tests/test_rollout_monitor.py
```
Result: exit code 0, no output (no lint errors introduced).

### 3. Full test suite — 42 passed, 6 failed (all pre-existing baseline)

```
uv run pytest tests/ -q
```
Result: 6 failed, 42 passed, 1 warning in 3.03s.

The 6 failures match the documented pre-existing baseline exactly:
- tests/test_metrics_config.py::test_gauge_metrics_count (assert 28 == 27)
- tests/test_metrics_config.py::test_all_metrics_count (assert 75 == 74)
- tests/test_rollout_config.py::test_default_rollout_deployments_count
- tests/test_rollout_config.py::test_default_rollout_deployments_namespaces
- tests/test_rollout_config.py::test_runner_config_default_rollout_deployments
- tests/test_rollout_config.py::test_runner_config_empty_string_returns_defaults

These are config count/namespace assertion drifts in `config.py` /
`metrics_config.py`, which this change does not touch.

### 4. Baseline confirmation — the 6 failures predate this change

Stashed only `rollout_monitor.py`, ran the two affected test files on clean HEAD:

```
git stash push src/kasbench_runner/services/rollout_monitor.py
uv run pytest tests/test_metrics_config.py tests/test_rollout_config.py -q
git stash pop
```
Result on clean HEAD: 6 failed, 8 passed — the identical 6 failures. This proves
they are pre-existing baseline, not regressions from this change. `git status`
confirms the only non-test source change is `rollout_monitor.py`.

## Review findings addressed

1. **Missing full-suite / lint verification evidence (blocking, confirmed)** —
   resolved. Full `pytest tests/` and `ruff check` outputs are recorded above,
   plus a stash-based baseline confirmation that the 6 remaining failures exist
   on clean HEAD independent of this change.

2. **Container-only readiness, init containers not gated (non-blocking,
   possible)** — confirmed no code change needed. A pod blocked in an init
   container has its pod-level `Ready` status condition set to `False` by the
   kubelet, which `_all_pods_ready` already rejects via its `Ready == "True"`
   check (the first gate it applies per pod). No monitored workload relies on
   init-container readiness being surfaced as a separate success signal; the
   `app=<name>` label discovery and the `Ready` condition gate already hold such
   a pod as not-ready until it fully passes probes or the timeout fires. Adding
   an `initContainerStatuses` loop would be redundant with the `Ready` condition
   gate and is intentionally omitted to keep the helper minimal.

## Constraints verified unchanged

No edits to `src/kasbench_runner/routes/rollout.py`,
`src/kasbench_runner/models/responses.py`, or `src/kasbench_runner/errors.py`.
Polling constants (`POLL_INTERVAL`/`RETRY_LIMIT`/`RETRY_DELAY`), the shared
`wait_for_all_rollouts` timeout fan-out, and `RolloutTimeoutError` /
`RolloutUnrecoverableError` / `KubernetesApiError` raising paths are unchanged.
