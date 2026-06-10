# Requirements Document

## Introduction

The KASBench Benchmark Runner is a Python FastAPI microservice that orchestrates Kubernetes cluster setup, GlobeCo application deployment, and load generator management for the KASBench benchmarking framework. It runs inside a Docker container on the Benchmark Runner node within the `kasbench` Docker network. The Runner is invoked by the Benchmark Controller and is responsible for configuring Kubernetes via SSH on remote nodes, deploying application manifests, launching five load generator containers, starting and monitoring benchmark runs, and collecting results to S3.

## Glossary

- **Runner**: The KASBench Benchmark Runner FastAPI application
- **Controller**: The KASBench Benchmark Controller that invokes the Runner from the Bastion Host
- **Load_Generator**: A KASBench Load Generator instance (Docker container running the `kasbench/kasbench-load-generator` image)
- **Control_Plane_Node**: The Kubernetes control plane node accessed via SSH
- **Worker_Node**: A Kubernetes worker node (either AMD64 or AARCH64 architecture) accessed via SSH
- **Benchmark_Status**: The Runner's internal lifecycle state: `not_initialized`, `not-started`, `running`, `success`, `failed`, or `aborted`
- **Role**: One of the five load generator profiles: `back-office`, `portfolio-manager`, `trader`, `investor`, `it-operations`
- **Trial**: A single benchmark execution within a run, identified by `trial_identifier`
- **S3_Bucket**: The AWS S3 bucket used for trial reservation and artifact storage
- **kasbench_Network**: The Docker bridge network (`kasbench`) on which the Runner and Load Generators communicate
- **Manifest_List**: A `k8s.lst` file from a GitHub repository that defines Kubernetes resources to apply
- **Health_Check**: An HTTP GET request to a Load Generator's `/health` endpoint to verify operational status
- **Node_Readiness**: The state where a Kubernetes node reports `Ready` condition via the kr8s library

## Requirements

### Requirement 1: Application Lifecycle and State Management

**User Story:** As the Benchmark Controller, I want the Runner to track its internal lifecycle state, so that I can determine whether the Runner is ready to accept commands.

#### Acceptance Criteria

1. WHEN the Runner application starts, THE Runner SHALL set Benchmark_Status to `not_initialized`
2. WHEN POST /initialize completes successfully (all internal flags `kubernetes_installed`, `globeco_installed`, and `load_generators_installed` are True), THE Runner SHALL set Benchmark_Status to `not-started`
3. WHEN POST /start completes successfully (all Load Generators confirm `running` status), THE Runner SHALL set Benchmark_Status to `running`
4. WHEN GET /status is received and all Load Generators report status `success` via their /health endpoint, THE Runner SHALL set Benchmark_Status to `success` and record the latest endTime across all roles as the internal `end_time`
5. WHEN GET /status is received and any Load Generator reports status `failed` via their /health endpoint, THE Runner SHALL set Benchmark_Status to `failed` and record the earliest endTime among failed generators as the internal `end_time`
6. THE Runner SHALL persist the request object from POST /initialize in memory so that settings are available to subsequent API calls for the lifetime of the process
7. IF POST /initialize is received and Benchmark_Status is not `not_initialized`, THEN THE Runner SHALL return HTTP 409 with a message indicating that the Runner has already been initialized
8. WHEN POST /abort completes successfully, THE Runner SHALL set Benchmark_Status to `aborted` and record the current UTC timestamp as the internal `end_time`

### Requirement 2: POST /initialize Request Validation

**User Story:** As the Benchmark Controller, I want the Runner to validate the initialization request, so that configuration errors are detected before any provisioning begins.

#### Acceptance Criteria

