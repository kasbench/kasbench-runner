# Requirements Document

## Introduction

This feature adds a new API endpoint `POST /logs/{namespace}/export` to the KASBench Benchmark Runner. The endpoint collects Kubernetes pod logs from all pods in a specified namespace and uploads them to S3. It captures logs from all containers across all pods regardless of pod status (Running, Succeeded, Failed), including completed or failed jobs, enabling comprehensive post-benchmark log analysis.

## Glossary

- **Runner**: The KASBench Benchmark Runner FastAPI microservice
- **Log_Exporter**: The service component responsible for collecting Kubernetes pod logs and uploading them to S3
- **Namespace**: A Kubernetes namespace identifier provided as a path parameter
- **Pod**: A Kubernetes pod object within the specified namespace
- **Container**: A container running within a Kubernetes pod
- **Single_Container_Pod**: A pod containing exactly one container
- **Multi_Container_Pod**: A pod containing more than one container
- **S3_Prefix**: The S3 key path prefix in the format `{runIdentifier}/{trialIdentifier}/logs/{namespace}/`
- **BenchmarkState**: The application-level state object tracking benchmark lifecycle

## Requirements

### Requirement 1: Endpoint Registration and Routing

**User Story:** As a benchmark operator, I want a dedicated endpoint to export Kubernetes logs from any namespace, so that I can collect diagnostic data after a benchmark trial.

#### Acceptance Criteria

1. THE Runner SHALL expose a `POST /logs/{namespace}/export` endpoint that accepts a namespace path parameter.
2. WHEN a request is received at `POST /logs/{namespace}/export`, THE Runner SHALL interpret the `{namespace}` path parameter as the target Kubernetes namespace for log collection.

### Requirement 2: State Guard

**User Story:** As a benchmark operator, I want the logs endpoint to reject requests before initialization, so that required configuration (S3 bucket, run identifier, trial identifier) is available.

#### Acceptance Criteria

1. WHEN a request is received and BenchmarkState status is `not-initialized`, THE Runner SHALL return HTTP 409 with error `not_initialized` and a message indicating that the benchmark has not been initialized.
2. WHILE BenchmarkState status is any value other than `not-initialized`, THE Runner SHALL accept and process the log export request.

### Requirement 3: Pod Discovery

**User Story:** As a benchmark operator, I want all pods in the namespace to be included regardless of their status, so that I capture logs from completed, failed, and running workloads.

#### Acceptance Criteria

1. WHEN processing a log export request, THE Log_Exporter SHALL query the Kubernetes API for all pods in the specified namespace.
2. THE Log_Exporter SHALL include pods in any phase (Running, Succeeded, Failed, Pending, Unknown) in the collection set.
3. THE Log_Exporter SHALL include pods belonging to completed or failed Jobs in the collection set.

### Requirement 4: Container Log Collection

**User Story:** As a benchmark operator, I want logs from all containers within each pod to be collected, so that I have complete diagnostic data for multi-container workloads.

#### Acceptance Criteria

1. WHEN a pod is discovered, THE Log_Exporter SHALL collect logs from every container within that pod that has available log output.
2. IF a container has no available logs (container never started or logs are inaccessible), THEN THE Log_Exporter SHALL skip that container and continue processing remaining containers.

### Requirement 5: File Naming Convention

**User Story:** As a benchmark operator, I want log files to be clearly named by pod and container, so that I can easily identify the source of each log file.

#### Acceptance Criteria

1. WHEN uploading logs from a Single_Container_Pod, THE Log_Exporter SHALL name the file `{pod_name}.log`.
2. WHEN uploading logs from a Multi_Container_Pod, THE Log_Exporter SHALL name the file `{pod_name}-{container_name}.log` for each container.

### Requirement 6: S3 Upload Path

**User Story:** As a benchmark operator, I want logs organized in a consistent S3 path structure, so that I can locate them alongside other trial artifacts.

#### Acceptance Criteria

1. THE Log_Exporter SHALL upload each log file to the S3 key `{runIdentifier}/{trialIdentifier}/logs/{namespace}/{filename}` where `{filename}` follows the naming convention from Requirement 5.
2. THE Log_Exporter SHALL use the S3 bucket configured during initialization (from BenchmarkState config `s3_bucket`).

### Requirement 7: Success Response

**User Story:** As a benchmark operator, I want a clear summary of the export operation, so that I know how many logs were collected and where they were stored.

#### Acceptance Criteria

1. WHEN all log files are uploaded successfully, THE Runner SHALL return HTTP 200 with a JSON body containing: `message`, `filesExported` (count of uploaded files), `s3Prefix` (the full S3 prefix used), and `timestamp` (ISO 8601 UTC).
2. WHEN some log collections or uploads fail but at least one succeeds, THE Runner SHALL return HTTP 207 with a JSON body containing: `message`, `filesExported` (count of successfully uploaded files), `s3Prefix`, `errors` (array of error objects with `pod`, `container`, `phase`, and `error` fields), and `timestamp`.

### Requirement 8: Error Handling

**User Story:** As a benchmark operator, I want the export to be best-effort so that a single pod failure does not prevent collecting logs from other pods.

#### Acceptance Criteria

1. IF a log collection fails for a specific pod or container, THEN THE Log_Exporter SHALL record the error and continue processing remaining pods and containers.
2. IF an S3 upload fails for a specific log file, THEN THE Log_Exporter SHALL record the error and continue uploading remaining log files.
3. IF no pods are found in the specified namespace, THEN THE Runner SHALL return HTTP 200 with `filesExported` set to 0.
4. IF the Kubernetes API is unreachable or returns an error during pod listing, THEN THE Runner SHALL return HTTP 500 with error `kubernetes_error` and a descriptive message.

### Requirement 9: README Documentation

**User Story:** As a developer, I want the README to document the new endpoint, so that API consumers can understand its usage.

#### Acceptance Criteria

1. WHEN this feature is implemented, THE Runner project README SHALL include an API reference section for `POST /logs/{namespace}/export` documenting: the endpoint path, request parameters, success response format, error responses, and allowed states.
2. WHEN this feature is implemented, THE Runner project README SHALL include a usage example showing a curl command for the `POST /logs/{namespace}/export` endpoint.
