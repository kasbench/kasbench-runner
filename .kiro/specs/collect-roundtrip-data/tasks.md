# Implementation Plan: Collect Roundtrip Data

## Overview

Add a `POST /roundtrip/export` endpoint that queries aggregated trade order data from the GlobeCo PostgreSQL database via `kubectl exec` and uploads the result to S3. This follows the existing route pattern established by `/metrics/export`.

## Tasks

- [x] 1. Create the roundtrip route module
  - [x] 1.1 Create `src/kasbench_runner/routes/roundtrip.py` with the endpoint implementation
    - Implement the state guard checking for terminal statuses (SUCCESS, FAILED, ABORTED)
    - Execute the kubectl subprocess command asynchronously
    - Handle non-zero exit code and empty stdout error cases
    - Validate JSON output with bracket-wrapping check
    - Upload raw stdout to S3 at `{run_identifier}/{trial_identifier}/roundtrip/trade_orders.json`
    - Return 200 response with `message`, `s3Key`, `jsonValid`, and `timestamp` fields
    - Include structured logging with bound `run_identifier` and `trial_identifier`
    - _Requirements: 1.1, 1.2, 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 6.1, 6.2, 6.3, 6.4_

  - [x] 1.2 Register the roundtrip router in `src/kasbench_runner/app.py`
    - Add import for `roundtrip` in the routes import block
    - Add `app.include_router(roundtrip.router)` in `create_app()`
    - _Requirements: 1.1, 5.2_

- [x] 2. Checkpoint - Verify route is wired correctly
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 3. Write tests for the roundtrip endpoint
  - [ ]* 3.1 Write property test for state guard behavior
    - **Property 1: State guard rejects non-terminal statuses**
    - **Validates: Requirements 1.1, 1.2**

  - [ ]* 3.2 Write property test for JSON validity classification
    - **Property 3: JSON validity classification by bracket wrapping**
    - **Validates: Requirements 3.2, 3.3**

  - [ ]* 3.3 Write unit tests for the roundtrip endpoint
    - Test successful export returns 200 with correct response fields
    - Test 409 response when benchmark is not in terminal state
    - Test 500 response on subprocess non-zero exit code with stderr
    - Test 500 response on empty stdout
    - Test 500 response on S3 upload failure
    - Test jsonValid is true for bracket-wrapped output and false otherwise
    - _Requirements: 1.1, 1.2, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3, 4.4_

- [x] 4. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- The design document contains the full implementation code for `roundtrip.py` — task 1.1 is a direct transcription
- The endpoint has no request body and derives all configuration from `BenchmarkState.config`
- No overwrite protection is needed (unlike `/metrics/export`) since aggregated sums are idempotent after terminal state

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["3.1", "3.2", "3.3"] }
  ]
}
```