1. WHEN a POST /initialize request is received, THE Runner SHALL validate that all required fields (`autoscaler`, `controlPlaneNode`, `amdWorkerNodes`, `armWorkerNodes`, `s3Bucket`, `globecoUrl`) are present and non-empty (strings must be non-blank, arrays must be non-empty)
2. WHEN a required field is missing or empty in the request, THE Runner SHALL return HTTP 422 with a JSON body identifying each invalid field and the reason (missing or empty)
3. WHEN an optional field is absent from the request, THE Runner SHALL apply the documented default value for that field
4. THE Runner SHALL accept the following optional fields with their defaults: `runIdentifier` ("run001"), `trialIdentifier` ("trial001"), `clusterCidrRange` ("10.244.0.0/16"), `kubernetesVersion` ("1.36.1"), `loadGeneratorImage` ("kasbench/kasbench-load-generator:latest"), `runDurationMinutes` (5), `globecoPort` (8080), `skipKubernetesInstall` (false), `skipManifestInstall` (false), `forceManifestInstall` (false)
5. IF a field value has an incorrect type (e.g., string where integer expected, or integer where array expected), THEN THE Runner SHALL return HTTP 422 with a message identifying the field name, the expected type, and the received type

### Requirement 3: S3 Trial Reservation

**User Story:** As the Benchmark Controller, I want the Runner to reserve a unique trial identifier in S3, so that duplicate trials within the same run are prevented.

#### Acceptance Criteria

1. WHEN POST /initialize passes request validation, THE Runner SHALL perform a conditional write of an empty file at path `{run_identifier}/{trial_identifier}/reserved` in the designated S3_Bucket using boto3 `s3.put_object` with `IfNoneMatch="*"`
2. IF the S3 `put_object` call raises a ClientError with error code `PreconditionFailed`, THEN THE Runner SHALL return HTTP 409 with a message indicating the trial identifier `{trial_identifier}` is already reserved for run `{run_identifier}`
3. IF the S3 `put_object` call raises any other exception, THEN THE Runner SHALL return HTTP 500 with the exception class name, message, and the S3 bucket and key path included in the response

### Requirement 4: Kubernetes Cluster Installation

**User Story:** As the Benchmark Controller, I want the Runner to configure a Kubernetes cluster on remote nodes via SSH, so that the benchmark environment is prepared automatically.

#### Acceptance Criteria

1. IF `skipKubernetesInstall` is true in the request, THEN THE Runner SHALL skip all Kubernetes installation steps and proceed to manifest installation
2. WHEN Kubernetes installation begins, THE Runner SHALL SSH to the Control_Plane_Node and execute `kubeadm init` with the configured `kubernetes_version` and `cluster_cidr_range`
3. WHEN `kubeadm init` completes, THE Runner SHALL copy the kubeconfig from the Control_Plane_Node to the local `$HOME/.kube/config` path via SCP
4. WHEN the kubeconfig is copied, THE Runner SHALL SSH to the Control_Plane_Node and execute the Flannel network installation script at `/home/ubuntu/flannel-install.sh`
5. WHEN Flannel installation completes, THE Runner SHALL SSH to the Control_Plane_Node and execute `kubeadm token create --print-join-command` to obtain the cluster join token
6. WHEN the join token is obtained, THE Runner SHALL SSH to each node in `amd_worker_nodes` and `arm_worker_nodes` and execute the `kubeadm join` command with the obtained token
7. WHEN all join commands have executed, THE Runner SHALL use the kr8s library to poll node status every 10 seconds and verify that all nodes (1 control plane + len(amd_worker_nodes) + len(arm_worker_nodes)) reach Ready state within a configurable timeout (default 300 seconds)
8. WHILE waiting for Node_Readiness, THE Runner SHALL log at each polling iteration the count of nodes currently in Ready state versus the expected total node count
9. IF any node reports a condition with status `False` for `Ready` and a reason containing `NetworkNotReady`, `KubeletNotReady`, or `ContainerRuntimeNotReady` for more than 120 seconds, THEN THE Runner SHALL stop polling immediately and return HTTP 500 with the node name and the reported condition reason
10. IF the readiness timeout expires before all nodes are ready, THEN THE Runner SHALL return HTTP 500 listing which nodes failed to reach Ready state and their last reported condition
11. WHEN all nodes are ready, THE Runner SHALL create Kubernetes namespaces: `globeco`, `monitoring`, `elasticsearch`, and `observability` (skipping creation if a namespace already exists)
12. WHEN namespaces are created, THE Runner SHALL install the AWS EBS CSI driver via Helm and create the `ebs-gp3` StorageClass if it does not already exist
13. IF any step in the Kubernetes installation sequence (kubeadm init, SCP, Flannel install, token creation, kubeadm join, namespace creation, or Helm install) fails with a non-zero exit code or exception, THEN THE Runner SHALL return HTTP 500 with the failed step name, the target node (if applicable), the command executed, and the error output
14. WHEN Kubernetes installation completes successfully, THE Runner SHALL set internal variable `kubernetes_installed` to True

