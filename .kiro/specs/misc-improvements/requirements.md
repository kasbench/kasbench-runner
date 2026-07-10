# Requirements Document

## Introduction

This document specifies miscellaneous improvements to the KASBench Runner application, including endpoint renaming, additional Prometheus metrics, configurable Prometheus port, new S3 export endpoints for TSDB snapshots, load generator output, databases, and metadata, a namespace cleanup endpoint, and README updates.

## Glossary

- **Runner**: The KASBench Benchmark Runner FastAPI application
- **Prometheus_Client**: The service responsible for executing PromQL queries against the Prometheus instance exposed on the control plane node
- **S3_Client**: The service responsible for uploading artifacts to AWS S3
- **Kubernetes_Manager**: The service responsible for Kubernetes cluster operations using kr8s
- **Metrics_Config**: The module defining all Prometheus metric query definitions (counters and gauges)
- **Benchmark_State**: The mutable singleton holding benchmark lifecycle state including configuration from POST /initialize
- **Load_Generator**: A per-role HTTP service running on port 8080 that produces benchmark output and database files
- **Role**: One of the five benchmark roles: back-office, portfolio-manager, trader, investor, it-operations
- **TSDB_Snapshot**: A Prometheus time-series database snapshot created via the /api/v1/admin/tsdb/snapshot admin endpoint
- **Run_Details**: A JSON metadata document capturing configuration, parameters, and status for a benchmark trial

## Requirements

### Requirement 1: Rename Metrics Export Endpoint

**User Story:** As an API consumer, I want the metrics export endpoint path to be `/metrics/export`, so that the endpoint naming is consistent with other export operations.

#### Acceptance Criteria

1. WHEN a POST request is sent to `/metrics/export`, THE Runner SHALL accept the same request body parameters (overwrite, interval, step) and return the same response structure and status codes (200, 207, 409, 500) as the current `/metrics` endpoint
2. WHEN a POST request is sent to `/metrics/export` with no request body, THE Runner SHALL use the same default parameter values as the current `/metrics` endpoint (overwrite: false, interval: "60s", step: "15s")
3. WHEN a POST request is sent to the old path `/metrics`, THE Runner SHALL return HTTP 404
4. WHEN a request using any HTTP method other than POST is sent to `/metrics/export`, THE Runner SHALL return HTTP 405 (Method Not Allowed)

### Requirement 2: Add Kafka Counter Metrics

**User Story:** As a benchmark operator, I want Kafka consumer counter metrics tracked, so that I can analyze consumer throughput and performance.

#### Acceptance Criteria

1. THE Metrics_Config SHALL include a counter metric definition (metric_type="counter") for `kafka_consumer_messages_processed_total` with query `sum by (service_name, topic) (rate(kafka_consumer_messages_processed_total{service_namespace="globeco"}[__INTERVAL__]))` and name `kafka_consumer_messages_processed_total-service_name-topic`
2. THE Metrics_Config SHALL include a counter metric definition (metric_type="counter") for `kafka_consumer_messages_failed_total` with query `sum by (service_name, topic) (rate(kafka_consumer_messages_failed_total{service_namespace="globeco"}[__INTERVAL__]))` and name `kafka_consumer_messages_failed_total-service_name-topic`
3. THE Metrics_Config SHALL include a counter metric definition (metric_type="counter") for `kafka_consumer_processing_seconds_total` with query `sum by (service_name, topic) (rate(kafka_consumer_processing_seconds_total{service_namespace="globeco"}[__INTERVAL__]))` and name `kafka_consumer_processing_seconds_total-service_name-topic`
4. THE Metrics_Config SHALL include a counter metric definition (metric_type="counter") for `kafka_consumer_idle_seconds_total` with query `sum by (service_name, topic) (rate(kafka_consumer_idle_seconds_total{service_namespace="globeco"}[__INTERVAL__]))` and name `kafka_consumer_idle_seconds_total-service_name-topic`
5. THE Metrics_Config SHALL include a counter metric definition (metric_type="counter") for `kafka_consumer_records_polled_total` with query `sum by (service_name, topic) (rate(kafka_consumer_records_polled_total{service_namespace="globeco"}[__INTERVAL__]))` and name `kafka_consumer_records_polled_total-service_name-topic`
6. THE Metrics_Config SHALL include a counter metric definition (metric_type="counter") for `kafka_consumer_poll_seconds_total` with query `sum by (service_name, topic) (rate(kafka_consumer_poll_seconds_total{service_namespace="globeco"}[__INTERVAL__]))` and name `kafka_consumer_poll_seconds_total-service_name-topic`
7. THE Metrics_Config SHALL include a counter metric definition (metric_type="counter") for `kafka_dlq_messages` with query `sum by (service_name, topic) (rate(kafka_dlq_messages{service_namespace="globeco"}[__INTERVAL__]))` and name `kafka_dlq_messages-service_name-topic`
8. THE Metrics_Config SHALL append all 7 Kafka consumer counter metric definitions to the COUNTER_METRICS list so that they are included in ALL_METRICS

