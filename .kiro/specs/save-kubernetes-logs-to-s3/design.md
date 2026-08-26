# Design Document: Save Kubernetes Logs to S3

## Architecture Overview

This feature adds a `POST /logs/{namespace}/export` endpoint to the KASBench Benchmark Runner. It follows the existing route/service separation pattern: a thin FastAPI route handles request validation and state guards, delegating to a `LogCollector` service that handles Kubernetes API interactions and S3 uploads.

```
┌────────────────────────┐
│   POST /logs/{ns}/export │
│   routes/logs.py        │
└───────────┬────────────┘
            │
            ▼
┌────────────────────────┐
│    LogCollector         │
│    services/            │
│    log_collector.py     │
├────────────────────────┤
│  - discover pods (kr8s) │
│  - collect logs (kr8s)  │
│  - determine filenames  │
│  - upload to S3         │
└───────────┬────────────┘
            │
            ▼
┌────────────────────────┐
│    S3Client             │
│    (existing)           │
│    upload_bytes()       │
└────────────────────────┘
```

## Components

### 1. Route: `src/kasbench_runner/routes/logs.py`

A new FastAPI `APIRouter` module following the same patterns as `metrics.py`:

- Accepts `{namespace}` as a path parameter
- Accesses `BenchmarkState` via `request.app.state.benchmark_state`
- Applies a state guard: rejects requests when status is `not-initialized` (HTTP 409)
- Instantiates `LogCollector` with an `S3Client`
- Returns structured JSON responses (200, 207, or 500)

```python
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


@router.post("/logs/{namespace}/export")
async def post_logs_export(namespace: str, request: Request) -> JSONResponse:
    state: BenchmarkState = request.app.state.benchmark_state

    # State guard
    if state.status == BenchmarkStatus.NOT_INITIALIZED:
        return build_error_response(
            error="not_initialized",
            message="Benchmark has not been initialized",
            status_code=409,
        )

    config = state.config
    s3_client = S3Client(bucket=config.s3_bucket)
    collector = LogCollector(s3_client=s3_client)

    result = await collector.collect_and_upload(
        namespace=namespace,
        run_identifier=config.run_identifier,
        trial_identifier=config.trial_identifier,
    )

    # Build response based on result
    ...
```

### 2. Service: `src/kasbench_runner/services/log_collector.py`

An async service class responsible for:

1. **Pod discovery** — Query all pods in the given namespace via `kr8s`
2. **Container enumeration** — For each pod, identify all containers
3. **Log collection** — Fetch logs from each container (best-effort)
4. **Filename determination** — Apply naming convention based on container count
5. **S3 upload** — Upload each log file via `S3Client.upload_bytes()`

```python
import kr8s
import structlog
from dataclasses import dataclass

from kasbench_runner.services.s3_client import S3Client, S3OperationError

logger = structlog.get_logger()


@dataclass(frozen=True)
class LogCollectionResult:
    """Result of the log collection and upload operation."""
    files_exported: int
    s3_prefix: str
    errors: list[dict]


@dataclass(frozen=True)
class LogEntry:
    """A single collected log ready for upload."""
    pod_name: str
    container_name: str
    filename: str
    content: bytes


class LogCollector:
    """Collects Kubernetes pod logs and uploads to S3."""

    def __init__(self, s3_client: S3Client) -> None:
        self._s3_client = s3_client

    async def collect_and_upload(
        self,
        namespace: str,
        run_identifier: str,
        trial_identifier: str,
    ) -> LogCollectionResult:
        ...

    async def _discover_pods(self, namespace: str) -> list:
        """Query all pods in the namespace via kr8s."""
        api = await kr8s.asyncio.api()
        pods = [p async for p in api.get("pods", namespace=namespace)]
        return pods

    def _determine_filename(
        self, pod_name: str, container_name: str, container_count: int
    ) -> str:
        """Apply naming convention based on container count."""
        if container_count == 1:
            return f"{pod_name}.log"
        return f"{pod_name}-{container_name}.log"

    async def _collect_container_log(self, pod, container_name: str) -> bytes | None:
        """Fetch logs from a single container. Returns None if unavailable."""
        ...
```