### Requirement 5: Manifest Installation

**User Story:** As the Benchmark Controller, I want the Runner to deploy GlobeCo application manifests from GitHub repositories, so that the system under test is running in Kubernetes.

#### Acceptance Criteria

1. WHEN `skipManifestInstall` is true in the request, THE Runner SHALL skip all manifest installation steps and proceed to load generator deployment
2. WHEN manifest installation begins, THE Runner SHALL iterate through the configured list of 13 GitHub repositories in the defined order: globeco-kafka, globeco-confirmation-service, globeco-execution-service, globeco-fix-engine, globeco-order-generation-service, globeco-order-service, globeco-portfolio-accounting-service, globeco-portfolio-management-portal, globeco-portfolio-service, globeco-pricing-service, globeco-security-service, globeco-trade-service, globeco-observability
3. WHEN processing a repository, THE Runner SHALL fetch the file at `https://raw.githubusercontent.com/{owner}/{repo}/{tag}/k8s_aws/k8s.lst` with a request timeout of 30 seconds
4. IF fetching the k8s.lst file fails or returns a non-200 HTTP status code, THEN THE Runner SHALL return HTTP 500 with the repository name and HTTP status code from GitHub
5. WHEN parsing a line from k8s.lst, THE Runner SHALL ignore blank lines (zero-length or whitespace-only) and lines beginning with `#`
6. WHEN a line begins with `>`, THE Runner SHALL execute the remainder of the line as a shell command, capture both stdout and stderr, and log the combined output
7. WHEN a line begins with `+` followed by a valid integer greater than zero, THE Runner SHALL sleep for that number of seconds
8. IF a line begins with `+` followed by a non-integer value or an integer less than or equal to zero, THEN THE Runner SHALL log a warning and sleep for 30 seconds
9. WHEN a line does not match any special prefix (`#`, `>`, `+`) and is not blank, THE Runner SHALL treat it as a manifest filename, append `.yaml` if the filename does not already end in `.yaml`, and issue a warning log entry when appending
10. WHEN applying a manifest, THE Runner SHALL execute `kubectl apply -f https://raw.githubusercontent.com/{owner}/{repo}/{tag}/k8s_aws/{manifest-filename}`
11. IF a shell command execution (from `>` lines) or `kubectl apply` returns a non-zero exit code and `forceManifestInstall` is false, THEN THE Runner SHALL return HTTP 500 with the specific command executed, the repository name, and the stderr output
12. IF a shell command execution (from `>` lines) or `kubectl apply` returns a non-zero exit code and `forceManifestInstall` is true, THEN THE Runner SHALL log the error including the command, repository name, and stderr output, and continue processing subsequent lines
13. WHEN all 13 repositories are processed successfully, THE Runner SHALL set internal variable `globeco_installed` to True

### Requirement 6: Load Generator Deployment

**User Story:** As the Benchmark Controller, I want the Runner to deploy five Load Generator containers on the kasbench Docker network, so that they are ready to generate benchmark load.

#### Acceptance Criteria

