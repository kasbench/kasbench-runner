# Requirements Document

## Introduction

This feature replaces the existing GET /metrics placeholder endpoint with a POST /metrics endpoint that queries Prometheus for benchmark metrics and saves the results as JSON files to S3. The endpoint executes a predefined set of PromQL range queries (36 counter-type and 18 gauge-type) against the cluster's Prometheus instance using the `/api/v1/query_range` endpoint, applies configurable interval substitution for rate-based queries, and uploads each result as a separate JSON file under the trial's S3 prefix. It supports an overwrite guard to prevent accidental re-collection of metrics. Range queries use the benchmark's start and end times with a configurable step resolution to retrieve time-series data across the full benchmark duration.

## Glossary

- **Runner**: The KASBench Benchmark Runner FastAPI application
- **Metrics_Endpoint**: The POST /metrics API route that orchestrates metric collection
- **Prometheus_Client**: The internal HTTP client component responsible for executing PromQL range queries against the Prometheus `/api/v1/query_range` endpoint
- **S3_Uploader**: The component responsible for writing metric JSON files to the configured S3 bucket
- **Metrics_Configuration**: The static JSON structures defining counter and gauge metric queries, including metric name, description, PromQL query template, and output file name
- **Interval**: A duration string (e.g., "60s", "5m") used to replace the `__INTERVAL__` placeholder in counter-type PromQL queries
- **Step**: A Prometheus duration string (e.g., "15s", "1m") defining the resolution between data points in a range query
- **Range_Query**: A Prometheus query that returns a matrix of time-series data points between a start and end time at a specified step resolution, executed via the `/api/v1/query_range` endpoint
- **Control_Plane_Node**: The DNS hostname of the Kubernetes control plane passed during initialization, used to construct the Prometheus URL
- **Prometheus_Service**: The Kubernetes service `prometheus-server` in the `monitoring` namespace on port 80, queried via the `/api/v1/query_range` endpoint for range queries
- **Overwrite_Flag**: A boolean request parameter that controls whether existing metric files in S3 may be overwritten

## Requirements

### Requirement 1: Endpoint Accepts POST with Optional Configuration

**User Story:** As a benchmark operator, I want to invoke metrics collection via POST /metrics with optional parameters, so that I can control interval substitution, step resolution, and overwrite behavior.

#### Acceptance Criteria

1. WHEN a POST request is received at /metrics with no request body, THE Metrics_Endpoint SHALL use a default interval value of "60s", a default step value of "15s", and a default overwrite value of false
2. WHEN a POST request is received at /metrics with a JSON body containing an `interval` field, THE Metrics_Endpoint SHALL replace all occurrences of the string literal `__INTERVAL__` in each configured PromQL query with the provided interval value before executing the query
3. WHEN a POST request is received at /metrics with a JSON body containing an `overwrite` field set to true, THE Metrics_Endpoint SHALL upload metric files to S3 regardless of whether an object with the same key already exists
4. WHEN a POST request is received at /metrics with a JSON body containing an `overwrite` field set to false and one or more metric S3 object keys already exist, THE Metrics_Endpoint SHALL not upload any file that would overwrite an existing object and SHALL return an error response indicating which metric names already exist in S3
5. IF a POST request is received at /metrics while the benchmark status is "not-initialized", "not-started", or "running", THEN THE Metrics_Endpoint SHALL return an error response indicating that metrics collection is only available after the benchmark has completed
6. IF a POST request is received at /metrics with a JSON body containing fields other than `interval`, `overwrite`, and `step`, THE Metrics_Endpoint SHALL ignore unrecognized fields and process the request using only `interval`, `overwrite`, and `step`
7. WHEN a POST request is received at /metrics with a JSON body containing a `step` field, THE Metrics_Endpoint SHALL use the provided step value as the step parameter for all Prometheus range query executions
8. WHEN a POST request is received at /metrics without a `step` field in the request body, THE Metrics_Endpoint SHALL use the default step value of "15s" for all Prometheus range query executions

### Requirement 2: State Guard Prevents Premature Collection

**User Story:** As a benchmark operator, I want the system to reject metrics collection when the benchmark has not completed, so that I only collect metrics from valid completed runs.

#### Acceptance Criteria

1. WHILE the Runner status is "not-initialized", WHEN a POST /metrics request is received, THE Metrics_Endpoint SHALL return HTTP 409 with error "benchmark_not_completed", a message indicating that metrics are only available after the benchmark has completed, and the current Runner status in the response body
2. WHILE the Runner status is "not-started", WHEN a POST /metrics request is received, THE Metrics_Endpoint SHALL return HTTP 409 with error "benchmark_not_completed", a message indicating that metrics are only available after the benchmark has completed, and the current Runner status in the response body
3. WHILE the Runner status is "running", WHEN a POST /metrics request is received, THE Metrics_Endpoint SHALL return HTTP 409 with error "benchmark_not_completed", a message indicating that metrics are only available after the benchmark has completed, and the current Runner status in the response body
4. WHILE the Runner status is "success" or "failed" or "aborted", WHEN a POST /metrics request is received, THE Metrics_Endpoint SHALL accept the request and continue to metrics collection processing without returning a state guard error
5. WHEN a POST /metrics request is received with any request body content, THE Metrics_Endpoint SHALL evaluate the state guard before processing the request body parameters

