# Implementation Plan: Rollout and Snapshot

## Overview

This plan implements two new services (RolloutMonitor and SnapshotCollector) and three REST API endpoints (`POST /rollout/wait`, `POST /rollout/all`, `POST /snapshot`) for the KASBench Benchmark Runner. Tasks are organized to build foundational error classes and models first, then implement services, then wire up routes, and finally update documentation.

## Tasks

- [x] 1. Add error classes and data models
  - [x] 1.1 Add rollout and snapshot error classes to `src/kasbench_runner/errors.py`
    - Add `RolloutTimeoutError`, `RolloutUnrecoverableError`, `DeploymentNotFoundError`, `KubernetesApiError`, `SnapshotCollectionError`, `InvalidPhaseError`
    - Each error must follow the existing `RunnerError` pattern with `error`, `message`, and `**context`
    - _Requirements: 1.3, 1.4, 1.5, 1.9, 3.14, 3.16_

  - [x] 1.2 Add request and response models
    - Add `RolloutWaitRequest`, `RolloutAllRequest`, `SnapshotRequest` to `src/kasbench_runner/models/requests.py`
    - Add `RolloutWaitResponse`, `RolloutAllResponse`, `SnapshotResponse` to `src/kasbench_runner/models/responses.py`
    - Use Pydantic `Field` with validation constraints (min_length, max_length, ge, le, Literal)
    - Use `populate_by_name: True` and `serialize_by_alias: True` for camelCase serialization
    - _Requirements: 4.1, 4.5, 4.6, 5.1, 5.5, 6.1, 6.5_

  - [x] 1.3 Add `snapshot_in_progress` field to `BenchmarkState` in `src/kasbench_runner/models/state.py`
    - Add `snapshot_in_progress: bool = False` to the `BenchmarkState` dataclass
    - _Requirements: 6.7_

  - [x] 1.4 Add rollout deployment configuration to `src/kasbench_runner/config.py`
    - Add `DEFAULT_ROLLOUT_DEPLOYMENTS` list constant with 24 deployments across namespaces
    - Add `rollout_deployments_json` field to `RunnerConfig` mapped to `ROLLOUT_DEPLOYMENTS` env var
    - Add a `rollout_deployments` property that parses JSON or returns defaults as `DeploymentSpec` objects
    - Import `DeploymentSpec` from the rollout monitor module (or define inline dataclass)
    - _Requirements: 5.2, 5.6_

