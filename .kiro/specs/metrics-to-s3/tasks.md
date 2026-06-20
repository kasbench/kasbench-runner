# Implementation Plan: Metrics to S3

## Overview

Replace the existing GET /metrics placeholder endpoint with a POST /metrics endpoint that orchestrates Prometheus range query execution and S3 upload. Implementation proceeds bottom-up: data models and configuration first, then service layer (Prometheus client, S3 extensions), then the route handler, and finally integration wiring and README updates.

## Tasks

- [ ] 1. Define request/response models and metrics configuration
  - [ ] 1.1 Add MetricsRequest model to models/requests.py
    - Add `MetricsRequest` Pydantic model with fields: `overwrite` (bool, default False), `interval` (str, default "60s"), `step` (str, default "15s")
    - Set `model_config = {"extra": "ignore"}` to silently drop unrecognized fields
    - _Requirements: 1.1, 1.6, 1.7, 1.8_

  - [ ] 1.2 Add MetricsResponse and MetricsErrorEntry models to models/responses.py
    - Add `MetricsErrorEntry` with fields: `metric_name` (alias "metricName"), `phase` (str: "query" or "upload"), `error` (str)
    - Add `MetricsResponse` with fields: `message`, `metrics_uploaded` (alias "metricsUploaded"), `metrics_total` (alias "metricsTotal"), `s3_prefix` (alias "s3Prefix"), `errors` (list[MetricsErrorEntry]), `timestamp` (datetime)
    - Both models use `populate_by_name = True, serialize_by_alias = True`
    - _Requirements: 8.1, 8.2_

  - [ ] 1.3 Create services/metrics_config.py with all 54 metric definitions
    - Define `MetricDefinition` frozen dataclass with fields: `metric`, `description`, `query`, `name`, `metric_type`
    - Populate `COUNTER_METRICS` list with all 36 counter entries from requirement_002.md
    - Populate `GAUGE_METRICS` list with all 18 gauge entries from requirement_002.md
    - Define `ALL_METRICS = COUNTER_METRICS + GAUGE_METRICS`
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

- [ ] 2. Implement Prometheus client service
  - [ ] 2.1 Create services/prometheus_client.py with PrometheusClient class
    - Define `QueryResult` dataclass (metric_name, success, response_json, error_message)
    - Define `QuerySummary` dataclass with `results` list, `successful`/`failed`/`all_succeeded` properties
    - Implement `PrometheusClient.__init__` accepting `control_plane_node`, `connect_timeout` (default 10.0), `read_timeout` (default 30.0)
    - Implement `build_url()` returning `http://{control_plane_node}:80/api/v1/query_range`
    - Implement `substitute_interval(query, interval)`: if interval is empty/blank use "60s"; replace all `__INTERVAL__` occurrences with interval value; return unchanged if no placeholder
    - Implement `execute_all(metrics, start_ts, end_ts, step, interval)`: iterate ALL_METRICS sequentially, substitute interval, execute range query via httpx, record success/failure in QueryResult, continue on error, return QuerySummary
    - _Requirements: 4.1, 4.2, 4.3, 5.1, 5.2, 5.3, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [ ]* 2.2 Write property test for interval substitution (Property 1)
    - **Property 1: Interval substitution round-trip preserves non-placeholder queries**
    - Use Hypothesis to generate arbitrary query strings without `__INTERVAL__`; assert substitute_interval returns input unchanged
    - **Validates: Requirements 5.2**

  - [ ]* 2.3 Write property test for interval substitution (Property 2)
    - **Property 2: Interval substitution replaces all occurrences**
    - Use Hypothesis to generate query strings containing `__INTERVAL__` and non-empty interval values; assert no `__INTERVAL__` remains and interval value appears
    - **Validates: Requirements 5.1**

  - [ ]* 2.4 Write property test for interval substitution (Property 3)
    - **Property 3: Empty/blank interval defaults to "60s"**
    - Use Hypothesis to generate query strings with `__INTERVAL__` and empty/whitespace interval values; assert "60s" is substituted
    - **Validates: Requirements 5.3**

- [ ] 3. Extend S3 client with upload_json and check_objects_exist
  - [ ] 3.1 Add upload_json method to S3Client in services/s3_client.py
    - Implement `upload_json(key: str, data: bytes)` that calls `put_object` with `ContentType="application/json"`
    - Wrap errors in `S3OperationError`
    - _Requirements: 7.2, 7.3, 7.4_

  - [ ] 3.2 Add check_objects_exist method to S3Client in services/s3_client.py
    - Implement `check_objects_exist(keys: list[str]) -> list[str]` that uses `head_object` per key
    - Return list of keys that exist; raise `S3OperationError` if head_object fails for non-404 reasons
    - _Requirements: 3.1, 3.5_

  - [ ]* 3.3 Write unit tests for upload_json and check_objects_exist
    - Use moto to mock S3
    - Test upload_json writes correct content type and body
    - Test check_objects_exist returns existing keys and empty list for non-existing
    - Test S3OperationError raised on non-404 failures
    - _Requirements: 3.1, 3.5, 7.2, 7.3, 7.4_

