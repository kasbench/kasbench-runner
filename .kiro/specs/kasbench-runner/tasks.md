# Implementation Plan: KASBench Benchmark Runner

## Overview

This plan implements the KASBench Benchmark Runner FastAPI microservice from scratch. The implementation follows a bottom-up approach: project setup and shared infrastructure first (config, logging, errors, models), then service modules, then route handlers, and finally integration wiring. Property-based tests validate correctness properties defined in the design document.

## Tasks

- [ ] 1. Project setup and shared infrastructure
  - [ ] 1.1 Configure project dependencies and package structure
    - Update `pyproject.toml` with all runtime dependencies (fastapi, uvicorn, asyncssh, httpx, boto3, kr8s, structlog, pydantic-settings, pandas, pyarrow)
    - Add dev dependencies (pytest, pytest-asyncio, hypothesis, respx, pytest-structlog)
    - Create `src/kasbench_runner/__init__.py` and all subdirectory `__init__.py` files (models/, routes/, services/)
    - _Requirements: 18.1_

  - [ ] 1.2 Implement configuration module (`src/kasbench_runner/config.py`)
    - Create `RunnerConfig` pydantic-settings class with all environment variables and defaults
    - Implement range validation with fallback to defaults and WARNING log on invalid values
    - Define `VALID_ROLES`, `ROLE_PORTS`, `ROLE_PARAMS`, and `MANIFEST_REPOS` constants
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6_

  - [ ]* 1.3 Write property test for configuration validation (Property 13)
    - **Property 13: Configuration environment variable validation**
    - **Validates: Requirements 18.2, 18.3, 18.4, 18.6**
    - Use Hypothesis to generate random numeric values (valid, out-of-range, non-integer) for config env vars
    - Verify valid values are used, invalid values fall back to defaults with WARNING log

  - [ ] 1.4 Implement structured logging module (`src/kasbench_runner/logging.py`)
    - Configure structlog with JSON output, ISO 8601 timestamps, UTC timezone
    - Include log level, event name, and bound context fields in each entry
    - _Requirements: 13.1_

  - [ ] 1.5 Implement error handling module (`src/kasbench_runner/errors.py`)
    - Create `RunnerError` base exception with `error`, `message`, `context` fields
    - Create `SSHError`, `DockerError`, `LoadGeneratorError`, `ManifestError` subclasses
    - Implement `build_error_response()` function returning JSONResponse with all required fields
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_

  - [ ]* 1.6 Write property test for error response structure (Property 10)
    - **Property 10: Error response structure completeness**
    - **Validates: Requirements 11.1, 11.2**
    - Use Hypothesis to generate random error conditions; verify every response contains `error`, `message`, `context`, and `timestamp` fields

  - [ ]* 1.7 Write property test for operation-specific error context (Property 11)
    - **Property 11: Operation-specific error context fields**
    - **Validates: Requirements 11.4, 11.5, 11.6**
    - Use Hypothesis to generate SSH failures (verify `hostname`, `command`, `exit_code`, `stderr`), Docker failures (verify `container_name`, `image`, `operation`, `error_output`), HTTP failures (verify `url`, `method`, `status_code`, `response_body`)