### Requirement 3: Overwrite Protection

**User Story:** As a benchmark operator, I want the system to prevent accidental overwriting of previously collected metrics, so that I do not lose data from prior collection runs.

#### Acceptance Criteria

1. WHEN overwrite is false, THE S3_Uploader SHALL check whether each metric object already exists in S3 before writing any metric objects, completing all existence checks prior to performing any writes
2. IF overwrite is false AND any metric object already exists in S3, THEN THE Metrics_Endpoint SHALL return HTTP 409 with error "metrics_already_exist" and a message listing the names of the existing metrics, and SHALL NOT write any metric objects during that request
3. WHEN overwrite is false AND no metric objects already exist in S3, THE S3_Uploader SHALL write all metric objects to S3
4. WHEN overwrite is true, THE S3_Uploader SHALL write metric objects to S3 without checking for prior existence
5. IF overwrite is false AND the S3 existence check fails due to an S3 operation error, THEN THE Metrics_Endpoint SHALL return HTTP 500 with error "s3_operation_failed" and a message indicating which check failed, and SHALL NOT write any metric objects

### Requirement 4: Prometheus URL Construction

**User Story:** As a benchmark operator, I want the system to dynamically construct the Prometheus endpoint URL from the configured control plane node, so that metrics collection works across different cluster deployments.

#### Acceptance Criteria

1. THE Prometheus_Client SHALL construct the Prometheus range query URL as `http://{controlPlaneNode}:80/api/v1/query_range` where `{controlPlaneNode}` is the value of the `controlPlaneNode` field provided during initialization, used directly as the hostname without additional DNS resolution
2. IF a connection attempt to the constructed Prometheus URL fails due to connection refused, DNS resolution failure, or timeout (using the configured HTTP connect timeout), THEN THE Prometheus_Client SHALL report an error including the attempted URL and the underlying connection error message
3. IF the Prometheus service returns a non-200 HTTP response, THEN THE Prometheus_Client SHALL report an error including the attempted URL, the HTTP status code received, and the response body

### Requirement 5: Interval Substitution in Counter Queries

**User Story:** As a benchmark operator, I want rate-based counter queries to use a configurable time interval, so that I can adjust metric granularity per collection.

#### Acceptance Criteria

1. WHEN a metric query contains the string literal `__INTERVAL__`, THE Prometheus_Client SHALL replace all occurrences of `__INTERVAL__` (case-sensitive, exact match) with the configured interval value (a Prometheus duration string, e.g., "60s") before executing the query
2. WHEN a metric query does not contain the string literal `__INTERVAL__`, THE Prometheus_Client SHALL execute the original query unchanged without any modification
3. IF the configured interval value is empty or blank, THEN THE Prometheus_Client SHALL use the default interval value "60s" for substitution

### Requirement 6: Execute PromQL Range Queries Against Prometheus

**User Story:** As a benchmark operator, I want the system to execute all configured PromQL queries as range queries, so that I can collect time-series performance metrics spanning the full benchmark duration.

#### Acceptance Criteria

1. THE Prometheus_Client SHALL execute each query from both the counter metrics configuration (36 queries) and the gauge metrics configuration (18 queries) as a range query via the `/api/v1/query_range` endpoint, substituting the literal string `__INTERVAL__` in each query template with the configured interval value before execution
2. THE Prometheus_Client SHALL pass the following parameters for each range query: `query` (the PromQL expression after interval substitution), `start` (BenchmarkState.start_time converted to a Unix timestamp in seconds), `end` (BenchmarkState.end_time converted to a Unix timestamp in seconds), and `step` (the step value from the request, defaulting to "15s")
3. WHEN a PromQL range query returns an HTTP 200 response with Prometheus API status "success" and result type "matrix", THE Prometheus_Client SHALL pass the full JSON response body to the S3_Uploader for storage as a .json file using the S3 key format `{runIdentifier}/{trialIdentifier}/metrics/{name}` where `name` is the configured name for that metric
4. IF a PromQL range query returns a non-200 HTTP status or a Prometheus API response with status "error", THEN THE Prometheus_Client SHALL record the metric name and error message and continue processing remaining queries without halting
5. IF the Prometheus endpoint is unreachable (connection refused, DNS resolution failure, or per-query timeout exceeding 30 seconds), THEN THE Prometheus_Client SHALL record the metric name and connection error and continue processing remaining queries
6. WHEN all configured metrics have been processed, THE Prometheus_Client SHALL return a summary indicating overall success if no errors occurred or failure if one or more queries produced errors, including the metric name and error message for each failed query

### Requirement 7: Store Metric Results as JSON in S3

