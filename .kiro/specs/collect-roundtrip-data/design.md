# Design Document

## Introduction

This document describes the design for the `POST /roundtrip/export` endpoint, which collects aggregated trade order roundtrip data from the GlobeCo PostgreSQL database via `kubectl exec` and uploads the results to S3.

## Architecture Overview

The endpoint follows the established pattern of the existing `/metrics/export` route: a state guard ensures the benchmark has completed, then an asynchronous subprocess executes the database query, and the result is uploaded to S3.

```
POST /roundtrip/export
         │
         ▼
┌─────────────────────┐
│   State Guard       │──── 409 if not terminal
│  (terminal status?) │
└─────────────────────┘
         │ pass
         ▼
┌─────────────────────┐
│  kubectl exec       │──── 500 if non-zero exit or empty stdout
│  (subprocess)       │
└─────────────────────┘
         │ success
         ▼
┌─────────────────────┐
│  Validate & Upload  │──── 500 if S3 fails
│  (S3Client)         │
└─────────────────────┘
         │ success
         ▼
     200 JSON response
```

## Components

### Route Module: `src/kasbench_runner/routes/roundtrip.py`

A new route module following the same structure as existing routes (e.g., `metrics.py`).

```python
"""POST /roundtrip/export endpoint for the KASBench Benchmark Runner.

Orchestrates kubectl exec query of roundtrip trade order data and S3 upload.

Requirements: 1.1, 1.2, 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 4.1, 4.2,
              4.3, 4.4, 5.1, 5.2, 6.1, 6.2, 6.3, 6.4
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from kasbench_runner.errors import build_error_response
from kasbench_runner.models.state import BenchmarkState, BenchmarkStatus
from kasbench_runner.services.s3_client import S3Client, S3OperationError

logger = structlog.get_logger(__name__)

router = APIRouter()

_TERMINAL_STATUSES = {
    BenchmarkStatus.SUCCESS,
    BenchmarkStatus.FAILED,
    BenchmarkStatus.ABORTED,
}

_KUBECTL_COMMAND = [
    "kubectl", "exec", "svc/globeco-debug-tools", "--",
    "psql", "-h", "globeco-trade-service-postgresql",
    "-U", "postgres", "-tAc",
    "select json_agg(t) from (select sum(quantity_ordered) quantity_ordered, "
    "sum(quantity_placed) quantity_placed, sum(quantity_filled) quantity_filled "
    "from execution) t;",
]


@router.post("/roundtrip/export")
async def post_roundtrip_export(request: Request) -> JSONResponse:
    """Collect roundtrip trade order data and upload to S3."""
    state: BenchmarkState = request.app.state.benchmark_state

    # State guard
    if state.status not in _TERMINAL_STATUSES:
        return build_error_response(
            error="benchmark_not_completed",
            message=(
                "Roundtrip export is only available after the benchmark "
                "has completed (status must be 'success', 'failed', or 'aborted')"
            ),
            status_code=409,
            current_status=state.status.value,
        )

    config = state.config
    run_identifier = config.run_identifier
    trial_identifier = config.trial_identifier
    s3_bucket = config.s3_bucket

    log = logger.bind(
        run_identifier=run_identifier,
        trial_identifier=trial_identifier,
    )
    log.info("roundtrip_export_start")

    # Execute kubectl query
    proc = await asyncio.create_subprocess_exec(
        *_KUBECTL_COMMAND,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()

    if proc.returncode != 0:
        stderr_text = stderr_bytes.decode().strip()
        log.error(
            "roundtrip_query_failed",
            exit_code=proc.returncode,
            stderr=stderr_text,
        )
        return build_error_response(
            error="roundtrip_query_failed",
            message="kubectl exec query returned non-zero exit code",
            status_code=500,
            exit_code=proc.returncode,
            stderr=stderr_text,
        )

    stdout_text = stdout_bytes.decode().strip()

    if not stdout_text:
        log.error("roundtrip_query_empty")
        return build_error_response(
            error="roundtrip_query_empty",
            message="No data was returned from the roundtrip query",
            status_code=500,
        )

    # Validate JSON structure (bracket check)
    json_valid = stdout_text.startswith("[") and stdout_text.endswith("]")

    if not json_valid:
        log.warning(
            "roundtrip_output_invalid_json",
            output_preview=stdout_text[:200],
        )

    # Upload to S3
    s3_key = f"{run_identifier}/{trial_identifier}/roundtrip/trade_orders.json"
    s3_client = S3Client(bucket=s3_bucket)

    try:
        await s3_client.upload_json(key=s3_key, data=stdout_text.encode("utf-8"))
    except S3OperationError as exc:
        log.error("s3_upload_failed", s3_key=s3_key, error=str(exc))
        return build_error_response(
            error="s3_operation_failed",
            message=f"S3 upload failed: {exc.message}",
            status_code=500,
        )

    log.info("roundtrip_export_success", s3_key=s3_key)

    return JSONResponse(
        status_code=200,
        content={
            "message": "Roundtrip data exported successfully",
            "s3Key": s3_key,
            "jsonValid": json_valid,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
```

