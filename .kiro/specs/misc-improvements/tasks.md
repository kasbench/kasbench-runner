# Implementation Plan: misc-improvements

## Overview

This plan implements miscellaneous improvements to the KASBench Runner: endpoint rename, Kafka metrics, configurable Prometheus port, TSDB snapshot export, output/db/metadata export to S3, namespace shutdown, and README updates. Each task builds incrementally, wiring new components into the existing FastAPI app.

## Tasks

- [x] 1. Update models, services, and metrics config
  - [x] 1.1 Add Kafka counter and gauge metrics to metrics_config.py
    - Append 7 Kafka consumer counter MetricDefinition entries to COUNTER_METRICS
    - Append 9 Kafka gauge MetricDefinition entries to GAUGE_METRICS
    - ALL_METRICS automatically includes them via existing concatenation
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11_

  - [x] 1.2 Update request models in models/requests.py
    - Rename `MetricsRequest` to `MetricsExportRequest` and add `prometheus_port: int = Field(default=31565, alias="prometheusPort", ge=1, le=65535)`
    - Add `TsdbExportRequest` model with `prometheus_port: int = Field(default=31565, alias="prometheusPort", ge=1, le=65535)` and `model_config = {"extra": "ignore", "populate_by_name": True}`
    - _Requirements: 4.1, 4.2, 4.3, 5.4, 5.5_

  - [x] 1.3 Update PrometheusClient.build_url() to accept port parameter
    - Change signature to `def build_url(self, port: int = 31565) -> str`
    - Use the port parameter in the URL: `http://{self._control_plane_node}:{port}/api/v1/query_range`
    - Update `execute_all` to accept and pass port parameter to `build_url`
    - _Requirements: 4.1, 4.2_

  - [x] 1.4 Add upload_bytes and upload_directory methods to S3Client
    - Add `async def upload_bytes(self, key: str, data: bytes, content_type: str) -> None` for arbitrary byte uploads
    - Add `async def upload_directory(self, prefix: str, local_dir: str) -> list[str]` that walks the local directory, uploads each file, and returns the list of S3 keys
    - Both raise `S3OperationError` on failure
    - _Requirements: 5.3, 6.1, 7.1_

  - [x] 1.5 Add response models to models/responses.py
    - Add `ExportResultEntry` model (role, status, s3_key, error)
    - Add `ExportResponse` model (message, files_exported, results, s3_prefix, s3_key, s3_path, timestamp)
    - Add `NamespaceResult` model (namespace, status, error)
    - Add `ShutdownResponse` model (results, timestamp)
    - _Requirements: 5.10, 6.4, 7.4, 8.1, 9.4_

- [x] 2. Rename metrics endpoint and add configurable port
  - [x] 2.1 Rename POST /metrics to POST /metrics/export in routes/metrics.py
    - Change `@router.post("/metrics")` to `@router.post("/metrics/export")`
    - Update function to use `MetricsExportRequest` instead of `MetricsRequest`
    - Pass `body.prometheus_port` to `prometheus_client.execute_all()`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 4.1, 4.2_

  - [ ]* 2.2 Write property test for port-based URL construction
    - **Property 1: Port-based URL construction**
    - Use Hypothesis to generate valid port integers [1, 65535] and non-empty hostnames
    - Verify `PrometheusClient.build_url(port)` produces `http://{hostname}:{port}/api/v1/query_range`
    - **Validates: Requirements 4.1**

  - [ ]* 2.3 Write property test for port validation boundaries
    - **Property 2: Port validation boundaries**
    - Use Hypothesis to generate integers inside and outside [1, 65535]
    - Verify MetricsExportRequest accepts valid ports and rejects invalid ones
    - **Validates: Requirements 4.3, 4.4**

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement output export endpoint
  - [x] 4.1 Add POST /output/export and POST /output/export/{role} to routes/output.py
    - Add state guard: reject if NOT_INITIALIZED (HTTP 409)
    - For single role: validate role, fetch from LG via GET http://{role}:8080/download-output, upload bytes to S3 at `{s3Bucket}/{runIdentifier}/{trialIdentifier}/output/{role}-output.txt`
    - For all roles: iterate all 5 roles, collect per-role results, return 200 (all success) or 207 (partial)
    - Handle connection failures (502), S3 failures (500), invalid role (400)
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9_

  - [ ]* 4.2 Write property test for invalid role rejection (output)
    - **Property 3: Invalid role rejection**
    - Use Hypothesis to generate arbitrary strings that are not valid roles
    - Verify /output/export/{role} returns HTTP 400 with invalid value and valid roles list
    - **Validates: Requirements 6.5**

  - [ ]* 4.3 Write property test for partial role failure (output)
    - **Property 4: Partial role failure yields correct 207 response**
    - Use Hypothesis to generate non-empty subsets of roles to fail
    - Verify response is 207 with correct per-role statuses, no omissions or duplicates
    - **Validates: Requirements 6.9**