### Requirement 3: Add Kafka Gauge Metrics

**User Story:** As a benchmark operator, I want Kafka consumer group and partition gauge metrics tracked, so that I can monitor consumer lag and partition health.

#### Acceptance Criteria

1. THE Metrics_Config SHALL include a gauge metric definition in the GAUGE_METRICS list for `kafka_consumer_group_lag_ratio` with metric `kafka_consumer_group_lag_ratio`, query `kafka_consumer_group_lag_ratio`, name `kafka_consumer_group_lag_ratio`, and metric_type `gauge`
2. THE Metrics_Config SHALL include a gauge metric definition in the GAUGE_METRICS list for `kafka_consumer_group_lag_sum_ratio` with metric `kafka_consumer_group_lag_sum_ratio`, query `kafka_consumer_group_lag_sum_ratio`, name `kafka_consumer_group_lag_sum_ratio`, and metric_type `gauge`
3. THE Metrics_Config SHALL include a gauge metric definition in the GAUGE_METRICS list for `kafka_consumer_group_members` with metric `kafka_consumer_group_members`, query `sum by (instance,group) (kafka_consumer_group_members)`, name `kafka_consumer_group_members-instance-group`, and metric_type `gauge`
4. THE Metrics_Config SHALL include a gauge metric definition in the GAUGE_METRICS list for `kafka_consumer_group_offset_ratio` with metric `kafka_consumer_group_offset_ratio`, query `kafka_consumer_group_offset_ratio`, name `kafka_consumer_group_offset_ratio`, and metric_type `gauge`
5. THE Metrics_Config SHALL include a gauge metric definition in the GAUGE_METRICS list for `kafka_consumer_group_offset_sum_ratio` with metric `kafka_consumer_group_offset_sum_ratio`, query `kafka_consumer_group_offset_sum_ratio`, name `kafka_consumer_group_offset_sum_ratio`, and metric_type `gauge`
6. THE Metrics_Config SHALL include a gauge metric definition in the GAUGE_METRICS list for `kafka_dlq_messages_current` with metric `kafka_dlq_messages_current`, query `kafka_dlq_messages_current`, name `kafka_dlq_messages_current`, and metric_type `gauge`
7. THE Metrics_Config SHALL include a gauge metric definition in the GAUGE_METRICS list for `kafka_partition_current_offset_ratio` with metric `kafka_partition_current_offset_ratio`, query `kafka_partition_current_offset_ratio`, name `kafka_partition_current_offset_ratio`, and metric_type `gauge`
8. THE Metrics_Config SHALL include a gauge metric definition in the GAUGE_METRICS list for `kafka_partition_oldest_offset_ratio` with metric `kafka_partition_oldest_offset_ratio`, query `kafka_partition_oldest_offset_ratio`, name `kafka_partition_oldest_offset_ratio`, and metric_type `gauge`
9. THE Metrics_Config SHALL include a gauge metric definition in the GAUGE_METRICS list for `kafka_topic_partitions` with metric `kafka_topic_partitions`, query `kafka_topic_partitions`, name `kafka_topic_partitions`, and metric_type `gauge`
10. THE Metrics_Config SHALL retain all previously existing gauge metric definitions in the GAUGE_METRICS list when the Kafka gauge metrics are added
11. THE Metrics_Config SHALL include exactly 9 Kafka gauge metric definitions, each implemented as a MetricDefinition dataclass instance with fields metric, description, query, name, and metric_type

### Requirement 4: Configurable Prometheus Port for Metrics Export

