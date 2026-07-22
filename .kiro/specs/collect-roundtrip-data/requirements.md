# Requirements Document

## Introduction

This feature adds a `POST /roundtrip/export` endpoint to the KASBench Benchmark Runner. The endpoint executes a `kubectl exec` command to query roundtrip trade order data from the GlobeCo PostgreSQL database, then uploads the query results to S3. The endpoint follows the same terminal-state guard pattern as `/metrics/export` and uploads results without overwrite protection.

## Glossary

- **Runner**: The KASBench Benchmark Runner FastAPI application
- **BenchmarkState**: The mutable singleton holding benchmark lifecycle state, including status and configuration
- **Terminal_Status**: A benchmark status of "success", "failed", or "aborted"
- **S3Client**: The service responsible for uploading artifacts to Amazon S3
- **Roundtrip_Query**: The `kubectl exec` command that retrieves aggregated trade order data from the GlobeCo PostgreSQL database via the `globeco-debug-tools` service
- **Roundtrip_Output**: The stdout result of executing the Roundtrip_Query
- **S3_Key**: The full object path in S3 where the roundtrip data is stored, formatted as `{s3_bucket}/{run_identifier}/{trial_identifier}/roundtrip/trade_orders.json`

## Requirements

### Requirement 1: State Guard

**User Story:** As a benchmark operator, I want the roundtrip export to only run after the benchmark has reached a terminal state, so that the data reflects a complete benchmark run.

#### Acceptance Criteria

1. WHEN a POST request is received at `/roundtrip/export` and the BenchmarkState status is not a Terminal_Status, THE Runner SHALL return an HTTP 409 response with error code "benchmark_not_completed" and a message indicating the benchmark must reach a terminal state before exporting roundtrip data.
2. WHEN a POST request is received at `/roundtrip/export` and the BenchmarkState status is a Terminal_Status, THE Runner SHALL proceed with the roundtrip data collection.

### Requirement 2: Query Execution

**User Story:** As a benchmark operator, I want the system to query the GlobeCo database for aggregated trade order data, so that I can analyze order fulfillment metrics.

#### Acceptance Criteria

1. WHEN the state guard passes, THE Runner SHALL execute the Roundtrip_Query asynchronously using `asyncio.create_subprocess_exec` with the command: `kubectl exec svc/globeco-debug-tools -- psql -h globeco-trade-service-postgresql -U postgres -tAc "select json_agg(t) from (select sum(quantity_ordered) quantity_ordered, sum(quantity_placed) quantity_placed, sum(quantity_filled) quantity_filled from execution) t;"`.
2. IF the Roundtrip_Query returns a non-zero exit code, THEN THE Runner SHALL return an HTTP 500 response with error code "roundtrip_query_failed" and include the stderr output in the error context.
3. IF the Roundtrip_Query returns an empty stdout, THEN THE Runner SHALL return an HTTP 500 response with error code "roundtrip_query_empty" and a message indicating no data was returned.

### Requirement 3: Output Validation and Upload

**User Story:** As a benchmark operator, I want the query results uploaded to S3 regardless of JSON validity, so that I always have access to the raw data for debugging.

#### Acceptance Criteria

1. WHEN the Roundtrip_Query completes successfully with non-empty output, THE Runner SHALL upload the raw stdout content to S3 at the S3_Key path `{run_identifier}/{trial_identifier}/roundtrip/trade_orders.json`.
2. WHEN the Roundtrip_Output starts with `[` and ends with `]`, THE Runner SHALL set a `jsonValid` field to `true` in the response body.
3. WHEN the Roundtrip_Output does not start with `[` or does not end with `]`, THE Runner SHALL set a `jsonValid` field to `false` in the response body and still upload the raw content to S3.
4. IF the S3 upload fails, THEN THE Runner SHALL return an HTTP 500 response with error code "s3_operation_failed" and include the exception details in the error context.

### Requirement 4: Response Structure

**User Story:** As a benchmark operator, I want a clear response indicating the upload outcome and data validity, so that I can determine whether further investigation is needed.

#### Acceptance Criteria

1. WHEN the roundtrip export completes successfully, THE Runner SHALL return an HTTP 200 response containing the fields: `message`, `s3Key`, `jsonValid`, and `timestamp`.
2. THE Runner SHALL set the `message` field to "Roundtrip data exported successfully" on a successful export.
3. THE Runner SHALL set the `s3Key` field to the full S3 object key where the data was uploaded.
4. THE Runner SHALL set the `timestamp` field to the current UTC time in ISO 8601 format.

### Requirement 5: No Request Body

**User Story:** As a benchmark operator, I want the endpoint to derive all parameters from the initialized configuration, so that I do not need to supply redundant information.

#### Acceptance Criteria

1. THE Runner SHALL derive the `s3_bucket`, `run_identifier`, and `trial_identifier` parameters from BenchmarkState.config for constructing the S3_Key and S3Client.
2. THE Runner SHALL accept `POST /roundtrip/export` requests with no request body.

### Requirement 6: Logging

**User Story:** As a system operator, I want structured log entries for roundtrip export operations, so that I can diagnose issues in production.

#### Acceptance Criteria

1. WHEN the roundtrip export begins, THE Runner SHALL emit a structlog info event with the `run_identifier` and `trial_identifier` bound to the logger context.
2. WHEN the Roundtrip_Query fails, THE Runner SHALL emit a structlog error event including the exit code and stderr output.
3. WHEN the S3 upload succeeds, THE Runner SHALL emit a structlog info event including the S3 key.
4. WHEN the Roundtrip_Output fails JSON validity check, THE Runner SHALL emit a structlog warning event including the first 200 characters of the output.