- [x] 2. Implement RolloutMonitor service
  - [x] 2.1 Create `src/kasbench_runner/services/rollout_monitor.py` with the `RolloutMonitor` class
    - Define `DeploymentSpec` dataclass (frozen, with `name` and `namespace`)
    - Implement `_fetch_deployment_with_retry` with 3 retries and 15s delay for transient errors (connection refused, timeout, HTTP 5xx)
    - Implement `_is_rollout_complete` checking updatedReplicas == replicas, readyReplicas == replicas, and Progressing condition reason "NewReplicaSetAvailable"
    - Implement `_check_unrecoverable_deployment_condition` checking Progressing status "False" with reason "ProgressDeadlineExceeded"
    - Implement `_check_pod_conditions` querying pods owned by the deployment for CrashLoopBackOff, ImagePullBackOff, ErrImagePull, InvalidImageName, CreateContainerConfigError
    - Implement `wait_for_rollout` polling every 10 seconds, re-fetching deployment each iteration, logging progress, raising appropriate errors
    - Raise `DeploymentNotFoundError` if deployment does not exist
    - Use kr8s async API for all Kubernetes interactions
    - Log current rollout progress (ready replicas vs desired) at each poll iteration using structlog
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9_

  - [ ]* 2.2 Write property test for rollout success condition recognition
    - **Property 1: Rollout Success Condition Recognition**
    - Generate random valid deployment statuses with varying replica counts (1-100), verify `_is_rollout_complete` returns True only when all conditions are met
    - **Validates: Requirements 1.2**

  - [ ]* 2.3 Write property test for unrecoverable condition detection
    - **Property 2: Unrecoverable Condition Detection**
    - Generate random condition lists containing/not containing unrecoverable reasons, verify detection function accuracy
    - **Validates: Requirements 1.4, 1.5**

  - [ ]* 2.4 Write property test for timeout error fields
    - **Property 3: Timeout Error Identification**
    - Generate random names/namespaces/elapsed times, construct `RolloutTimeoutError`, verify fields preserved
    - **Validates: Requirements 1.3**

  - [ ]* 2.5 Write property test for transient error retry behavior
    - **Property 4: Transient Error Retry Behavior**
    - Generate random sequences of success/transient-error responses (length 1-5), verify retry behavior matches spec
    - **Validates: Requirements 1.6**

  - [x] 2.6 Implement `wait_for_all_rollouts` in `RolloutMonitor`
    - Use `asyncio.wait` with `return_when=FIRST_EXCEPTION` and shared timeout
    - Cancel all pending tasks on first failure
    - Return successfully immediately for empty deployment list
    - Collect incomplete deployments on timeout and include in error
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [ ]* 2.7 Write property test for batch cancellation on failure
    - **Property 6: Batch Cancellation on Failure**
    - Verify that when one deployment fails, all remaining are cancelled and error identifies the failing deployment
    - **Validates: Requirements 2.4**

  - [ ]* 2.8 Write property test for batch timeout incomplete list
    - **Property 7: Batch Timeout Lists Incomplete Deployments**
    - Generate random batches with random subsets completing, verify error lists exactly the incomplete ones
    - **Validates: Requirements 2.5**

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement SnapshotCollector service
  - [x] 4.1 Create `src/kasbench_runner/services/snapshot_collector.py` with the `SnapshotCollector` class
    - Define `SnapshotResult` dataclass (frozen, with `files_uploaded: int` and `s3_prefix: str`)
    - Accept `S3Client` in constructor
    - Implement `_prepend_header` to prepend ISO 8601 UTC timestamp and resource label to content
    - Implement `_compute_sha256sums` generating SHA-256 hash for every collected file
    - Implement `collect_snapshot` as the main orchestration method
    - Validate phase is "pre" or "post", raising `InvalidPhaseError` otherwise
    - _Requirements: 3.1, 3.9, 3.10, 3.11, 3.12, 3.16_

  - [x] 4.2 Implement metadata collection in `SnapshotCollector`
    - Implement `_collect_metadata` gathering: date.txt (UTC timestamp), kubectl-version.yaml (server version info), context.txt (current context), cluster-info.txt (cluster endpoint), api-resources.txt (available API resources)
    - Use kr8s async API calls
    - Raise `SnapshotCollectionError` on failure
    - _Requirements: 3.2, 3.11, 3.14_

  - [x] 4.3 Implement resource collection in `SnapshotCollector`
    - Implement `_collect_resources` gathering all required resource manifests: nodes, pods, pods-wide, workloads (deployments, statefulsets, daemonsets, replicasets, jobs, cronjobs), autoscaling (HPAs), network (services, endpoints, endpointslices, ingresses, networkpolicies), storage (PVCs, PVs, storageclasses, volumeattachments), policies (resourcequotas, limitranges, poddisruptionbudgets), configmaps, webhooks
    - Serialize to YAML format where applicable, text for pods-wide
    - Raise `SnapshotCollectionError` on failure for required resources
    - _Requirements: 3.3, 3.11, 3.14_

  - [x] 4.4 Implement descriptions, events, raw endpoints, and optional CRDs collection
    - Implement `_collect_descriptions` for nodes and pods detailed output
    - Implement `_collect_events` for all events and warning-only events
    - Implement `_collect_raw_endpoints` for /readyz, /livez, node-metrics, pod-metrics
    - Implement `_collect_optional_crds` for VPA, KEDA, Gateway API resources — log warning and continue on failure
    - _Requirements: 3.4, 3.5, 3.6, 3.7, 3.8, 3.14, 3.15_

  - [x] 4.5 Implement S3 upload logic in `collect_snapshot`
    - Upload all files to S3 under `{run_id}/{trial_id}/snapshot/{phase}/` prefix
    - Upload SHA256SUMS last as completeness indicator
    - Raise `S3OperationError` on failure for required files
    - Log warning and continue for optional CRD upload failures
    - Use existing `S3Client.upload_bytes` method
    - _Requirements: 3.1, 3.12, 3.13, 3.15_

  - [ ]* 4.6 Write property test for S3 path construction
    - **Property 8: S3 Path Construction**
    - Generate random identifiers (alphanumeric + hyphens, 1-50 chars) and phases, verify path format
    - **Validates: Requirements 3.1**

  - [ ]* 4.7 Write property test for file header format
    - **Property 9: File Header Format**
    - Generate random content bytes and label strings, verify header structure with ISO 8601 regex
    - **Validates: Requirements 3.9**

  - [ ]* 4.8 Write property test for SHA256SUMS integrity
    - **Property 10: SHA256SUMS Integrity**
    - Generate random dicts of {filename: bytes}, compute SHA256SUMS, verify each hash matches hashlib.sha256()
    - **Validates: Requirements 3.10**

  - [ ]* 4.9 Write property test for phase validation
    - **Property 13: Phase Validation Rejection**
    - Generate random strings (excluding "pre"/"post"), verify rejection with `InvalidPhaseError`
    - **Validates: Requirements 3.16, 6.5**

  - [ ]* 4.10 Write property test for optional resource graceful degradation
    - **Property 11: Optional Resource Graceful Degradation**
    - Generate random subsets of optional resources to fail, verify snapshot still completes
    - **Validates: Requirements 3.7, 3.15**