1. WHEN load generator deployment begins, THE Runner SHALL verify that the `kasbench` Docker network exists
2. IF the `kasbench` Docker network does not exist, THEN THE Runner SHALL return HTTP 500 with a message indicating the network must be pre-created
3. WHEN the network is verified, THE Runner SHALL start a RabbitMQ container named `rabbitmq` using the configured RabbitMQ image (default: `rabbitmq:4-management`) on the `kasbench` network with host ports 5672 and 15672 mapped to container ports 5672 and 15672
4. WHEN the RabbitMQ `docker run` command completes successfully, THE Runner SHALL start five Load_Generator containers on the `kasbench` network with the configured `load_generator_image`, each with host port mapped to container port 8080 (back-office:8081, portfolio-manager:8082, trader:8083, investor:8084, it-operations:8085), container name set to the role name, and environment variable `RABBITMQ_HOST=rabbitmq`
5. IF a `docker run` command fails for any container, THEN THE Runner SHALL return HTTP 500 with the container name, role, and error output
6. IF a container with the same name already exists (running or stopped) on the expected port, THEN THE Runner SHALL log a warning and continue without failure
7. WHEN all containers are started, THE Runner SHALL perform a Health_Check on each Load_Generator by calling `GET http://{role}:8080/health`
8. THE Runner SHALL retry each Health_Check up to 3 times with a 5-second wait between the end of one failed attempt and the start of the next attempt
9. WHEN a Health_Check succeeds with HTTP 200 and a JSON response body containing `Status` equal to `not-started` and `Health` equal to `healthy`, THE Runner SHALL mark that Load_Generator as verified
10. IF any Load_Generator fails all 3 Health_Check attempts, THEN THE Runner SHALL return HTTP 500 identifying the failed role and the last error received
11. WHEN all five Load Generators are verified, THE Runner SHALL set internal variable `load_generators_installed` to True
12. IF `kubernetes_installed`, `globeco_installed`, and `load_generators_installed` are all True, THEN THE Runner SHALL set `initialization_complete` to True and Benchmark_Status to `not-started`

### Requirement 7: POST /start Benchmark Execution

**User Story:** As the Benchmark Controller, I want to start the benchmark run, so that all load generators begin producing traffic simultaneously.

#### Acceptance Criteria

1. WHEN POST /start is received and `initialization_complete` is false, THE Runner SHALL return HTTP 409 with a message indicating initialization has not completed
2. WHEN POST /start is received and Benchmark_Status is `running`, THE Runner SHALL return HTTP 409 with a message indicating a benchmark is already in progress
3. WHEN POST /start is valid, THE Runner SHALL record `benchmark_start_time` as the current UTC timestamp
4. WHEN starting load generators, THE Runner SHALL POST to each Load_Generator's `/start` endpoint with the JSON payload containing Role, BenchmarkLengthMinutes (from `run_duration_minutes`), BaseLoadIntensity, SpawnRate, BaseDelayPercentage, and KasbenchUrl (constructed as `{globeco_url}:{globeco_port}`) using the role-specific parameters: back-office (BaseLoadIntensity=100, BaseDelayPercentage=100, SpawnRate=10), portfolio-manager (BaseLoadIntensity=100, BaseDelayPercentage=100, SpawnRate=10), trader (BaseLoadIntensity=100, BaseDelayPercentage=100, SpawnRate=10), investor (BaseLoadIntensity=10, BaseDelayPercentage=100, SpawnRate=10), it-operations (BaseLoadIntensity=100, BaseDelayPercentage=100, SpawnRate=1)
5. THE Runner SHALL issue all five POST /start requests concurrently (e.g., via asyncio.gather) to start all Load Generators as close to simultaneously as possible
6. IF any Load_Generator POST /start request returns a non-200 HTTP status code, THEN THE Runner SHALL return HTTP 500 with the failed role, the HTTP status code received, and the response body
7. WHEN all start requests return HTTP 200, THE Runner SHALL verify each Load_Generator reports status `running` and health `healthy` via Health_Check
8. THE Runner SHALL retry each post-start Health_Check up to 3 times with 5-second intervals
9. IF any Load_Generator fails to report `running` status after 3 Health_Check attempts, THEN THE Runner SHALL return HTTP 500 identifying the failed role and last observed status
10. WHEN all Load Generators confirm `running` status, THE Runner SHALL set Benchmark_Status to `running` and return HTTP 200 with the benchmark start timestamp

### Requirement 8: GET /status Benchmark Monitoring

**User Story:** As the Benchmark Controller, I want to query the benchmark status, so that I can monitor progress and detect completion or failure.

#### Acceptance Criteria