- [ ] 2. Data models
  - [ ] 2.1 Implement request models (`src/kasbench_runner/models/requests.py`)
    - Create `InitializeRequest` Pydantic model with required fields (autoscaler, controlPlaneNode, amdWorkerNodes, armWorkerNodes, s3Bucket, globecoUrl) and optional fields with defaults
    - Use Field aliases for camelCase JSON input and snake_case Python attributes
    - Add min_length and type constraints as per design
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [ ] 2.2 Implement response models (`src/kasbench_runner/models/responses.py`)
    - Create `ErrorResponse`, `LoadGeneratorStatus`, `StatusResponse`, `StartResponse`, `AbortResponse` Pydantic models
    - Implement camelCase serialization aliases
    - _Requirements: 8.6, 11.2_

  - [ ] 2.3 Implement internal state model (`src/kasbench_runner/models/state.py`)
    - Create `BenchmarkStatus` enum with all states (not-initialized, not-started, running, success, failed, aborted)
    - Create `BenchmarkState` dataclass with status, config, timestamps, and internal flags
    - Implement `initialization_complete` property
    - _Requirements: 1.1, 1.2, 1.6_

  - [ ]* 2.4 Write property test for required field validation (Property 6)
    - **Property 6: Required field validation rejects invalid requests**
    - **Validates: Requirements 2.1, 2.2**
    - Use Hypothesis to generate requests with random subsets of required fields missing/empty/blank; verify HTTP 422 identifying all invalid fields

  - [ ]* 2.5 Write property test for optional field defaults (Property 7)
    - **Property 7: Optional field defaults are applied correctly**
    - **Validates: Requirements 2.3, 2.4**
    - Use Hypothesis to generate requests with random subsets of optional fields omitted; verify defaults applied correctly

  - [ ]* 2.6 Write property test for type mismatch validation (Property 8)
    - **Property 8: Type mismatch returns 422 with diagnostic info**
    - **Validates: Requirements 2.5**
    - Use Hypothesis to generate type-incorrect values for fields; verify 422 with field name, expected type, and received type

- [ ] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Core service modules
  - [ ] 4.1 Implement health checker service (`src/kasbench_runner/services/health_checker.py`)
    - Create `check_health()` async function with max_attempts, interval_seconds, timeout_seconds, expected_status, expected_fields parameters
    - Implement retry loop with interval waits between failed attempts
    - Return `HealthCheckResult` with success/failure details, last status, last body, attempt count
    - Log each attempt at INFO level with attempt number, target URL, status code, and match result
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5_

  - [ ]* 4.2 Write property test for health check exhaustion (Property 12)
    - **Property 12: Health check exhaustion reports**
    - **Validates: Requirements 14.3**
    - Use Hypothesis to generate random max_attempts N and failing responses; verify failure result contains last status, last body, and attempt count == N

  - [ ] 4.3 Implement SSH client service (`src/kasbench_runner/services/ssh_client.py`)
    - Create `SSHClient` class with `connect()`, `execute()`, `copy_from_remote()`, `close()` async methods
    - Use asyncssh for connections with configurable timeout (default 30s) as ubuntu user
    - Capture stdout and stderr separately
    - Raise `SSHError` on non-zero exit codes or connection failures
    - Log each command execution at INFO level with hostname, command, exit code, outcome
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

  - [ ] 4.4 Implement Docker manager service (`src/kasbench_runner/services/docker_manager.py`)
    - Create `DockerManager` class with `verify_network()`, `run_container()`, `inspect_container()` async methods
    - Use asyncio.create_subprocess_exec for Docker CLI commands
    - Raise `DockerError` on failures with container_name, image, operation, error_output
    - Log each Docker operation at INFO level
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [ ] 4.5 Implement manifest parser service (`src/kasbench_runner/services/manifest_parser.py`)
    - Create `ManifestOperation` dataclass with op_type (noop, comment, command, sleep, manifest), raw_line, value
    - Implement `parse_manifest_list(content: str) -> list[ManifestOperation]` with line-by-line classification
    - Implement `serialize_operations(operations: list[ManifestOperation]) -> str` for round-trip support
    - Handle blank lines, `#` comments, `>` commands, `+` sleep, manifest filenames with `.yaml` appending
    - _Requirements: 19.1, 19.2, 19.3, 19.4, 19.5, 19.6, 19.7, 19.8, 19.9_

  - [ ]* 4.6 Write property test for manifest round-trip parsing (Property 1)
    - **Property 1: Manifest list round-trip parsing**
    - **Validates: Requirements 19.9**
    - Use Hypothesis to generate random k8s.lst content; verify parse→serialize→parse produces identical operation list

  - [ ]* 4.7 Write property test for manifest line classification (Property 2)
    - **Property 2: Manifest line classification**
    - **Validates: Requirements 19.1, 19.2, 19.3, 19.4, 19.5, 19.7**
    - Use Hypothesis to generate random lines; verify correct classification per rules and .yaml appending

  - [ ] 4.8 Implement Kubernetes manager service (`src/kasbench_runner/services/kubernetes_manager.py`)
    - Create `KubernetesManager` class orchestrating kubeadm init, SCP kubeconfig, Flannel install, token creation, kubeadm join
    - Implement kr8s node readiness polling with configurable timeout and 10s intervals
    - Implement namespace creation (globeco, monitoring, elasticsearch, observability) with idempotent checks
    - Implement EBS CSI driver Helm install and StorageClass creation
    - Log node readiness progress at each poll iteration
    - Raise appropriate errors with full context on any step failure
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11, 4.12, 4.13, 4.14_

  - [ ] 4.9 Implement S3 client service (`src/kasbench_runner/services/s3_client.py`)
    - Create `S3Client` class with `reserve_trial()` method using boto3 conditional put_object with `IfNoneMatch="*"`
    - Handle `PreconditionFailed` ClientError → HTTP 409
    - Handle other exceptions → HTTP 500 with bucket, key, exception details
    - _Requirements: 3.1, 3.2, 3.3_

  - [ ] 4.10 Implement Load Generator client service (`src/kasbench_runner/services/load_generator_client.py`)
    - Create `LoadGeneratorClient` class with httpx async client
    - Implement `start()`, `health()`, `abort()`, `stream_output()`, `stream_db()` methods
    - Address generators by container name on port 8080
    - Set connection timeout 10s, read timeout 30s
    - Raise `LoadGeneratorError` on failures with full context
    - _Requirements: 20.1, 20.2, 20.3, 20.4, 20.5, 20.6_