**User Story:** As a benchmark operator, I want metric results stored as individual JSON files in S3 under a predictable path, so that downstream analysis tools can locate and process them.

#### Acceptance Criteria

1. WHEN the S3_Uploader stores a metric result, THE S3_Uploader SHALL write a valid JSON file at the S3 path `{runIdentifier}/{trialIdentifier}/metrics/{name}` where `name` is the metric name string from the predefined metrics query list, `runIdentifier` is the run identifier provided during initialization, and `trialIdentifier` is the trial identifier provided during initialization
2. THE S3_Uploader SHALL use the `s3Bucket` configured during initialization as the target bucket for all metric uploads
3. THE S3_Uploader SHALL set the content type of uploaded files to "application/json"
4. IF an S3 upload operation fails for a metric file, THEN THE S3_Uploader SHALL report an error indicating which metric file failed and the reason for the failure

### Requirement 8: Aggregate Error Reporting

**User Story:** As a benchmark operator, I want a clear summary of which metrics failed and why, so that I can diagnose and resolve issues without re-running the entire collection.

#### Acceptance Criteria

1. WHEN all metric queries and uploads succeed, THE Metrics_Endpoint SHALL return HTTP 200 with a response body containing a message indicating successful collection, the count of metric files uploaded (one per configured metric query), and the S3 prefix where files were stored
2. WHEN one or more metric queries or uploads fail, THE Metrics_Endpoint SHALL return HTTP 207 with a response body containing a list of error entries (each including the metric query name, the phase that failed being query or upload, and the error description), the count of successfully uploaded metrics, and the total count of configured metrics attempted
3. THE Metrics_Endpoint SHALL attempt all configured metric queries and their corresponding uploads before returning a response, accumulating errors from each failed metric rather than aborting on the first failure
4. IF the benchmark status is not "success" or "failed" WHEN the Metrics_Endpoint is called, THEN THE Metrics_Endpoint SHALL return HTTP 409 with an error message indicating that metrics collection requires a completed benchmark, and include the current benchmark status in the response

### Requirement 9: Metrics Configuration Maintainability

**User Story:** As a developer, I want the metrics configuration stored in a dedicated module separate from business logic, so that adding or modifying metrics requires minimal code changes.

#### Acceptance Criteria

1. THE Runner SHALL store counter and gauge metric configurations in a dedicated Python module that contains only metric definitions and no query-execution, S3-upload, or route-handler logic
2. THE Metrics_Configuration SHALL define each metric with fields: metric type (counter or gauge), metric name, description, PromQL query template (which may contain substitution placeholders such as `__INTERVAL__`), and output file name
3. WHEN a new metric entry is added to the configuration module, THE Runner SHALL query Prometheus and upload results to S3 for that metric without requiring modifications to any other Python module
4. THE Runner SHALL iterate the metrics configuration data structure generically so that the query-execution and upload logic contains no metric-specific references or conditional branches per metric

### Requirement 10: README Documentation Update

**User Story:** As a developer, I want the README to reflect the new POST /metrics endpoint behavior, so that users have accurate API documentation.

#### Acceptance Criteria

1. THE Runner documentation SHALL describe the POST /metrics endpoint in the API Reference section including: the HTTP method and path, the optional request body fields (`overwrite` with type and default, `interval` with type and default, `step` with type and default of "15s"), the success response format with fields returned, the error response HTTP status codes (for invalid state and overwrite conflict), and the allowed benchmark states for calling the endpoint
2. THE Runner documentation SHALL replace the existing GET /metrics entry in the API Reference section and its corresponding usage examples with POST /metrics documentation, removing all references to the former GET method for metrics collection
3. THE Runner documentation SHALL include at least one POST /metrics usage example showing a curl request with a request body containing `overwrite`, `interval`, and `step` fields, and at least one example showing the error response when the benchmark has not completed

### Requirement 11: Range Query Time Bounds

**User Story:** As a benchmark operator, I want range queries to use the benchmark's actual start and end times, so that collected metrics span precisely the benchmark execution window.

#### Acceptance Criteria

1. THE Metrics_Endpoint SHALL use BenchmarkState.start_time as the range query start parameter, where start_time is the UTC datetime recorded when POST /start was called
2. THE Metrics_Endpoint SHALL use BenchmarkState.end_time as the range query end parameter, where end_time is the latest end_time across all load generator roles recorded when GET /status detects benchmark completion
3. THE Metrics_Endpoint SHALL convert both start_time and end_time to Unix timestamps (seconds since epoch) before passing them to the Prometheus range query API
4. IF BenchmarkState.start_time is None when POST /metrics is called, THEN THE Metrics_Endpoint SHALL return HTTP 500 with error "missing_time_bounds" and a message indicating that the benchmark start time is not available
5. IF BenchmarkState.end_time is None when POST /metrics is called, THEN THE Metrics_Endpoint SHALL return HTTP 500 with error "missing_time_bounds" and a message indicating that the benchmark end time is not available