- [ ] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Implement POST /metrics route handler
  - [ ] 5.1 Replace routes/metrics.py with POST /metrics handler
    - Remove all existing GET /metrics code (including pandas/parquet imports and helpers)
    - Implement `post_metrics(request, body: MetricsRequest = MetricsRequest())` as POST handler
    - Step 1: State guard — reject if status not in (SUCCESS, FAILED, ABORTED) with HTTP 409
    - Step 2: Validate time bounds — return HTTP 500 "missing_time_bounds" if start_time or end_time is None
    - Step 3: Overwrite protection — if `overwrite=false`, call `check_objects_exist` for all 54 keys; return HTTP 409 "metrics_already_exist" if any found
    - Step 4: Execute Prometheus queries via `PrometheusClient.execute_all`
    - Step 5: Upload successful results to S3 via `S3Client.upload_json`; accumulate upload errors
    - Step 6: Return HTTP 200 (all OK) or HTTP 207 (partial failures) with MetricsResponse-shaped JSON
    - Construct S3 keys as `{run_identifier}/{trial_identifier}/metrics/{name}`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 6.3, 7.1, 8.1, 8.2, 8.3, 8.4, 11.1, 11.2, 11.3, 11.4, 11.5_

  - [ ]* 5.2 Write property test for state guard (Property 7)
    - **Property 7: State guard rejects non-terminal statuses**
    - Use Hypothesis to generate status values from {NOT_INITIALIZED, NOT_STARTED, RUNNING}; assert handler returns 409 without calling Prometheus or S3
    - **Validates: Requirements 2.1, 2.2, 2.3**

  - [ ]* 5.3 Write property test for S3 key construction (Property 4)
    - **Property 4: S3 key construction format invariant**
    - Use Hypothesis to generate valid run_identifier, trial_identifier, and metric name strings; assert key matches `{run}/{trial}/metrics/{name}` with no leading/double/trailing slashes
    - **Validates: Requirements 7.1**

  - [ ]* 5.4 Write property test for overwrite protection (Property 5)
    - **Property 5: Overwrite-false prevents any writes when existing keys found**
    - Use Hypothesis to generate a non-empty subset of metric keys that "exist"; mock S3Client; assert zero put_object calls when overwrite=false
    - **Validates: Requirements 3.1, 3.2**

  - [ ]* 5.5 Write property test for error accumulation (Property 6)
    - **Property 6: Error accumulation preserves all failures**
    - Use Hypothesis to generate N metrics with K random failures; assert returned error list length == K with correct metric names and phases
    - **Validates: Requirements 6.4, 6.5, 6.6, 8.2, 8.3**

- [ ] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Integration tests and README update
  - [ ] 7.1 Create tests/conftest.py with shared fixtures
    - Create fixtures for mock BenchmarkState (with start_time, end_time, config)
    - Create fixture for FastAPI test client with mocked app state
    - Create fixtures for moto S3 mock and respx Prometheus mock
    - _Requirements: 2.4, 6.2, 7.1_

  - [ ] 7.2 Create tests/test_metrics_config.py to validate configuration structure
    - Assert COUNTER_METRICS has 36 entries
    - Assert GAUGE_METRICS has 18 entries
    - Assert ALL_METRICS has 54 entries
    - Assert all entries have non-empty metric, description, query, name, metric_type fields
    - Assert all counter queries contain `__INTERVAL__`
    - Assert no gauge queries contain `__INTERVAL__`
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

  - [ ]* 7.3 Create tests/test_metrics_route.py with integration tests
    - Test full success flow: mock Prometheus returning 200 for all 54 queries, assert S3 receives 54 objects, assert HTTP 200 response
    - Test partial failure: mock some queries returning 500, assert HTTP 207 with correct error list
    - Test state guard: call with status=RUNNING, assert 409
    - Test overwrite protection: pre-create S3 objects, assert 409 with existing names
    - Test missing time bounds: set start_time=None, assert 500
    - Use respx for Prometheus HTTP mocking, moto for S3 mocking
    - _Requirements: 2.1, 3.1, 3.2, 6.4, 8.1, 8.2, 11.4, 11.5_

  - [ ] 7.4 Update README.md to document POST /metrics endpoint
    - Replace the existing GET /metrics entry in the API Reference section with POST /metrics
    - Document optional request body fields: `overwrite` (bool, default false), `interval` (string, default "60s"), `step` (string, default "15s")
    - Document success response format (200) with fields: message, metricsUploaded, metricsTotal, s3Prefix, timestamp
    - Document error responses: 409 for invalid state and overwrite conflict, 207 for partial failures, 500 for missing time bounds
    - Add curl examples showing: default invocation, custom parameters, and error case
    - _Requirements: 10.1, 10.2, 10.3_

- [ ] 8. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document using Hypothesis
- Unit tests validate specific examples and edge cases using pytest + respx + moto
- The metrics_config.py file will be large (~54 dataclass instances) but is pure data, easy to maintain
- The existing routes/metrics.py is completely replaced — all old code (pandas, parquet, GET handler) is removed

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["2.1", "3.1", "3.2"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.4", "3.3"] },
    { "id": 3, "tasks": ["5.1"] },
    { "id": 4, "tasks": ["5.2", "5.3", "5.4", "5.5", "7.1"] },
    { "id": 5, "tasks": ["7.2", "7.3", "7.4"] }
  ]
}
```