- [ ] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Route handlers - Initialization and Start
  - [ ] 6.1 Implement POST /initialize route (`src/kasbench_runner/routes/initialize.py`)
    - Validate request using InitializeRequest model (422 on validation errors)
    - Check state is `not_initialized` (409 if already initialized)
    - Reserve S3 trial (409 on duplicate, 500 on error)
    - Orchestrate Kubernetes install (respecting skipKubernetesInstall)
    - Orchestrate manifest install (respecting skipManifestInstall, forceManifestInstall)
    - Orchestrate load generator deployment (Docker network validation, RabbitMQ, five generators, health checks)
    - Set state flags and transition to `not-started`
    - Persist request config in BenchmarkState
    - _Requirements: 1.2, 1.7, 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 4.1–4.14, 5.1–5.13, 6.1–6.12_

  - [ ] 6.2 Implement POST /start route (`src/kasbench_runner/routes/start.py`)
    - Validate initialization_complete is True (409 if not)
    - Validate Benchmark_Status is not `running` (409 if already running)
    - Record benchmark_start_time
    - POST /start to all five Load Generators concurrently via asyncio.gather with role-specific parameters
    - Verify all generators report `running` status via health checks (3 attempts, 5s intervals)
    - Set Benchmark_Status to `running` and return start timestamp
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9, 7.10_

