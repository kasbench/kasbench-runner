# Requirements Document

## Introduction

This feature adds deployment rollout monitoring and comprehensive cluster snapshot capabilities to the KASBench Benchmark Runner. It provides functions and REST API endpoints to wait for Kubernetes deployments to complete their rollouts, detect unrecoverable failure conditions, and collect a full cluster state snapshot stored in S3. These capabilities support pre- and post-benchmark auditing of the cluster state.

## Glossary

- **Runner**: The KASBench Benchmark Runner FastAPI application
- **Rollout_Monitor**: The service component responsible for polling a Kubernetes Deployment until rollout completes or fails
- **Snapshot_Collector**: The service component responsible for gathering cluster state and uploading it to S3
- **Deployment_Spec**: A tuple of (deployment_name, namespace) identifying a Kubernetes Deployment to monitor
- **Phase**: A string literal, either "pre" or "post", indicating whether the snapshot is taken before or after the benchmark run
- **Unrecoverable_Condition**: A Deployment condition or pod state that indicates the rollout will never succeed without external intervention (ProgressDeadlineExceeded, CrashLoopBackOff, ImagePullBackOff, ErrImagePull, InvalidImageName, CreateContainerConfigError)
- **S3_Prefix**: The S3 key path `{runIdentifier}/{trialIdentifier}/snapshot/{phase}` under which all snapshot files are stored
- **kr8s**: The async Python Kubernetes client library used throughout the project

## Requirements

### Requirement 1: Wait for Single Deployment Rollout

**User Story:** As a benchmark operator, I want to wait for a specific Kubernetes deployment to complete its rollout, so that I can ensure workloads are ready before proceeding with benchmarks.

#### Acceptance Criteria

1. WHEN a deployment name, namespace, and timeout are provided, THE Rollout_Monitor SHALL poll the Deployment status via kr8s at a fixed interval of 10 seconds until all replicas are updated, available, and ready, or until a terminal condition is detected.
2. WHEN the Deployment has `updatedReplicas` equal to `replicas`, `readyReplicas` equal to `replicas`, and the Progressing condition reports reason "NewReplicaSetAvailable", THE Rollout_Monitor SHALL return successfully.
3. WHEN the timeout elapses before rollout completes, THE Rollout_Monitor SHALL raise a timeout error that includes the deployment name, namespace, and elapsed time.
4. WHEN the Deployment Progressing condition has status "False" and reason "ProgressDeadlineExceeded", THE Rollout_Monitor SHALL raise an unrecoverable error immediately without waiting for timeout.
5. WHEN any pod owned by the Deployment enters CrashLoopBackOff, ImagePullBackOff, ErrImagePull, InvalidImageName, or CreateContainerConfigError state, THE Rollout_Monitor SHALL raise an unrecoverable error that includes the failing pod name and condition.
6. WHEN a transient API error (connection refused, connection timeout, or HTTP 5xx response) occurs during polling, THE Rollout_Monitor SHALL retry up to 3 times with a 15-second delay between attempts before propagating the error.
7. THE Rollout_Monitor SHALL re-fetch the Deployment object from the Kubernetes API on each poll iteration rather than relying solely on a cached refresh.
8. THE Rollout_Monitor SHALL log the current rollout progress (ready replicas vs desired) at each poll iteration using structured logging.
9. IF the specified Deployment does not exist in the given namespace, THEN THE Rollout_Monitor SHALL raise an error indicating the deployment was not found, including the deployment name and namespace.

### Requirement 2: Wait for Multiple Deployment Rollouts

**User Story:** As a benchmark operator, I want to wait for a batch of deployments to complete their rollouts under a single timeout, so that I can ensure the full application stack is ready.

#### Acceptance Criteria

1. WHEN a list of one or more Deployment_Specs (each containing a deployment name and namespace) and a timeout in seconds are provided, THE Rollout_Monitor SHALL monitor all deployments concurrently using the single-deployment rollout function.
2. THE Rollout_Monitor SHALL enforce the timeout as the maximum wall-clock time for the entire batch, not per individual deployment.
3. WHEN all deployments complete their rollouts within the timeout, THE Rollout_Monitor SHALL return successfully with no return value.
4. IF any deployment encounters an Unrecoverable_Condition (a state from which the deployment cannot succeed without external intervention, such as ProgressDeadlineExceeded), THEN THE Rollout_Monitor SHALL cancel monitoring of all remaining deployments and raise an error that identifies the failing deployment and the condition encountered.
5. WHEN the batch timeout elapses before all deployments complete, THE Rollout_Monitor SHALL raise a timeout error that lists all deployments that had not yet completed.
6. THE Rollout_Monitor SHALL use asyncio concurrency to monitor all deployments simultaneously rather than sequentially.
7. IF an empty list of Deployment_Specs is provided, THEN THE Rollout_Monitor SHALL return successfully with no return value without waiting.