1. WHEN GET /status is received and Benchmark_Status is `not_initialized`, THE Runner SHALL return HTTP 200 with `{"status": "not-initialized", "startTime": null, "endTime": null, "loadGenerators": []}`
2. WHEN GET /status is received and Benchmark_Status is not `not_initialized`, THE Runner SHALL query each Load_Generator's `/health` endpoint with a timeout of 5 seconds per request to retrieve current status, startTime, and endTime
3. WHEN all Load Generators report status `success`, THE Runner SHALL set Benchmark_Status to `success` and set the internal `end_time` to the latest endTime across all roles
4. WHEN any Load Generator reports status `failed`, THE Runner SHALL set Benchmark_Status to `failed` and set the internal `end_time` to the earliest endTime among failed generators
5. WHEN the aggregated Load Generator statuses include no `failed` and not all `success` (e.g., some report `running` or `not-started`), THE Runner SHALL leave Benchmark_Status unchanged
6. WHEN GET /status is received and Benchmark_Status is not `not_initialized`, THE Runner SHALL return HTTP 200 containing: overall status, benchmark startTime (null if not yet started), benchmark endTime (null if not yet ended), and an array of load generator objects each with role, status, startTime, and endTime
7. IF querying any Load_Generator health endpoint fails or exceeds the 5-second timeout, THEN THE Runner SHALL return HTTP 500 with the role name and connection error details

### Requirement 9: GET /output/{role} Log Forwarding

**User Story:** As the Benchmark Controller, I want to download the stdout/stderr output from a specific Load Generator, so that I can collect logs for analysis.

#### Acceptance Criteria

1. WHEN GET /output/{role} is received with a valid role, THE Runner SHALL forward the request to `GET http://{role}:8080/download-output` using a streaming connection that does not buffer the entire response body in memory
2. WHEN the Load_Generator returns HTTP 200 with text/plain content, THE Runner SHALL stream the response body to the client with content type `text/plain`
3. IF the Load_Generator returns HTTP 409, THEN THE Runner SHALL return HTTP 409 indicating the load generator subprocess is still active
4. IF the Load_Generator returns HTTP 404, THEN THE Runner SHALL return HTTP 404 indicating no output is available
5. IF the role parameter does not match a valid Role, THEN THE Runner SHALL return HTTP 400 with the invalid role value and the list of valid roles (back-office, portfolio-manager, trader, investor, it-operations)
6. IF the Runner cannot establish a connection to the Load_Generator within 10 seconds, THEN THE Runner SHALL return HTTP 502 with the role name and connection error details

### Requirement 10: GET /db/{role} Database Forwarding

**User Story:** As the Benchmark Controller, I want to download the SQLite database from a specific Load Generator, so that I can collect detailed request metrics.

#### Acceptance Criteria

1. WHEN GET /db/{role} is received with a valid role, THE Runner SHALL forward the request to `GET http://{role}:8080/download-db` using a streaming connection that does not buffer the entire response body in memory
2. WHEN the Load_Generator returns HTTP 200 with application/x-sqlite3 content, THE Runner SHALL stream the response body to the client with content type `application/x-sqlite3`
3. IF the Load_Generator returns HTTP 409, THEN THE Runner SHALL return HTTP 409 indicating the load generator subprocess is still active
4. IF the Load_Generator returns HTTP 404, THEN THE Runner SHALL return HTTP 404 indicating the database file is not available
5. IF the role parameter does not match a valid Role, THEN THE Runner SHALL return HTTP 400 with the invalid role value and the list of valid roles (back-office, portfolio-manager, trader, investor, it-operations)
6. IF the Runner cannot establish a connection to the Load_Generator within 10 seconds, THEN THE Runner SHALL return HTTP 502 with the role name and connection error details
7. IF the Load_Generator returns an HTTP status code other than 200, 404, or 409, THEN THE Runner SHALL return HTTP 502 with the role name, the upstream status code, and any response body text

### Requirement 11: Error Handling Philosophy

**User Story:** As a developer debugging benchmark failures, I want error responses to contain maximum diagnostic detail, so that I can identify and resolve issues without additional investigation.

#### Acceptance Criteria