**User Story:** As a benchmark operator, I want to specify the Prometheus port when calling the metrics export endpoint, so that I can target Prometheus instances running on non-default ports.

#### Acceptance Criteria

1. WHEN a POST request to `/metrics/export` includes a `prometheusPort` field in the request body, THE Runner SHALL use that port value when constructing the Prometheus URL for all range queries in that request
2. WHEN a POST request to `/metrics/export` omits the `prometheusPort` field, THE Runner SHALL default to port 31565
3. THE Runner SHALL validate that the `prometheusPort` value is an integer between 1 and 65535 inclusive
4. IF the `prometheusPort` value fails validation, THEN THE Runner SHALL reject the request with an error response indicating the invalid port value and SHALL NOT execute any Prometheus queries

### Requirement 5: Prometheus TSDB Snapshot Export

**User Story:** As a benchmark operator, I want to export a Prometheus TSDB snapshot to S3, so that I can preserve the raw time-series data for later analysis.

#### Acceptance Criteria

1. WHEN a POST request is sent to `/prometheus/tsdb/export`, THE Runner SHALL trigger a TSDB snapshot on the Prometheus server by POSTing to `http://{controlPlaneNode}:{prometheusPort}/api/v1/admin/tsdb/snapshot` and extract the snapshot directory name from the JSON response field `data.name`
2. WHEN the TSDB snapshot is created, THE Runner SHALL copy the snapshot directory from the path `/data/snapshots/{snapshotName}` in the prometheus-server pod (selected by labels `app.kubernetes.io/component=server,app.kubernetes.io/instance=prometheus`) in the `monitoring` namespace to a local temporary directory using kr8s
3. WHEN the snapshot files are copied locally, THE Runner SHALL upload the snapshot directory to S3 at `{s3Bucket}/{runIdentifier}/{trialIdentifier}/tsdb-snapshots` and delete the local temporary copy after a successful upload
4. WHEN a POST request to `/prometheus/tsdb/export` includes a `prometheusPort` field, THE Runner SHALL use that port value (integer between 1 and 65535) for the Prometheus API call
5. WHEN a POST request to `/prometheus/tsdb/export` omits the `prometheusPort` field, THE Runner SHALL default to port 31565
6. IF the Prometheus snapshot API call fails or does not respond within 30 seconds, THEN THE Runner SHALL return an error response with HTTP 502 and a message indicating the Prometheus snapshot trigger failed
7. IF the pod copy operation fails, THEN THE Runner SHALL return an error response with HTTP 500 and a message indicating the snapshot copy from the pod failed
8. IF the S3 upload fails, THEN THE Runner SHALL return an error response with HTTP 500 and a message indicating the S3 upload failed
9. IF the benchmark state is NOT_INITIALIZED, THEN THE Runner SHALL reject the request with HTTP 409 and a message indicating the benchmark must be initialized before exporting
10. WHEN the TSDB snapshot export completes successfully, THE Runner SHALL return HTTP 200 with a JSON response containing the S3 destination path and a timestamp
11. WHEN no prometheus-server pod matching labels `app.kubernetes.io/component=server,app.kubernetes.io/instance=prometheus` is found in the `monitoring` namespace, THE Runner SHALL return an error response with HTTP 500 and a message indicating the Prometheus server pod was not found

### Requirement 6: Output Export to S3

**User Story:** As a benchmark operator, I want to export load generator output to S3, so that I can archive test results for later review without manually downloading them.

#### Acceptance Criteria