### Requirement 3: Cluster Snapshot Collection

**User Story:** As a benchmark operator, I want to capture a comprehensive snapshot of the cluster state, so that I can audit the environment before and after benchmark runs.

#### Acceptance Criteria

1. WHEN a phase ("pre" or "post") is provided, THE Snapshot_Collector SHALL collect cluster state and upload all files to S3 under the path `{runIdentifier}/{trialIdentifier}/snapshot/{phase}/`.
2. THE Snapshot_Collector SHALL collect metadata consisting of: current UTC timestamp (metadata/date.txt), kubectl version equivalent (metadata/kubectl-version.yaml), current context name (metadata/context.txt), cluster endpoint info (metadata/cluster-info.txt), and available API resources (metadata/api-resources.txt).
3. THE Snapshot_Collector SHALL collect resource manifests for: nodes (resources/nodes.yaml), pods (resources/pods.yaml), pods wide format (resources/pods-wide.txt), workloads including deployments, statefulsets, daemonsets, replicasets, jobs, and cronjobs (resources/workloads.yaml), HPAs (resources/autoscaling.yaml), services, endpoints, endpointslices, ingresses, and networkpolicies (resources/network.yaml), PVCs, PVs, storageclasses, and volumeattachments (resources/storage.yaml), resourcequotas, limitranges, and poddisruptionbudgets (resources/policies.yaml), configmaps (resources/configmaps.yaml), and validatingwebhookconfigurations and mutatingwebhookconfigurations (resources/webhooks.yaml).
4. THE Snapshot_Collector SHALL collect node descriptions (descriptions/nodes.txt) and pod descriptions (descriptions/pods.txt) containing detailed status output for each resource.
5. THE Snapshot_Collector SHALL collect all cluster events (events/all.yaml) and warning-only events (events/warnings.yaml).
6. THE Snapshot_Collector SHALL collect raw API responses for /readyz (raw/readyz.txt), /livez (raw/livez.txt), node metrics (raw/node-metrics.json), and pod metrics (raw/pod-metrics.json).
7. IF VPA, KEDA, or Gateway API custom resources are not available in the cluster, THEN THE Snapshot_Collector SHALL log a warning identifying the unavailable resource type and continue the snapshot without failing.
8. THE Snapshot_Collector SHALL attempt to collect optional CRDs: VPA resources (resources/vpa.yaml), KEDA resources including scaledobjects, scaledjobs, triggerauthentications, and clustertriggerauthentications (resources/keda.yaml), and Gateway API resources including gateways, gatewayclasses, httproutes, and grpcroutes (resources/gateway-api.yaml).
9. THE Snapshot_Collector SHALL prepend a header to each collected file containing the ISO 8601 UTC collection timestamp and a human-readable label identifying the Kubernetes API resource or endpoint that produced the data.
10. THE Snapshot_Collector SHALL generate a SHA256SUMS manifest file containing the SHA-256 hash of every collected file, and upload it alongside the other files.
11. THE Snapshot_Collector SHALL use kr8s async API calls to collect Kubernetes data, consistent with the rest of the codebase.
12. THE Snapshot_Collector SHALL use the existing S3Client service to upload all collected files.
13. IF an S3 upload fails for a non-optional file, THEN THE Snapshot_Collector SHALL raise an error indicating which file failed and the underlying exception.
14. IF a non-optional Kubernetes API call fails during collection, THEN THE Snapshot_Collector SHALL raise an error indicating which resource collection failed and the underlying exception.
15. IF an S3 upload fails for an optional CRD file, THEN THE Snapshot_Collector SHALL log a warning identifying the failed file and continue the snapshot without failing.
16. IF the provided phase value is not "pre" or "post", THEN THE Snapshot_Collector SHALL reject the request with an error indicating the invalid phase value and the allowed values.

### Requirement 4: Wait for Rollout REST API Endpoint

**User Story:** As an external orchestrator, I want an HTTP endpoint to trigger deployment rollout monitoring, so that I can integrate rollout waiting into automated workflows.

#### Acceptance Criteria

