# Implementation Plan — Fix `/rollout/all` returning success with unhealthy pods

## Root cause (confirmed by reading the code)

The `/rollout/all` route (`src/kasbench_runner/routes/rollout.py:109-129`) is a thin wrapper that
calls `monitor.wait_for_all_rollouts(...)`. The bug is in the success-determination logic of
`src/kasbench_runner/services/rollout_monitor.py`, not the route.

`wait_for_all_rollouts` fans out to `wait_for_rollout` (deployments) and `wait_for_statefulset`
(statefulsets). Each of those decides "done" entirely from the workload controller's `.status`
replica counters:

- `_is_rollout_complete(status, spec)` returns `True` when `updatedReplicas == replicas`,
  `readyReplicas == replicas`, and the `Progressing` condition reason is
  `"NewReplicaSetAvailable"`.
- `_is_statefulset_ready(status, spec)` returns `True` when `readyReplicas == replicas`,
  `updatedReplicas == replicas`, and `currentRevision == updateRevision`.

Neither function inspects actual pod health. The only pod-level inspection anywhere in the loop is
`_check_pod_conditions`, which flags **only** a hardcoded set of container *waiting* reasons in
`UNRECOVERABLE_POD_CONDITIONS`. Critically, `CrashLoopBackOff`, `ImagePullBackOff`, and
`ErrImagePull` are **commented out** of that set (see the class attribute near the top of
`RolloutMonitor`), and that method never checks the pod `Ready` condition or container
`ready` flags at all — it only looks for terminal provisioning errors.

Why an unhealthy pod slips through to HTTP 200: the controller-level counters
(`readyReplicas`/`availableReplicas`/`updatedReplicas`) are **not** equivalent to "every pod has
all probes passing right now." During and after a rollout these counters can be satisfied by old
ReplicaSet pods, can lag behind live probe state, or can momentarily equal `replicas` while an
individual new pod is Running-but-not-Ready (failing readiness probe) or in CrashLoopBackOff. When
that happens, `_is_rollout_complete` / `_is_statefulset_ready` return `True`, `_check_pod_conditions`
returns `None` (CrashLoopBackOff is not in the active set, and a plain not-Ready pod is not in the
set), and the task completes successfully — so `wait_for_all_rollouts` returns and the route emits
`RolloutAllResponse` (200) even though a pod is unhealthy.

**Needs verification during implementation:** confirm at runtime/in tests that the counters-only
path returns success while a pod is not Ready. The unit test in step 4 reproduces exactly this
(controller status looks complete, one pod not Ready) and must fail before the fix and pass after.

## Fix strategy

Add a pod-level readiness gate that **both** the deployment and statefulset success paths must pass
in addition to their existing controller checks. A workload is "done" only when its controller
status is complete AND every pod belonging to it is actually healthy: the pod's
`status.conditions` entry of `type == "Ready"` has `status == "True"`, and every entry in
`status.containerStatuses` has `ready == true`. Pods must also exist (an empty pod list for a
workload with `replicas > 0` is not "ready"). This preserves the existing timeout/polling structure
(the readiness gate simply makes `_is_*` return not-done, so the loop keeps polling until the pods
become Ready or the shared timeout in `wait_for_all_rollouts` fires and raises
`RolloutTimeoutError`). No API shape, response model, or exception type changes.

Reuse the existing pod-discovery convention already used by `_check_pod_conditions` and
`prometheus_tsdb.py`: `api.get("pods", namespace=namespace, label_selector=f"app={name}")`. Keep
structlog `logger.<event>` style and the existing retry/error-wrapping conventions.

## Constraints (must hold)

- Public API shape of `/rollout/all` and `/rollout/wait`, and the response/exception types
  (`RolloutAllResponse`, `RolloutWaitResponse`, `RolloutTimeoutError`, `RolloutUnrecoverableError`,
  `KubernetesApiError`), MUST NOT change. Only health-determination logic and private helpers change.
- Preserve the `POLL_INTERVAL`/`RETRY_LIMIT`/`RETRY_DELAY` polling and shared-timeout structure.
- `replicas == 0` (scale-to-zero) must still be treated as "done" — the readiness gate only applies
  when `replicas > 0`.