1. WHEN a POST request is sent to `/output/export`, THE Runner SHALL internally retrieve output from all five roles (back-office, portfolio-manager, trader, investor, it-operations) using the same mechanism as GET /output/{role} (i.e., calling GET `http://{role}:8080/download-output`) and upload each result to S3 at `{s3Bucket}/{runIdentifier}/{trialIdentifier}/output/{role}-output.txt`
2. WHEN a POST request is sent to `/output/export/{role}`, THE Runner SHALL internally retrieve output for only the specified role using the same mechanism as GET /output/{role} and upload it to S3 at `{s3Bucket}/{runIdentifier}/{trialIdentifier}/output/{role}-output.txt`
3. THE Runner SHALL NOT return the output content to the API caller; the response SHALL only indicate the export status (success/failure, files uploaded, S3 paths)
4. WHEN all uploads complete successfully, THE Runner SHALL return HTTP 200 with a response indicating the number of files exported, the S3 prefix used, and a timestamp
5. IF a role parameter in the path is not one of the five valid roles, THEN THE Runner SHALL return HTTP 400 with an error response that includes the invalid value and the list of valid roles
6. IF a load generator connection fails or times out within the configured HTTP connect timeout, THEN THE Runner SHALL return HTTP 502 with an error response identifying the failed role
7. IF an S3 upload operation fails, THEN THE Runner SHALL return HTTP 500 with an error response identifying the S3 key that failed and the exception detail
8. IF the benchmark state is NOT_INITIALIZED, THEN THE Runner SHALL reject the request with HTTP 409 and an error response indicating that initialization is required
9. IF the `/output/export` request involves multiple roles and one or more roles fail while others succeed, THEN THE Runner SHALL return HTTP 207 with a response listing per-role success or failure status including error details for failed roles

### Requirement 7: Database Export to S3

**User Story:** As a benchmark operator, I want to export load generator databases to S3, so that I can archive the raw data for later analysis without manually downloading them.

#### Acceptance Criteria

1. WHEN a POST request is sent to `/db/export`, THE Runner SHALL internally retrieve the database from each of the five roles (back-office, portfolio-manager, trader, investor, it-operations) using the same mechanism as GET /db/{role} (i.e., calling GET `http://{role}:8080/download-db`) and upload each to S3 at `{s3Bucket}/{runIdentifier}/{trialIdentifier}/db/{role}.db`
2. WHEN a POST request is sent to `/db/export/{role}`, THE Runner SHALL internally retrieve the database from only the specified role using the same mechanism as GET /db/{role} and upload it to S3 at `{s3Bucket}/{runIdentifier}/{trialIdentifier}/db/{role}.db`
3. THE Runner SHALL NOT return the database content to the API caller; the response SHALL only indicate the export status (success/failure, files uploaded, S3 paths)
4. WHEN all database exports complete successfully, THE Runner SHALL return HTTP 200 with a response body listing each exported role and its S3 key
5. IF a role path parameter is not one of the five valid roles (back-office, portfolio-manager, trader, investor, it-operations), THEN THE Runner SHALL return HTTP 400 with an error message listing the valid roles
6. IF a load generator returns a non-200 response (including 409 subprocess active or 404 database not found), THEN THE Runner SHALL return HTTP 502 with an error message identifying the failed role and the upstream HTTP status code
7. IF connecting to a load generator exceeds 10 seconds or the connection is refused, THEN THE Runner SHALL return HTTP 502 with an error message identifying the unreachable role
8. IF the S3 upload fails for any role, THEN THE Runner SHALL return HTTP 500 with an error message identifying the role and the S3 failure reason
9. WHEN the benchmark state is NOT_INITIALIZED, THE Runner SHALL reject the request with HTTP 409 and an error message indicating that the benchmark must be initialized first

### Requirement 8: Metadata Export to S3

**User Story:** As a benchmark operator, I want to export a comprehensive metadata document to S3, so that I have a complete record of the benchmark configuration and state.

#### Acceptance Criteria