1. WHEN a POST request is received at the rollout wait endpoint with a valid deployment name (non-empty string, maximum 253 characters), namespace (non-empty string, maximum 63 characters), and timeout (positive integer, 1 to 1800 seconds), THE Runner SHALL invoke the single-deployment rollout function and return a response indicating success or failure upon completion.
2. WHEN the rollout completes successfully, THE Runner SHALL return an HTTP 200 response containing the deployment name and elapsed time in seconds.
3. WHEN the rollout fails because the elapsed time exceeds the specified timeout, THE Runner SHALL return an HTTP 500 response with error type "rollout_timeout", the deployment name, namespace, and elapsed time in seconds.
4. WHEN the rollout fails because the deployment's Progressing condition has status "False" with reason "ProgressDeadlineExceeded", THE Runner SHALL return an HTTP 500 response with error type "rollout_unrecoverable", the deployment name, namespace, and the specific condition reason detected.
5. IF the timeout parameter is missing or not a positive integer between 1 and 1800, THEN THE Runner SHALL return an HTTP 422 response with a validation error message indicating the constraint violated.
6. IF the deployment name or namespace parameter is missing or empty, THEN THE Runner SHALL return an HTTP 422 response with a validation error message indicating which parameter is invalid.
7. IF the specified deployment does not exist in the given namespace, THEN THE Runner SHALL return an HTTP 404 response with an error message indicating the deployment was not found.
8. IF the Kubernetes API is unreachable during rollout monitoring, THEN THE Runner SHALL return an HTTP 500 response with error type "kubernetes_api_error" and a message indicating the connectivity failure.

### Requirement 5: Wait for All Rollouts REST API Endpoint

**User Story:** As an external orchestrator, I want an HTTP endpoint to wait for all application deployments to roll out, so that I can confirm the full stack is ready before starting a benchmark.

#### Acceptance Criteria

1. WHEN a POST request is received at `/rollout/all` with a `timeout` parameter (integer, 1 to 3600 seconds), THE Runner SHALL invoke the batch rollout function with the configured deployment list, using the provided timeout as the maximum total wait time for all deployments combined.
2. THE Runner SHALL use a configurable default deployment list containing 24 deployments across namespaces: elasticsearch (1), globeco (14), kube-system (2), monitoring (5), observability (1), and opentelemetry-operator-system (1).
3. WHEN all deployments in the list reach a successful rollout state (all desired replicas ready, Progressing condition True with reason NewReplicaSetAvailable, and Available condition True) within the timeout, THE Runner SHALL return an HTTP 200 response containing the count of deployments checked and the elapsed wait time in seconds.
4. IF any deployment reports a ProgressDeadlineExceeded condition or the total timeout elapses before all deployments are ready, THEN THE Runner SHALL return an HTTP 500 response with error details listing each failing or incomplete deployment by name and namespace.
5. IF the timeout parameter is missing or not an integer in the range 1 to 3600, THEN THE Runner SHALL return an HTTP 422 response with a validation error message indicating the constraint violation.
6. THE Runner SHALL load the deployment list from configuration (environment variable or configuration file), allowing it to be overridden without code changes.

### Requirement 6: Snapshot REST API Endpoint

**User Story:** As an external orchestrator, I want an HTTP endpoint to trigger cluster snapshot collection, so that I can capture cluster state at defined points in the benchmark lifecycle.

#### Acceptance Criteria

1. WHEN a POST request is received at `/snapshot` with a phase parameter set to "pre" or "post", THE Runner SHALL collect Kubernetes resource manifests from the cluster and upload them to S3 under the path `{run_identifier}/{trial_identifier}/snapshot/{phase}/`, then return an HTTP 200 response within 120 seconds.
2. WHEN the snapshot completes successfully, THE Runner SHALL return an HTTP 200 response body containing the phase value, the integer count of files uploaded to S3, and the S3 key prefix used for the upload.
3. IF the snapshot fails due to an S3 operation error, THEN THE Runner SHALL return an HTTP 500 response containing the error field set to "s3_operation_failed" and a message describing the failure.
4. IF the snapshot fails due to a Kubernetes API error, THEN THE Runner SHALL return an HTTP 500 response containing the error field set to "kubernetes_error" and a message describing the failure.
5. IF the phase parameter is not "pre" or "post", THEN THE Runner SHALL return an HTTP 422 response with a validation error message indicating the allowed values.
6. IF the benchmark has not been initialized, THEN THE Runner SHALL return an HTTP 409 response indicating that initialization is required before taking a snapshot.
7. WHILE a snapshot operation is already in progress, IF a new POST request is received at `/snapshot`, THEN THE Runner SHALL return an HTTP 409 response indicating that a snapshot is already running.