### 3. Router Registration: `src/kasbench_runner/app.py`

The new router is included in the FastAPI application alongside existing routers:

```python
from kasbench_runner.routes.logs import router as logs_router

app.include_router(logs_router)
```

## Interfaces

### HTTP Interface

**Request:**
```
POST /logs/{namespace}/export
```

No request body required.

**Success Response (200):**
```json
{
  "message": "Logs exported successfully",
  "filesExported": 12,
  "s3Prefix": "run001/trial001/logs/globeco/",
  "timestamp": "2026-06-10T14:50:00.000000+00:00"
}
```

**Partial Success Response (207):**
```json
{
  "message": "Log export completed with 2 error(s)",
  "filesExported": 10,
  "s3Prefix": "run001/trial001/logs/globeco/",
  "errors": [
    {
      "pod": "worker-abc123",
      "container": "sidecar",
      "phase": "collection",
      "error": "container logs not available"
    },
    {
      "pod": "api-def456",
      "container": "main",
      "phase": "upload",
      "error": "S3 operation failed: ClientError: ..."
    }
  ],
  "timestamp": "2026-06-10T14:50:00.000000+00:00"
}
```

**Error Responses:**

| Status | Error | Condition |
|--------|-------|-----------|
| 409 | `not_initialized` | BenchmarkState status is `not-initialized` |
| 500 | `kubernetes_error` | Kubernetes API unreachable during pod listing |

### Internal Service Interface

```python
class LogCollector:
    async def collect_and_upload(
        self,
        namespace: str,
        run_identifier: str,
        trial_identifier: str,
    ) -> LogCollectionResult:
        """
        Collect logs from all pods in namespace and upload to S3.

        Args:
            namespace: Target Kubernetes namespace.
            run_identifier: Run ID for S3 path construction.
            trial_identifier: Trial ID for S3 path construction.

        Returns:
            LogCollectionResult with files_exported count, s3_prefix, and errors list.

        Raises:
            SnapshotCollectionError: If the initial pod listing fails
                (Kubernetes API unreachable).
        """
```

## Data Models

### LogCollectionResult

```python
@dataclass(frozen=True)
class LogCollectionResult:
    """Result of a log collection and upload operation."""
    files_exported: int
    s3_prefix: str
    errors: list[dict]
    # Each error dict has keys: pod, container, phase, error
```

### LogEntry (internal)

```python
@dataclass(frozen=True)
class LogEntry:
    """A single collected log ready for upload."""
    pod_name: str
    container_name: str
    filename: str
    content: bytes
```

## S3 Path Structure

```
{s3_bucket}/
  {runIdentifier}/
    {trialIdentifier}/
      logs/
        {namespace}/
          {pod_name}.log                    # single-container pod
          {pod_name}-{container_name}.log   # multi-container pod
```

## Error Handling

The feature uses a best-effort approach with two error phases:

1. **Collection phase** — If fetching logs from a container fails (container never started, logs unavailable), the error is recorded and processing continues to the next container/pod.

2. **Upload phase** — If uploading a log file to S3 fails, the error is recorded and the remaining uploads continue.

**Fatal errors** (returned as HTTP 500):
- Kubernetes API unreachable during initial pod listing — raises `SnapshotCollectionError` which the route converts to a 500 response.

**Non-fatal errors** (recorded in errors array):
- Individual container log collection failures
- Individual S3 upload failures

This matches the existing pattern in `metrics.py` where query failures and upload failures are recorded individually but don't abort the entire operation.

## Sequence Diagram

