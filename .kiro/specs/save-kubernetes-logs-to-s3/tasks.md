# Implementation Plan: Save Kubernetes Logs to S3

## Overview

Implement a `POST /logs/{namespace}/export` endpoint that collects Kubernetes pod logs from all pods in a given namespace and uploads them to S3. Follows the existing route/service separation pattern with best-effort error handling matching `metrics.py` and `snapshot_collector.py`.

## Tasks

- [x] 1. Create the LogCollector service
  - [x] 1.1 Create `src/kasbench_runner/services/log_collector.py` with `LogCollector` class, `LogCollectionResult` and `LogEntry` dataclasses
    - Define `LogCollectionResult` (frozen dataclass: `files_exported: int`, `s3_prefix: str`, `errors: list[dict]`)
    - Define `LogEntry` (frozen dataclass: `pod_name: str`, `container_name: str`, `filename: str`, `content: bytes`)
    - `LogCollector.__init__` accepts `s3_client: S3Client`
    - Implement `_discover_pods(namespace)` — use `kr8s.asyncio.api()` to query all pods in the namespace; raise `SnapshotCollectionError` if Kubernetes API is unreachable
    - Implement `_determine_filename(pod_name, container_name, container_count)` — returns `{pod_name}.log` for single-container pods, `{pod_name}-{container_name}.log` for multi-container pods
    - Implement `_collect_container_log(pod, container_name)` — fetches logs via kr8s, returns `bytes | None` (None if unavailable), catches all exceptions
    - Implement `collect_and_upload(namespace, run_identifier, trial_identifier)` — orchestrates discovery, collection, and upload with best-effort error recording; uses `S3Client.upload_bytes()` with `content_type="text/plain"`
    - Use `structlog.get_logger()` for logging throughout
    - _Requirements: 3.1, 3.2, 3.3, 4.1, 4.2, 5.1, 5.2, 6.1, 6.2, 8.1, 8.2, 8.3_

  - [x]* 1.2 Write property test for filename determination logic
    - **Property 4: File naming convention**
    - **Validates: Requirements 5.1, 5.2**

  - [x]* 1.3 Write property test for S3 key path construction
    - **Property 5: S3 key path construction**
    - **Validates: Requirements 6.1**

  - [x]* 1.4 Write unit tests for LogCollector
    - Test `_determine_filename` with single and multi-container pods
    - Test `collect_and_upload` handles empty namespace (0 pods → 0 files_exported)
    - Test best-effort: one container failure doesn't block others
    - _Requirements: 5.1, 5.2, 8.1, 8.2, 8.3_

- [x] 2. Create the logs route
  - [x] 2.1 Create `src/kasbench_runner/routes/logs.py` with `POST /logs/{namespace}/export` endpoint
    - Create `APIRouter` and define `post_logs_export(namespace: str, request: Request)`
    - Access `BenchmarkState` via `request.app.state.benchmark_state`
    - State guard: return HTTP 409 with `error="not_initialized"` when `state.status == BenchmarkStatus.NOT_INITIALIZED`
    - Instantiate `S3Client(bucket=config.s3_bucket)` and `LogCollector(s3_client=s3_client)`
    - Call `collector.collect_and_upload(namespace, config.run_identifier, config.trial_identifier)`
    - Catch `SnapshotCollectionError` → return HTTP 500 with `error="kubernetes_error"`
    - Build JSON response: 200 if no errors, 207 if partial errors (include `message`, `filesExported`, `s3Prefix`, `errors`, `timestamp`)
    - _Requirements: 1.1, 1.2, 2.1, 2.2, 7.1, 7.2, 8.4_

  - [x]* 2.2 Write property test for state guard logic
    - **Property 1: State guard accepts all initialized states**
    - **Validates: Requirements 2.2**

  - [x]* 2.3 Write property test for response status code correctness
    - **Property 6: Response status code correctness**
    - **Validates: Requirements 7.1, 7.2**

- [x] 3. Register the router and wire up
  - [x] 3.1 Register `logs.router` in `src/kasbench_runner/app.py`
    - Add import: `from kasbench_runner.routes import logs`
    - Add `app.include_router(logs.router)` alongside existing routers
    - _Requirements: 1.1_

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Update README documentation
  - [x] 5.1 Add API reference for `POST /logs/{namespace}/export` to the README
    - Document endpoint path, request parameters (namespace path param)
    - Document success response format (200 with `message`, `filesExported`, `s3Prefix`, `timestamp`)
    - Document partial success (207 with errors array)
    - Document error responses (409 not_initialized, 500 kubernetes_error)
    - Document allowed states (any status except not-initialized)
    - Include a curl usage example
    - _Requirements: 9.1, 9.2_

- [x] 6. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- The LogCollector follows the same patterns as `SnapshotCollector` (kr8s for K8s API, S3Client for uploads, SnapshotCollectionError for fatal K8s failures)
- Best-effort error handling mirrors `metrics.py`: individual failures are recorded but don't abort the entire operation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "1.4", "2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "3.1"] },
    { "id": 3, "tasks": ["5.1"] }
  ]
}
```