### Registration in `app.py`

Add import and router registration:

```python
from kasbench_runner.routes import roundtrip

# In create_app():
app.include_router(roundtrip.router)
```

## Interfaces

### Endpoint

| Method | Path | Request Body | Auth |
|--------|------|-------------|------|
| POST | `/roundtrip/export` | None | None |

### Success Response (200)

```json
{
  "message": "Roundtrip data exported successfully",
  "s3Key": "run001/trial001/roundtrip/trade_orders.json",
  "jsonValid": true,
  "timestamp": "2024-01-15T10:30:00.000000+00:00"
}
```

### Error Responses

| Status | Error Code | Condition |
|--------|-----------|-----------|
| 409 | `benchmark_not_completed` | Benchmark not in terminal state |
| 500 | `roundtrip_query_failed` | kubectl exec returned non-zero exit code |
| 500 | `roundtrip_query_empty` | Query returned empty stdout |
| 500 | `s3_operation_failed` | S3 upload raised an exception |

## Data Flow

1. Request arrives at `POST /roundtrip/export`
2. State guard checks `BenchmarkState.status ∈ {SUCCESS, FAILED, ABORTED}`
3. Configuration values (`run_identifier`, `trial_identifier`, `s3_bucket`) are read from `BenchmarkState.config`
4. `asyncio.create_subprocess_exec` runs the kubectl command
5. Exit code and stdout are checked for errors
6. Raw stdout is uploaded to S3 at `{run_identifier}/{trial_identifier}/roundtrip/trade_orders.json`
7. JSON validity is determined by bracket-wrapping check (`[...]`)
8. 200 response returned with upload metadata

## Error Handling

- **Non-terminal state**: Returns 409 immediately without executing any query
- **Subprocess failure (non-zero exit)**: Returns 500 with stderr included for diagnostics
- **Empty stdout**: Returns 500 — the query succeeded but returned no data, indicating a database issue
- **S3 upload failure**: Returns 500 with exception details from `S3OperationError`
- **No overwrite protection**: Unlike `/metrics/export`, this endpoint always uploads (idempotent data — aggregated sums don't change after terminal state)

## Logging Strategy

All log events use `structlog` with `run_identifier` and `trial_identifier` bound to the logger context:

| Event | Level | Additional Fields |
|-------|-------|-------------------|
| `roundtrip_export_start` | INFO | — |
| `roundtrip_query_failed` | ERROR | `exit_code`, `stderr` |
| `roundtrip_query_empty` | ERROR | — |
| `roundtrip_output_invalid_json` | WARNING | `output_preview` (first 200 chars) |
| `s3_upload_failed` | ERROR | `s3_key`, `error` |
| `roundtrip_export_success` | INFO | `s3_key` |

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: State guard rejects non-terminal statuses

*For any* BenchmarkStatus that is not in the set {SUCCESS, FAILED, ABORTED}, calling `POST /roundtrip/export` SHALL return HTTP 409 with error code "benchmark_not_completed", and for any BenchmarkStatus that IS in that set, the endpoint SHALL NOT return 409.

**Validates: Requirements 1.1, 1.2**

### Property 2: Non-zero exit code produces query failure response

*For any* subprocess execution that returns a non-zero exit code and any stderr content, the endpoint SHALL return HTTP 500 with error code "roundtrip_query_failed" and the response context SHALL include the stderr output.

**Validates: Requirements 2.2**

### Property 3: JSON validity classification by bracket wrapping

*For any* non-empty stdout string, the `jsonValid` field in the response SHALL be `true` if and only if the string starts with `[` and ends with `]`.

**Validates: Requirements 3.2, 3.3**

### Property 4: S3 key construction from config

*For any* `run_identifier` and `trial_identifier` values in BenchmarkState.config, the S3 upload key SHALL equal `"{run_identifier}/{trial_identifier}/roundtrip/trade_orders.json"` and the uploaded content SHALL be the raw stdout bytes.

**Validates: Requirements 3.1, 4.3, 5.1**

### Property 5: S3 failure produces operation error response

*For any* S3OperationError raised during upload, the endpoint SHALL return HTTP 500 with error code "s3_operation_failed".

**Validates: Requirements 3.4**

### Property 6: Successful response contains all required fields

*For any* successful roundtrip export (no subprocess or S3 errors), the HTTP 200 response body SHALL contain exactly the fields: `message`, `s3Key`, `jsonValid`, and `timestamp`, where `timestamp` is a valid ISO 8601 UTC string.

**Validates: Requirements 4.1, 4.4**