```
Client          Route (logs.py)       LogCollector        kr8s API        S3Client
  │                  │                     │                 │               │
  │ POST /logs/ns/   │                     │                 │               │
  │─────────────────>│                     │                 │               │
  │                  │ state guard check   │                 │               │
  │                  │ (reject if not-init)│                 │               │
  │                  │                     │                 │               │
  │                  │ collect_and_upload() │                 │               │
  │                  │────────────────────>│                 │               │
  │                  │                     │ get pods in ns  │               │
  │                  │                     │────────────────>│               │
  │                  │                     │<────────────────│               │
  │                  │                     │                 │               │
  │                  │                     │ for each pod:   │               │
  │                  │                     │   for each container:           │
  │                  │                     │     get logs    │               │
  │                  │                     │────────────────>│               │
  │                  │                     │<────────────────│               │
  │                  │                     │                 │               │
  │                  │                     │   upload_bytes()│               │
  │                  │                     │────────────────────────────────>│
  │                  │                     │<────────────────────────────────│
  │                  │                     │                 │               │
  │                  │ LogCollectionResult  │                 │               │
  │                  │<────────────────────│                 │               │
  │                  │                     │                 │               │
  │  200/207 JSON    │                     │                 │               │
  │<─────────────────│                     │                 │               │
```

## Container Log Retrieval

Logs are fetched using kr8s pod log retrieval. The approach:

```python
async def _collect_container_log(self, pod, container_name: str) -> bytes | None:
    """Fetch logs from a single container.

    Returns None if logs are unavailable (container never started,
    waiting state, etc.).
    """
    try:
        logs = await pod.logs(container=container_name)
        if logs:
            return logs.encode("utf-8") if isinstance(logs, str) else logs
        return None
    except Exception:
        return None
```

## Filename Determination Logic

```python
def _determine_filename(
    self, pod_name: str, container_name: str, container_count: int
) -> str:
    """Determine the log filename based on container count.

    Single-container pods: {pod_name}.log
    Multi-container pods:  {pod_name}-{container_name}.log
    """
    if container_count == 1:
        return f"{pod_name}.log"
    return f"{pod_name}-{container_name}.log"
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: State guard accepts all initialized states

*For any* BenchmarkState status in {not-started, running, success, failed, aborted}, the `POST /logs/{namespace}/export` endpoint SHALL accept and process the request (not return 409 with `not_initialized`).

**Validates: Requirements 2.2**

### Property 2: All pod phases are included in collection

*For any* set of pods in a namespace, regardless of their phase (Running, Succeeded, Failed, Pending, Unknown), the LogCollector SHALL include every pod in its collection set without filtering by phase.

**Validates: Requirements 3.2, 3.3**

### Property 3: Container log completeness

*For any* pod with N containers where M containers have available log output (M ≤ N), the LogCollector SHALL produce exactly M log entries — one for each container with available output — and skip the remaining N-M containers without raising a fatal error.

**Validates: Requirements 4.1, 4.2**

### Property 4: File naming convention

*For any* pod with exactly one container, the log filename SHALL be `{pod_name}.log`. *For any* pod with more than one container, each container's log filename SHALL be `{pod_name}-{container_name}.log`.

**Validates: Requirements 5.1, 5.2**

### Property 5: S3 key path construction

*For any* combination of run_identifier, trial_identifier, namespace, and filename, the S3 upload key SHALL be `{run_identifier}/{trial_identifier}/logs/{namespace}/{filename}`.

**Validates: Requirements 6.1**

### Property 6: Response status code correctness

*For any* log export operation, if all collected logs are uploaded successfully the response SHALL be HTTP 200, and if at least one operation fails but at least one succeeds the response SHALL be HTTP 207 with an errors array containing one entry per failure.

**Validates: Requirements 7.1, 7.2**

### Property 7: Best-effort error resilience

*For any* set of pods/containers where K operations fail (either log collection or S3 upload), the remaining operations SHALL still be attempted and completed. The total files_exported plus the error count SHALL equal the total number of containers with attempted operations.

**Validates: Requirements 8.1, 8.2**