- [x] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Implement REST API routes
  - [x] 6.1 Create `src/kasbench_runner/routes/rollout.py` with `/rollout/wait` and `/rollout/all` endpoints
    - Create `APIRouter` with rollout endpoints
    - `POST /rollout/wait`: validate request via `RolloutWaitRequest`, instantiate `RolloutMonitor`, call `wait_for_rollout`, return `RolloutWaitResponse` with deployment name and elapsed time
    - Handle `DeploymentNotFoundError` → 404, `RolloutTimeoutError` → 500, `RolloutUnrecoverableError` → 500, `KubernetesApiError` → 500
    - `POST /rollout/all`: validate `RolloutAllRequest`, load deployment list from config, call `wait_for_all_rollouts`, return `RolloutAllResponse` with count and elapsed time
    - Handle timeout and unrecoverable errors → 500 with deployment details
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

  - [x] 6.2 Create `src/kasbench_runner/routes/snapshot.py` with `/snapshot` endpoint
    - Create `APIRouter` with snapshot endpoint
    - `POST /snapshot`: validate `SnapshotRequest`, check benchmark is initialized (else 409), check `snapshot_in_progress` (else 409), set flag, instantiate `SnapshotCollector` with S3Client, call `collect_snapshot`, reset flag in `finally` block, return `SnapshotResponse`
    - Handle `InvalidPhaseError` → 422, `SnapshotCollectionError` → 500, `S3OperationError` → 500
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_

  - [x] 6.3 Register new routers in `src/kasbench_runner/app.py`
    - Import `rollout` and `snapshot` route modules
    - Add `app.include_router(rollout.router)` and `app.include_router(snapshot.router)`
    - _Requirements: 4.1, 5.1, 6.1_

  - [ ]* 6.4 Write unit tests for rollout endpoints
    - Test successful rollout returns 200 with correct fields
    - Test ProgressDeadlineExceeded returns 500 with "rollout_unrecoverable"
    - Test deployment not found returns 404
    - Test K8s API unreachable returns 500 with "kubernetes_api_error"
    - Test invalid timeout returns 422
    - Test empty deployment name returns 422
    - Test all rollouts succeed returns 200 with count
    - Test empty deployment list returns immediately for wait_for_all_rollouts
    - _Requirements: 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 5.3, 5.4, 5.5, 2.7_

  - [ ]* 6.5 Write unit tests for snapshot endpoint
    - Test snapshot success returns 200 with phase, count, prefix
    - Test S3 failure returns 500 with "s3_operation_failed"
    - Test K8s failure returns 500 with "kubernetes_error"
    - Test invalid phase returns 422
    - Test not-initialized state returns 409
    - Test concurrent snapshot returns 409
    - _Requirements: 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_

  - [ ]* 6.6 Write property test for endpoint input validation
    - **Property 14: Endpoint Input Validation**
    - Generate invalid timeout values and empty names, verify 422 responses with appropriate messages
    - **Validates: Requirements 4.5, 4.6, 5.5**

- [x] 7. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Update README.md with rollout and snapshot feature documentation
  - [x] 8.1 Update `README.md` with new endpoints, services, configuration, and project structure
    - Add `ROLLOUT_DEPLOYMENTS` environment variable to the Configuration table
    - Add `POST /rollout/wait` endpoint documentation with request/response schema and error codes
    - Add `POST /rollout/all` endpoint documentation with request/response schema and error codes
    - Add `POST /snapshot` endpoint documentation with request/response schema and error codes
    - Add usage examples (curl commands) for all three new endpoints
    - Update the Project Structure section to include `rollout_monitor.py`, `snapshot_collector.py`, `routes/rollout.py`, `routes/snapshot.py`
    - Update the Components list in Architecture to mention RolloutMonitor and SnapshotCollector
    - Update the Full Lifecycle Script to include snapshot and rollout steps
    - _Requirements: all_

- [x] 9. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The `DeploymentSpec` dataclass is defined in `rollout_monitor.py` and imported where needed (config.py, routes)
- The `SnapshotResult` dataclass is defined in `snapshot_collector.py`
- All services use async/await patterns consistent with the existing codebase
- All Kubernetes interactions use kr8s async API
- All S3 operations use the existing `S3Client` service

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["1.4", "2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.4", "2.5", "2.6"] },
    { "id": 3, "tasks": ["2.7", "2.8", "4.1"] },
    { "id": 4, "tasks": ["4.2", "4.3", "4.4"] },
    { "id": 5, "tasks": ["4.5", "4.6", "4.7", "4.8", "4.9", "4.10"] },
    { "id": 6, "tasks": ["6.1", "6.2"] },
    { "id": 7, "tasks": ["6.3", "6.4", "6.5", "6.6"] },
    { "id": 8, "tasks": ["8.1"] }
  ]
}
```