- Match surrounding structlog logging (`logger.info`/`logger.warning` with event-name first arg and
  keyword context) and `KubernetesApiError` wrapping already used in the file.

## Commands

- Install deps: `uv sync` (uses `uv`, Python >= 3.13, per `pyproject.toml`).
- Run tests: `uv run pytest tests/ -q`
- Run the focused new tests: `uv run pytest tests/test_rollout_monitor.py -v`
- Type check (lint): `uv run mypy src/`

> Pre-existing baseline failures (NOT caused by this task — do not attempt to fix them here):
> `tests/test_metrics_config.py::test_gauge_metrics_count`,
> `tests/test_metrics_config.py::test_all_metrics_count`, and four tests in
> `tests/test_rollout_config.py` (count/namespace assertions). These fail on the current `HEAD`
> because config lists drifted from the asserted counts. Your changes must not add new failures;
> the new `test_rollout_monitor.py` tests must pass.

---

- [ ] 1. Add a private pod-readiness helper to `RolloutMonitor`.
      Add `async def _all_pods_ready(self, workload_name: str, namespace: str, expected_replicas: int) -> bool`
      in `src/kasbench_runner/services/rollout_monitor.py`, placed near `_check_pod_conditions` and
      following its exact pod-discovery pattern (`api = await kr8s.asyncio.api()`;
      `api.get("pods", namespace=namespace, label_selector=f"app={workload_name}")`). A pod is ready
      only when its `status.conditions` has an entry with `type == "Ready"` and `status == "True"`
      AND every `status.containerStatuses[*].ready` is `True`. Return `False` if no pods are found
      while `expected_replicas > 0`, or if any pod is not ready. Wrap unexpected errors the same way
      the file already does: on a kr8s/connection error, log `logger.warning("pod_readiness_check_failed", workload=..., namespace=..., error=str(exc))`
      and return `False` (so the poll loop keeps waiting rather than falsely succeeding) — mirror the
      try/except shape of `_check_pod_conditions`. Add an `logger.info("pods_not_ready", ...)`-style
      debug/progress log when returning `False` due to unready pods (optional, match existing event
      naming). Do not change any public method signatures.
      Files: src/kasbench_runner/services/rollout_monitor.py
      Verify: `uv run pytest tests/test_rollout_monitor.py -v` (tests added in step 4) — the readiness
      unit tests for this helper pass. `uv run mypy src/` reports no new errors.

- [ ] 2. Gate deployment success on pod readiness.
      In `wait_for_rollout`, after the existing `_is_rollout_complete(status, deployment.spec)` check
      returns truthy, additionally require `await self._all_pods_ready(deployment_name, namespace, desired_replicas)`
      (where `desired_replicas = deployment.spec.get("replicas", 0) or 0`) before treating the rollout
      as complete and returning `elapsed`. If the controller looks complete but pods are not ready,
      do NOT return — fall through to the existing progress log + `asyncio.sleep(self.POLL_INTERVAL)`
      so the loop keeps polling until pods are Ready or the timeout fires. Keep the existing
      `logger.info("rollout_complete", ...)` only on the fully-ready path. Do not alter the
      `replicas == 0` short-circuit (handled inside `_is_rollout_complete`), and skip the pod gate
      when `desired_replicas == 0`.
      Files: src/kasbench_runner/services/rollout_monitor.py
      Verify: `uv run pytest tests/test_rollout_monitor.py -v` — the deployment "controller complete
      but pod not Ready => times out/raises RolloutTimeoutError" test passes, and the "all pods Ready
      => succeeds" test passes.

- [ ] 3. Gate statefulset success on pod readiness.
      In `wait_for_statefulset`, apply the same gate: after `_is_statefulset_ready(status, spec)`
      returns truthy, additionally require `await self._all_pods_ready(statefulset_name, namespace, desired_replicas)`
      (with `desired_replicas = spec.get("replicas", 0) or 0`) before returning `elapsed` and logging
      `statefulset_rollout_complete`. Otherwise fall through to the existing progress log and
      `asyncio.sleep`. Skip the pod gate when `desired_replicas == 0`.
      Files: src/kasbench_runner/services/rollout_monitor.py
      Verify: `uv run pytest tests/test_rollout_monitor.py -v` — the statefulset "controller ready but
      pod not Ready => does not succeed" test passes.