1. WHEN any operation fails, THE Runner SHALL return an HTTP response with a status code appropriate to the failure category (4xx for client errors, 5xx for server errors)
2. THE Runner SHALL return every error response as a JSON object containing at minimum the following fields: `error` (string describing the specific operation that failed), `message` (the underlying error message or exception text), `context` (object containing operation-specific diagnostic fields such as node hostname, container name, command executed, role, or target URL as applicable to the failure), and `timestamp` (ISO 8601 UTC timestamp of when the error occurred)
3. THE Runner SHALL NOT obfuscate, redact, or minimize error details for security purposes
4. WHEN an SSH command fails on a remote node, THE Runner SHALL include in the error response context: the target node hostname, the full command that was executed, the integer exit code, and the complete stderr output
5. WHEN a Docker operation fails, THE Runner SHALL include in the error response context: the container name, the Docker image name, the operation attempted (run, stop, remove), and the complete error output from the Docker daemon
6. WHEN an HTTP request to a Load_Generator fails or returns a non-success status, THE Runner SHALL include in the error response context: the target URL, the HTTP method, the HTTP status code received (or connection error description), and the response body text (up to 10,000 characters)

### Requirement 12: SSH Remote Command Execution

**User Story:** As the Runner application, I want to execute commands on remote nodes via SSH, so that I can configure Kubernetes across the cluster.

#### Acceptance Criteria

1. THE Runner SHALL use SSH (via paramiko or asyncssh) to connect to remote nodes as the `ubuntu` user using the default SSH key available in the container, with a connection timeout of 30 seconds
2. WHEN executing a remote command, THE Runner SHALL capture both stdout and stderr separately
3. IF a remote command exits with a non-zero exit code, THEN THE Runner SHALL raise an error including the hostname, command, exit code, and stderr content
4. IF the SSH connection cannot be established within the 30-second timeout, THEN THE Runner SHALL raise an error including the target hostname and the connection error description
5. THE Runner SHALL use structured logging to record each SSH command executed, the target host, and the outcome (success with exit code 0, or failure with exit code and stderr summary)
6. WHEN copying files from remote nodes (SCP), THE Runner SHALL create the destination directory if it does not exist before writing

### Requirement 13: Structured Logging

**User Story:** As a developer, I want the Runner to produce structured log output, so that benchmark runs can be debugged and audited effectively.

#### Acceptance Criteria

1. THE Runner SHALL produce structured log entries in JSON format, where each entry includes at minimum a timestamp (ISO 8601 with UTC timezone), a log level (DEBUG, INFO, WARNING, ERROR), an event name, and operation-specific fields
2. WHEN an SSH command is executed, THE Runner SHALL log at INFO level the target hostname, the full command string, the exit code, and whether the command succeeded or failed
3. WHEN a Docker operation is performed, THE Runner SHALL log at INFO level the container name, the operation type (run, stop, remove, inspect), and the outcome (success or failure with exit code)
4. WHEN a Health_Check is performed, THE Runner SHALL log at INFO level the target role, the current attempt number out of maximum attempts, the HTTP response status code, and the body status field value
5. WHEN a manifest is applied, THE Runner SHALL log at INFO level the repository name, the manifest filename, and whether kubectl apply succeeded or failed including the exit code
6. WHEN node readiness is being polled, THE Runner SHALL log at INFO level the count of ready nodes versus expected nodes at each polling iteration
7. IF any operation fails, THEN THE Runner SHALL log at ERROR level with the same structured fields as the corresponding INFO entry plus the error message or stderr output

### Requirement 14: Health Check Retry Mechanism

**User Story:** As the Runner application, I want to retry health checks with configurable attempts and intervals, so that transient startup delays do not cause premature failures.

#### Acceptance Criteria

