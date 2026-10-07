# Pod-readiness gate for rollout success determination (v2)

`wait_for_all_rollouts` (via `wait_for_rollout` / `wait_for_statefulset`) previously declared a rollout successful based only on the controller's replica counters — `_is_rollout_complete` for Deployments and `_is_statefulset_ready` for StatefulSets. Those counters can be satisfied while an individual pod is Running-but-not-Ready (failing readiness probe) or in CrashLoopBackOff (which is intentionally commented out of `UNRECOVERABLE_POD_CONDITIONS`), so an unhealthy pod could reach HTTP 200. The fix adds a private `_all_pods_ready` helper that queries the workload's pods (`app={name}` label selector) and requires each pod's `Ready` status condition to be `True` and every `containerStatuses[*].ready` to be `True`. Both success paths now AND this gate with the existing controller check (skipping it only when `desired_replicas == 0`); when the gate fails the loop keeps polling until the shared timeout fires `RolloutTimeoutError`. No route, response-model, or exception-type changes.

Watch for: nothing blocking. The one blocking finding from v1 — missing full-suite and lint evidence — is now resolved: `verification.md` records the exact `pytest tests/`, `ruff check`, and a stash-based baseline confirmation (confirmed by reading the note). The non-blocking init-container point from v1 was addressed with correct reasoning (confirmed).

**Verdict**: APPROVED

## High-level view

The gate is implemented symmetrically for Deployments and StatefulSets: each success branch keeps its original controller check and conjoins `desired_replicas == 0 or await self._all_pods_ready(...)`. Short-circuit evaluation means the pod query only runs once the controller already looks complete, and the `== 0` guard preserves the scale-to-zero "done" semantics the controller checks already encode.

`_all_pods_ready` mirrors the existing `_check_pod_conditions` discovery pattern (`kr8s.asyncio.api()` + `api.get("pods", label_selector=f"app={name}")`) and fails closed: an empty pod list with `expected_replicas > 0`, any not-Ready pod, or any exception from the pod query all return `False`, so the poll loop waits rather than falsely succeeding.

No new method was added to `kubernetes_manager.py`. Task item (d) is conditional on a new pod-status call being routed through the manager; the gate instead follows the in-module convention `_check_pod_conditions` already set, so there is no `KubernetesApiError` wrapping to review.

Both prior-pass findings are now closed. The full suite shows 42 passed / 6 failed, and the coder's stash-based baseline run proves those 6 failures (`test_metrics_config.py`, `test_rollout_config.py` count/namespace drifts) exist on clean HEAD independent of this change and in files this diff does not touch.

<details>
<summary>Issues (0)</summary>

No blocking or new findings. Both v1 findings are resolved:

1. **Missing full-suite / lint verification evidence** (v1, blocking) — RESOLVED. `verification.md` records `uv run pytest tests/ -q` (42 passed, 6 pre-existing failures), `uv run ruff check` (clean, exit 0), and a `git stash`-based baseline run confirming the 6 failures predate the change.
2. **Container-only readiness, init containers not gated** (v1, non-blocking) — RESOLVED with reasoning. A pod blocked in an init container has its pod-level `Ready` condition set to `False` by the kubelet, which `_all_pods_ready` already rejects via its first per-pod gate; an `initContainerStatuses` loop would be redundant.

</details>

<details>
<summary>Details</summary>

### v1 blocking finding now backed by recorded evidence

v1 held the change at NEEDS_CHANGES solely because no recorded command output showed the full suite and linter had been run. `verification.md` now supplies it: `uv run pytest tests/test_rollout_monitor.py -v` (5/5 passed), `uv run ruff check src/.../rollout_monitor.py tests/test_rollout_monitor.py` (exit 0, no findings), and `uv run pytest tests/ -q` (6 failed, 42 passed). The six failures are enumerated and shown to be count/namespace assertion drifts in `test_metrics_config.py` and `test_rollout_config.py` — files this diff does not touch. The coder then stashed only `rollout_monitor.py` and re-ran the two affected files on clean HEAD, reproducing the identical 6 failures, which establishes them as pre-existing baseline rather than regressions. The note also records that `mypy` is not installed or configured, so ruff is correctly treated as the project's active linter. Per the task instruction not to re-run what the coder just ran, this evidence is accepted as-is; no spot-check was needed because the note leaves no specific articulable doubt.

### Fail-closed semantics in `_all_pods_ready`

The helper returns `False` on three distinct failure modes: the pod query raising (logged `pod_readiness_check_failed`, matching the `_check_pod_conditions` warning shape), an empty pod list while `expected_replicas > 0` (logged `pods_not_ready` / `no_pods_found`), and any pod whose `Ready` condition is absent or not `"True"` or whose containers report `ready != True` (logged `pods_not_ready` with a `reason`). Every path that cannot positively confirm health holds the rollout as not-done. The gate relies on pods carrying the `app=<workload-name>` label, the same assumption `_check_pod_conditions` and `prometheus_tsdb.py` already make; a workload using a different label would return an empty pod query and the gate would hold until timeout — again erring toward not-success.

### Error-raising and timeout structure preserved

The polling loops, `POLL_INTERVAL`/`RETRY_LIMIT`/`RETRY_DELAY` constants, retry/`KubernetesApiError` wrapping in the fetch helpers, and the `wait_for_all_rollouts` fan-out that raises `RolloutTimeoutError` on remaining pending tasks are untouched. A gate failure does not raise on its own; it falls through to the existing progress log and `asyncio.sleep(POLL_INTERVAL)`, so the shared timeout in `wait_for_all_rollouts` remains the single source of `RolloutTimeoutError`. `RolloutUnrecoverableError` continues to come only from `_check_unrecoverable_deployment_condition` and `_check_pod_conditions`; the fix adds no new unrecoverable path, so a CrashLoopBackOff pod causes a timeout rather than an unrecoverable error — acceptable under the requirement. The route still returns `RolloutAllResponse` and catches the same `(RolloutTimeoutError, RolloutUnrecoverableError, KubernetesApiError)` triple, so the public API shape is unchanged.

### Test coverage

`tests/test_rollout_monitor.py` drives both the workload fetch and the pod query through a fake `kr8s.asyncio.api` whose `.get` dispatches on resource kind, with async-iterable results matching how the monitor consumes them. The negative tests genuinely reproduce the bug: the fake deployment/statefulset status satisfies the controller check, so pre-fix the first poll would have returned success; post-fix the not-Ready pod forces the loop to the timeout and `RolloutTimeoutError`. The positive case asserts the all-Ready path returns `None`, and two direct `_all_pods_ready` unit cases cover empty-with-replicas (`False`) and all-healthy (`True`).

Not tested: no positive StatefulSet success test (the Deployment positive path exercises the same `_all_pods_ready` branch, so this is a minor gap), and the `container_not_ready` branch is not exercised separately from `ready_condition_not_true` (low risk — both return `False` identically). Neither gap is blocking.

</details>

<details>
<summary>File map</summary>

- `src/kasbench_runner/services/rollout_monitor.py` — added `_all_pods_ready` helper; gated both the Deployment and StatefulSet success branches on it; moved the `desired_replicas` assignment above the success check.
- `tests/test_rollout_monitor.py` (new, untracked) — five async tests covering the readiness gate and the reproduced bug.
- `.agents/tasks/verification.md` (new) — recorded command output resolving the v1 blocking finding.

Full diff: `git diff -- src/kasbench_runner/services/rollout_monitor.py` plus the untracked `tests/test_rollout_monitor.py`.

</details>