- [ ] 7. Route handlers - Status, Output, DB
  - [ ] 7.1 Implement GET /status route (`src/kasbench_runner/routes/status.py`)
    - Handle `not_initialized` state: return minimal response
    - Query all Load Generator /health endpoints with 5s timeout
    - Implement endTime aggregation: max for all-success, min-of-failed for any-failed
    - Return StatusResponse with overall status, timestamps, and per-generator details
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_

  - [ ]* 7.2 Write property test for success endTime aggregation (Property 3)
    - **Property 3: Success endTime is the maximum across generators**
    - **Validates: Requirements 1.4, 8.3**
    - Use Hypothesis to generate five datetime values; verify aggregated end_time equals max

  - [ ]* 7.3 Write property test for failure endTime aggregation (Property 4)
    - **Property 4: Failure endTime is the minimum among failed generators**
    - **Validates: Requirements 1.5, 8.4**
    - Use Hypothesis to generate mixed status/datetime sets; verify end_time equals min of failed

  - [ ]* 7.4 Write property test for non-terminal status preservation (Property 5)
    - **Property 5: Non-terminal status mix preserves current status**
    - **Validates: Requirements 8.5**
    - Use Hypothesis to generate status sets with no `failed` and not all `success`; verify status unchanged

  - [ ] 7.5 Implement GET /output/{role} route (`src/kasbench_runner/routes/output.py`)
    - Validate role parameter (400 for invalid role with valid roles list)
    - Stream response from Load Generator /download-output endpoint
    - Forward 409 (subprocess active), 404 (no output) status codes
    - Return 502 on connection timeout (10s)
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

  - [ ] 7.6 Implement GET /db/{role} route (`src/kasbench_runner/routes/db.py`)
    - Validate role parameter (400 for invalid role with valid roles list)
    - Stream response from Load Generator /download-db endpoint
    - Forward 409 (subprocess active), 404 (no DB) status codes
    - Return 502 on connection timeout (10s) or unexpected upstream status
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7_

  - [ ]* 7.7 Write property test for invalid role rejection (Property 9)
    - **Property 9: Invalid role rejection**
    - **Validates: Requirements 9.5, 10.5**
    - Use Hypothesis to generate random non-role strings; verify both /output and /db return 400 with invalid value and valid roles list

- [ ] 8. Route handlers - Abort and Metrics
  - [ ] 8.1 Implement POST /abort route (`src/kasbench_runner/routes/abort.py`)
    - Validate Benchmark_Status is `running` (409 if not)
    - POST /abort to all five Load Generators concurrently (best-effort)
    - Set Benchmark_Status to `aborted` with current UTC timestamp
    - Return abort timestamp and per-role results
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5_

  - [ ] 8.2 Implement GET /metrics route (`src/kasbench_runner/routes/metrics.py`)
    - Validate Benchmark_Status is `success` or `failed` (409 otherwise)
    - Scrape Prometheus metrics from monitoring namespace
    - Transform to Pandas DataFrames, serialize to Parquet
    - Upload to S3 at `{run_identifier}/{trial_identifier}/metrics/`
    - Return confirmation with file count
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6_

- [ ] 9. Application wiring and entrypoint
  - [ ] 9.1 Implement FastAPI application factory (`src/kasbench_runner/app.py`)
    - Create FastAPI app with lifespan handler for startup/shutdown
    - Register all route modules
    - Register global RunnerError exception handler
    - Initialize shared BenchmarkState and inject via app.state or dependency
    - _Requirements: 1.1, 11.1_

  - [ ] 9.2 Update `main.py` as application entrypoint
    - Import and run the FastAPI app via uvicorn
    - Wire RunnerConfig for host/port settings
    - _Requirements: 18.1_

- [ ] 10. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- All services use asyncio for concurrency; SSH via asyncssh, HTTP via httpx, subprocess via asyncio.create_subprocess_exec
- The implementation uses Python 3.13+ with FastAPI, as specified in the design

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.4", "1.5"] },
    { "id": 2, "tasks": ["1.3", "1.6", "1.7", "2.1", "2.2", "2.3"] },
    { "id": 3, "tasks": ["2.4", "2.5", "2.6", "4.1", "4.5", "4.9"] },
    { "id": 4, "tasks": ["4.2", "4.3", "4.4", "4.6", "4.7", "4.10"] },
    { "id": 5, "tasks": ["4.8"] },
    { "id": 6, "tasks": ["6.1"] },
    { "id": 7, "tasks": ["6.2", "7.1", "7.5", "7.6"] },
    { "id": 8, "tasks": ["7.2", "7.3", "7.4", "7.7", "8.1", "8.2"] },
    { "id": 9, "tasks": ["9.1", "9.2"] }
  ]
}
```