1. THE Runner SHALL implement a reusable health check function that accepts: target URL, maximum attempt count (where the first call counts as attempt 1), interval in seconds between attempts, per-attempt connection timeout in seconds, and expected response conditions specified as an HTTP status code and a set of JSON field-value pairs to match in the response body
2. WHEN a Health_Check attempt receives a non-matching response (wrong HTTP status, missing/mismatched JSON fields) or a connection error, THE Runner SHALL wait the configured interval before the next attempt
3. WHEN all attempts are exhausted without a successful match, THE Runner SHALL return a failure result containing the last HTTP status code received (or connection error description), the last response body (if any), and the total number of attempts made
4. WHEN a Health_Check attempt matches all expected conditions, THE Runner SHALL return a success result immediately without waiting or making further attempts
5. THE Runner SHALL log each Health_Check attempt at INFO level including the attempt number (e.g., "2/3"), target URL, HTTP status code received, and whether the expected conditions were met

### Requirement 15: Docker Network Validation

**User Story:** As the Runner application, I want to verify the Docker network exists before deploying containers, so that networking failures are caught early with clear error messages.

#### Acceptance Criteria

1. WHEN load generator deployment begins, THE Runner SHALL verify the `kasbench` Docker network exists by querying the Docker daemon (via Docker API or CLI `docker network inspect kasbench`)
2. IF the `kasbench` network does not exist, THEN THE Runner SHALL return HTTP 500 with a message stating "Docker network 'kasbench' does not exist. It must be created before initialization."
3. IF the Docker daemon is not accessible (connection refused or timeout), THEN THE Runner SHALL return HTTP 500 with a message stating "Cannot connect to Docker daemon. Ensure Docker is running and accessible."
4. THE Runner SHALL NOT attempt to create the Docker network itself

### Requirement 16: POST /abort (Placeholder)

**User Story:** As the Benchmark Controller, I want to abort a running benchmark, so that I can terminate a trial early if needed.

#### Acceptance Criteria

1. WHEN POST /abort is received and Benchmark_Status is `running`, THE Runner SHALL call POST /abort on all five Load Generators concurrently (best-effort: attempt all five regardless of individual failures)
2. WHEN at least one Load Generator confirms abort (returns HTTP 200), THE Runner SHALL set Benchmark_Status to `aborted` and record the current UTC timestamp as the internal `end_time`
3. IF any Load Generator returns a non-200 response during abort, THE Runner SHALL log a warning with the role name and the error received but not fail the overall abort operation
4. WHEN the abort operation completes, THE Runner SHALL return HTTP 200 with a JSON response containing the abort timestamp and the individual result for each role (success or error message)
5. IF POST /abort is received and Benchmark_Status is not `running`, THEN THE Runner SHALL return HTTP 409 indicating no benchmark is currently running

### Requirement 17: GET /metrics (Placeholder)

**User Story:** As the Benchmark Controller, I want to retrieve Prometheus metrics from the Kubernetes cluster, so that I can analyze system performance during the benchmark.

#### Acceptance Criteria

1. WHEN GET /metrics is received and Benchmark_Status is `success` or `failed`, THE Runner SHALL scrape metrics from the Prometheus instance running in the Kubernetes cluster's `monitoring` namespace and return HTTP 200 with a confirmation message indicating the number of metrics files uploaded
2. IF GET /metrics is received and Benchmark_Status is not `success` or `failed`, THEN THE Runner SHALL return HTTP 409 with a message indicating that the benchmark has not yet completed
3. WHEN metrics are scraped successfully, THE Runner SHALL transform the scraped metrics into Pandas DataFrames and serialize each DataFrame in Parquet format
4. WHEN Parquet files are generated, THE Runner SHALL upload them to the configured S3_Bucket at path `{run_identifier}/{trial_identifier}/metrics/`
5. IF the Prometheus instance is unreachable or returns an error during scraping, THEN THE Runner SHALL return HTTP 500 with the Prometheus endpoint URL and the connection or response error details
6. IF the S3 upload fails for any Parquet file, THEN THE Runner SHALL return HTTP 500 with the failed filename and the S3 error details

### Requirement 18: Configuration Management

**User Story:** As a developer, I want the Runner to centralize configuration with sensible defaults, so that the application can be deployed with minimal environment setup.

#### Acceptance Criteria