- [x] 5. Implement database export endpoint
  - [x] 5.1 Add POST /db/export and POST /db/export/{role} to routes/db.py
    - Add state guard: reject if NOT_INITIALIZED (HTTP 409)
    - For single role: validate role, fetch from LG via GET http://{role}:8080/download-db, upload bytes to S3 at `{s3Bucket}/{runIdentifier}/{trialIdentifier}/db/{role}.db`
    - For all roles: iterate all 5 roles, collect per-role results, return 200 (all success)
    - Handle LG non-200 (502), connection timeout 10s (502), S3 failures (500), invalid role (400)
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9_

  - [ ]* 5.2 Write property test for invalid role rejection (db)
    - **Property 3: Invalid role rejection**
    - Use Hypothesis to generate arbitrary strings that are not valid roles
    - Verify /db/export/{role} returns HTTP 400 with invalid value and valid roles list
    - **Validates: Requirements 7.5**

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implement Prometheus TSDB snapshot export
  - [x] 7.1 Create routes/prometheus_tsdb.py with POST /prometheus/tsdb/export
    - Add state guard: reject if NOT_INITIALIZED (HTTP 409)
    - Accept `TsdbExportRequest` body (optional prometheusPort, default 31565)
    - POST to `http://{controlPlaneNode}:{prometheusPort}/api/v1/admin/tsdb/snapshot` with 30s timeout
    - Extract snapshot name from response `data.name`
    - Find prometheus-server pod via kr8s (labels: `app.kubernetes.io/component=server,app.kubernetes.io/instance=prometheus`, namespace: `monitoring`)
    - Copy `/data/snapshots/{snapshotName}` from pod to local temp directory
    - Upload directory to S3 at `{s3Bucket}/{runIdentifier}/{trialIdentifier}/tsdb-snapshots`
    - Delete local temp copy after upload
    - Return 200 with s3Path and timestamp
    - Handle errors: 502 (Prometheus API fail/timeout), 500 (pod not found, copy failed, S3 failed)
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 5.10, 5.11_

- [x] 8. Implement metadata export endpoint
  - [x] 8.1 Create routes/metadata.py with POST /metadata/export
    - Add state guard: reject if NOT_INITIALIZED (HTTP 409)
    - Construct run_details.json with: timestamp (ISO 8601 UTC), environment (all 12 RunnerConfig fields), initialization (all 15 fields from BenchmarkState.config), roles (5 roles from ROLE_PARAMS), manifests (from MANIFEST_REPOS), status (equivalent to GET /status response)
    - Upload to S3 at `{s3Bucket}/{runIdentifier}/{trialIdentifier}/run_details.json` with Content-Type application/json
    - Return 200 with s3Key and timestamp
    - Handle S3 failure (500)
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9_

  - [ ]* 8.2 Write property test for run_details document completeness
    - **Property 5: Run details document completeness**
    - Use Hypothesis to generate valid BenchmarkState with non-null config
    - Verify constructed document contains all required top-level keys, all 12 environment fields, all 15 initialization fields, all 5 roles with correct parameters, and manifests with owner/repo/tag
    - **Validates: Requirements 8.1, 8.3, 8.4, 8.5, 8.6, 8.7**

- [x] 9. Implement shutdown endpoint
  - [x] 9.1 Create routes/shutdown.py with POST /shutdown
    - Add state guard: reject if NOT_INITIALIZED (409) or RUNNING (409)
    - Delete namespaces sequentially in order: globeco, elasticsearch, observability, monitoring
    - Use `asyncio.wait_for` with 60s timeout per namespace
    - Continue on failure, recording error detail
    - Return 200 with per-namespace results and timestamp
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

  - [ ]* 9.2 Write property test for partial namespace failure
    - **Property 6: Partial namespace failure yields correct response**
    - Use Hypothesis to generate subsets of namespaces that fail/timeout
    - Verify response lists all 4 namespaces exactly once with correct status and error details
    - **Validates: Requirements 9.3, 9.4**

- [x] 10. Register new routers and wire together
  - [x] 10.1 Update app.py to register new routers
    - Import and include routers for `prometheus_tsdb`, `metadata`, `shutdown`
    - Verify all new endpoints are accessible
    - _Requirements: 1.1, 5.1, 8.1, 9.1_

- [x] 11. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Update README documentation
  - [x] 12.1 Update README.md with all new and changed endpoints
    - Replace `POST /metrics` section with `POST /metrics/export` including prometheusPort field
    - Add `POST /prometheus/tsdb/export` section with request body, responses, and states
    - Add `POST /output/export` and `POST /output/export/{role}` section
    - Add `POST /db/export` and `POST /db/export/{role}` section
    - Add `POST /metadata/export` section with JSON fields and S3 path
    - Add `POST /shutdown` section with namespaces, responses, and error conditions
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7_

- [x] 13. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The design uses Python with FastAPI, so all implementations use that stack
- Hypothesis is the property-based testing library for Python

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3", "1.4", "1.5"] },
    { "id": 1, "tasks": ["2.1", "2.2", "2.3"] },
    { "id": 2, "tasks": ["4.1", "5.1", "7.1", "8.1", "9.1"] },
    { "id": 3, "tasks": ["4.2", "4.3", "5.2", "8.2", "9.2"] },
    { "id": 4, "tasks": ["10.1"] },
    { "id": 5, "tasks": ["12.1"] }
  ]
}
```