- [ ] 4. Add focused unit tests for the readiness gate.
      Create `tests/test_rollout_monitor.py` following the mocking style in `tests/test_snapshot_route.py`
      (`unittest.mock.patch` / `AsyncMock`) and the async-auto mode in `pyproject.toml` (no decorator
      needed, but `@pytest.mark.asyncio` is fine). Patch `kr8s.asyncio.api` so both the workload fetch
      (`_fetch_deployment_with_retry` / `_fetch_statefulset_with_retry` via `api.get("deployments"/"statefulsets", ...)`)
      and the pod queries (`api.get("pods", ...)`) are driven by fakes. Use small fake objects exposing
      `.name`, `.status` (dict), and `.spec` (dict) to match how the monitor reads them
      (`deployment.status`, `deployment.spec.get(...)`, `pod.status.get("conditions"|"containerStatuses")`).
      Build an async-iterable helper for `api.get(...)` results since the monitor consumes them with
      `async for`. Use a tiny timeout (e.g. `timeout_seconds=1`) and monkeypatch
      `RolloutMonitor.POLL_INTERVAL = 0` (or patch `asyncio.sleep`) so the timeout path resolves fast.
      Cover at minimum:
        - Deployment NEGATIVE: controller status looks complete (`replicas=1`, `updatedReplicas=1`,
          `readyReplicas=1`, `Progressing`/`NewReplicaSetAvailable`) BUT the single pod has
          `Ready` condition `status: "False"` (or a container with `ready: false`) — assert
          `await monitor.wait_for_all_rollouts([DeploymentSpec("app","ns")], timeout_seconds=1)`
          raises `RolloutTimeoutError` (does NOT return success).
        - Deployment POSITIVE: same controller status AND the pod has `Ready: True` with all
          containers `ready: true` — assert `wait_for_all_rollouts` returns `None` without raising.
        - StatefulSet NEGATIVE: `_is_statefulset_ready` criteria met but the pod is not Ready —
          assert `wait_for_all_rollouts([], timeout_seconds=1, statefulsets=[StatefulSetSpec("sts","ns")])`
          raises `RolloutTimeoutError`.
        - Optional: a direct `_all_pods_ready` unit test for the empty-pod-list-with-replicas>0 => False
          case and the all-ready => True case.
      Import `DeploymentSpec` from `kasbench_runner.services.rollout_monitor` and `StatefulSetSpec`
      from `kasbench_runner.config` (matching current imports).
      Files: tests/test_rollout_monitor.py
      Verify: `uv run pytest tests/test_rollout_monitor.py -v` — all new tests pass. Then
      `uv run pytest tests/ -q` shows no NEW failures beyond the documented pre-existing baseline
      (6 failures in test_metrics_config.py / test_rollout_config.py).

- [ ] 5. Final verification pass.
      Run the full suite and type check; confirm no regressions and the API/response/exception shapes
      are unchanged (no edits to `routes/rollout.py`, `models/responses.py`, or `errors.py`).
      Files: (none — verification only)
      Verify: `uv run pytest tests/ -q` (only the documented pre-existing failures remain, plus the
      new passing rollout-monitor tests) and `uv run mypy src/` (no new errors introduced by the change).

## Notes / assumptions

- Pod ownership is resolved via the `app={name}` label selector, matching the existing
  `_check_pod_conditions` and `prometheus_tsdb.py` convention. If any monitored workload does not use
  the `app=<name>` label, pod discovery would return an empty list and (by design in step 1) the
  gate would hold the rollout as not-ready until timeout. This matches the task's requirement to err
  on the side of NOT reporting success; flag it during implementation if a monitored workload is
  found to use a different label.
- No new Kubernetes API method was added to `kubernetes_manager.py`: that module manages cluster
  installation over SSH/kr8s and does not expose the per-pod query the monitor needs; the monitor
  already queries pods directly via `kr8s.asyncio.api()` in `_check_pod_conditions`, so the readiness
  gate follows that established in-module pattern rather than introducing a cross-module dependency.
  (Task item (d) is conditional — "if pod-level status needs a new API call" — and it does not here.)