1. THE Runner SHALL load all configuration from environment variables at application startup, before the FastAPI application begins accepting requests
2. THE Runner SHALL make the node readiness timeout configurable via environment variable `NODE_READINESS_TIMEOUT_SECONDS` (default: 300, valid range: 60–1800)
3. THE Runner SHALL make the health check retry count configurable via environment variable `HEALTH_CHECK_MAX_ATTEMPTS` (default: 3, valid range: 1–10)
4. THE Runner SHALL make the health check retry interval configurable via environment variable `HEALTH_CHECK_INTERVAL_SECONDS` (default: 5, valid range: 1–60)
5. THE Runner SHALL make the RabbitMQ Docker image configurable via environment variable `RABBITMQ_IMAGE` (default: `rabbitmq:4-management`)
6. IF any numeric environment variable contains a value that cannot be parsed as an integer or falls outside its valid range, THEN THE Runner SHALL log a WARNING with the variable name, invalid value, and the default being used, and apply the default value

### Requirement 19: Manifest List Parsing

**User Story:** As the Runner application, I want to parse k8s.lst files with well-defined line semantics, so that manifest deployment follows a predictable and debuggable sequence.

#### Acceptance Criteria

1. WHEN parsing a k8s.lst file, THE Runner SHALL process lines sequentially from top to bottom
2. THE Runner SHALL treat empty lines (zero-length or whitespace-only after stripping) as no-ops
3. THE Runner SHALL treat lines where the first non-whitespace character is `#` as comments and skip them
4. WHEN a line's first non-whitespace character is `>`, THE Runner SHALL execute the text following `>` (trimmed of leading/trailing whitespace) as a shell command
5. WHEN a line's first non-whitespace character is `+` followed by a valid integer greater than zero, THE Runner SHALL pause execution for that number of seconds
6. IF a line's first non-whitespace character is `+` and the remainder (after trimming) does not parse as an integer greater than zero, THEN THE Runner SHALL log a warning including the unparseable value and pause for 30 seconds
7. WHEN a line does not match any special prefix (`#`, `>`, `+`) and is not blank, THE Runner SHALL treat it (trimmed of whitespace) as a manifest filename; IF the filename does not end in `.yaml`, THE Runner SHALL append `.yaml` and log a warning including the original filename
8. IF a line matches a special prefix (`>` or `+`) but contains no content after the prefix character (empty or whitespace-only after the prefix), THEN THE Runner SHALL log a warning and treat the line as a no-op
9. FOR ALL valid k8s.lst file content, parsing the content into a sequence of typed operations (no-op, comment, command, sleep, manifest) and then serializing those operations back to k8s.lst format SHALL produce a sequence that, when re-parsed, yields the same ordered list of operations (round-trip property)

### Requirement 20: Load Generator Communication

**User Story:** As the Runner application, I want to communicate with Load Generators via HTTP on the Docker network, so that I can start, monitor, and collect results from each instance.

#### Acceptance Criteria

1. THE Runner SHALL address Load Generators by their container name as hostname on port 8080 (e.g., `http://back-office:8080`, `http://portfolio-manager:8080`, `http://trader:8080`, `http://investor:8080`, `http://it-operations:8080`)
2. WHEN sending POST /start to a Load_Generator, THE Runner SHALL include a JSON payload with Content-Type `application/json` containing fields: `Role` (string), `BenchmarkLengthMinutes` (integer from `run_duration_minutes`), `BaseLoadIntensity` (integer), `SpawnRate` (integer), `BaseDelayPercentage` (integer), and `KasbenchUrl` (string constructed as `{globeco_url}:{globeco_port}`)
3. IF a Load_Generator returns HTTP 409 on POST /start, THEN THE Runner SHALL return HTTP 500 with a message indicating the generator for role `{role}` is already running
4. IF a Load_Generator returns HTTP 422 on POST /start, THEN THE Runner SHALL return HTTP 500 with the role name and the validation error details from the response body
5. THE Runner SHALL set a per-request connection timeout of 10 seconds and a read timeout of 30 seconds for all HTTP requests to Load Generators
6. IF a connection to a Load_Generator times out or is refused, THEN THE Runner SHALL include in the error response: the target URL, the timeout duration, and the connection error description