1. WHEN a POST request is sent to `/metadata/export`, THE Runner SHALL create a JSON document and upload it to S3 at `{s3Bucket}/{runIdentifier}/{trialIdentifier}/run_details.json` with Content-Type `application/json`, and return HTTP 200 with a JSON response body containing the S3 key of the uploaded object and a timestamp of when the upload completed
2. THE Run_Details document SHALL include a `timestamp` field containing the date and time the document was generated, formatted in ISO 8601 UTC (e.g., `2024-01-15T10:30:00Z`)
3. THE Run_Details document SHALL include an `environment` object containing all environment configuration variables: HOST, PORT, SSH_USER, SSH_CONNECT_TIMEOUT, NODE_READINESS_TIMEOUT_SECONDS, NODE_READINESS_POLL_INTERVAL, HEALTH_CHECK_MAX_ATTEMPTS, HEALTH_CHECK_INTERVAL_SECONDS, RABBITMQ_IMAGE, HTTP_CONNECT_TIMEOUT, HTTP_READ_TIMEOUT, MANIFEST_FETCH_TIMEOUT
4. THE Run_Details document SHALL include an `initialization` object containing all initialization variables: autoscaler, controlPlaneNode, amdWorkerNodes, armWorkerNodes, s3Bucket, globecoUrl, runIdentifier, trialIdentifier, clusterCidrRange, kubernetesVersion, loadGeneratorImage, runDurationMinutes, globecoPort, skipKubernetesInstall, skipManifestInstall, forceManifestInstall
5. THE Run_Details document SHALL include a `roles` object containing per-role parameters (base_load_intensity, base_delay_percentage, spawn_rate) for each of the five roles: back-office, portfolio-manager, trader, investor, it-operations
6. THE Run_Details document SHALL include a `manifests` array containing the Kubernetes manifest repositories and their version tags from MANIFEST_REPOS, where each entry includes owner, repo, and tag fields
7. THE Run_Details document SHALL include a `status` object containing the full status response equivalent to the GET /status endpoint response, including overall status, start_time, end_time, and the per-generator load_generators array
8. IF the S3 upload fails, THEN THE Runner SHALL return HTTP 500 with an error response containing the error type, a message indicating the S3 operation that failed, and context including the target bucket and key
9. IF the benchmark state is NOT_INITIALIZED when the POST `/metadata/export` request is received, THEN THE Runner SHALL reject the request with HTTP 409 and an error response indicating that the system has not been initialized

### Requirement 9: Namespace Cleanup on Shutdown

**User Story:** As a benchmark operator, I want to delete namespaces with PVCs before destroying the cluster, so that claimed storage volumes are released cleanly.

#### Acceptance Criteria

1. WHEN a POST request is sent to `/shutdown`, THE Runner SHALL delete the following Kubernetes namespaces in this order: globeco, elasticsearch, observability, monitoring
2. THE Runner SHALL delete namespaces sequentially, waiting up to 60 seconds per namespace for deletion to complete, and continuing to the next namespace even if one deletion fails or times out
3. IF a namespace deletion fails or times out, THEN THE Runner SHALL record the namespace name and error detail, and continue processing remaining namespaces
4. WHEN all namespace deletions complete, THE Runner SHALL return HTTP 200 with a response containing the per-namespace deletion result (success or failure with error detail) and a timestamp
5. IF the benchmark state is NOT_INITIALIZED, THEN THE Runner SHALL reject the request with HTTP 409 and an error response indicating the current state
6. IF the benchmark state is RUNNING, THEN THE Runner SHALL reject the request with HTTP 409 and an error response indicating that shutdown is not permitted while a benchmark is in progress

### Requirement 10: README Documentation Update

**User Story:** As a developer, I want the README to document all new and changed endpoints, so that the API documentation remains accurate.

#### Acceptance Criteria

1. WHEN the `/metrics` endpoint has been renamed to `/metrics/export`, THE README SHALL replace the existing `POST /metrics` API Reference section with a `POST /metrics/export` section that includes the endpoint path, request body fields with types and defaults, success response format, error responses with status codes and conditions, and allowed benchmark states
2. THE README SHALL document the `POST /prometheus/tsdb/export` endpoint in the API Reference section including the endpoint path, the optional `prometheusPort` request body parameter with its type and default value of 31565, success response format, error responses with status codes and conditions, and allowed benchmark states
3. THE README SHALL document the `POST /output/export` and `POST /output/export/{role}` endpoints in the API Reference section including the endpoint paths, the path parameter for role with valid values, the S3 destination path format, success response format, and error responses with status codes and conditions
4. THE README SHALL document the `POST /db/export` and `POST /db/export/{role}` endpoints in the API Reference section including the endpoint paths, the path parameter for role with valid values, the S3 destination path format, success response format, and error responses with status codes and conditions
5. THE README SHALL document the `POST /metadata/export` endpoint in the API Reference section including the endpoint path, the JSON fields included in the exported document, the S3 destination path format, success response format, and error responses with status codes and conditions
6. THE README SHALL document the `POST /shutdown` endpoint in the API Reference section including the endpoint path, the namespaces deleted, success response format, and error responses with status codes and conditions
7. THE README SHALL include the `prometheusPort` field with its type, default value of 31565, and description in the request body table of the `POST /metrics/export` endpoint documentation
