# Requirement 3: Miscellaneous improvements to the KASBench Runner

## Rename the POST /metrics API endpoint
Change the endpoint from POST /metrics to POST /metrics/export

## Add additional metrics

### Counters

Add the following to COUNTER_METRICS in src/kasbench_runner/services/metrics_config.py

```json
{
    "kafka_consumer_messages_processed_total(service_name,topic)": {
        "metric": "kafka_consumer_messages_processed_total",
        "description": "sum of kafka_consumer_messages_processed_total by service_name and topic.",
        "query": "sum by (service_name, topic) (rate(kafka_consumer_messages_processed_total{service_namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "kafka_consumer_messages_processed_total-service_name-topic"
    },
    "kafka_consumer_messages_failed_total(service_name,topic)": {
        "metric": "kafka_consumer_messages_failed_total",
        "description": "sum of kafka_consumer_messages_failed_total by service_name and topic.",
        "query": "sum by (service_name, topic) (rate(kafka_consumer_messages_failed_total{service_namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "kafka_consumer_messages_failed_total-service_name-topic"
    },
    "kafka_consumer_processing_seconds_total(service_name,topic)": {
        "metric": "kafka_consumer_processing_seconds_total",
        "description": "sum of kafka_consumer_processing_seconds_total by service_name and topic.",
        "query": "sum by (service_name, topic) (rate(kafka_consumer_processing_seconds_total{service_namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "kafka_consumer_processing_seconds_total-service_name-topic"
    },
    "kafka_consumer_idle_seconds_total(service_name,topic)": {
        "metric": "kafka_consumer_idle_seconds_total",
        "description": "sum of kafka_consumer_idle_seconds_total by service_name and topic.",
        "query": "sum by (service_name, topic) (rate(kafka_consumer_idle_seconds_total{service_namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "kafka_consumer_idle_seconds_total-service_name-topic"
    },
    "kafka_consumer_records_polled_total(service_name,topic)": {
        "metric": "kafka_consumer_records_polled_total",
        "description": "sum of kafka_consumer_records_polled_total by service_name and topic.",
        "query": "sum by (service_name, topic) (rate(kafka_consumer_records_polled_total{service_namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "kafka_consumer_records_polled_total-service_name-topic"
    },
    "kafka_consumer_poll_seconds_total(service_name,topic)": {
        "metric": "kafka_consumer_poll_seconds_total",
        "description": "sum of kafka_consumer_poll_seconds_total by service_name and topic.",
        "query": "sum by (service_name, topic) (rate(kafka_consumer_poll_seconds_total{service_namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "kafka_consumer_poll_seconds_total-service_name-topic"
    },
    "kafka_dlq_messages(service_name,topic)": {
        "metric": "kafka_consumer_poll_seconds_total",
        "description": "sum of kafka_dlq_messages by service_name and topic.",
        "query": "sum by (service_name, topic) (rate(kafka_dlq_messages{service_namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "kafka_dlq_messages-service_name-topic"
    }
```



### Gauges
Add the following to GAUGE_METRICS in src/kasbench_runner/services/metrics_config.py

```json
{
    "kafka_consumer_group_lag_ratio": {
        "metric": "kafka_consumer_group_lag_ratio",
        "description": "kafka_consumer_group_lag_ratio",
        "query": "kafka_consumer_group_lag_ratio",
        "name": "kafka_consumer_group_lag_ratio"
    },
    "kafka_consumer_group_lag_sum_ratio": {
        "metric": "kafka_consumer_group_lag_sum_ratio",
        "description": "kafka_consumer_group_lag_sum_ratio",
        "query": "kafka_consumer_group_lag_sum_ratio",
        "name": "kafka_consumer_group_lag_sum_ratio"
    },
    "kafka_consumer_group_members(instance,group)": {
        "metric": "kafka_consumer_group_members",
        "description": "sum of kafka_consumer_group_members by instance and group.",
        "query": "sum by (instance,group) (kafka_consumer_group_members)",
        "name": "kafka_consumer_group_members-instance-group"
    },
    "kafka_consumer_group_offset_ratio": {
        "metric": "kafka_consumer_group_offset_ratio",
        "description": "kafka_consumer_group_offset_ratio",
        "query": "kafka_consumer_group_offset_ratio",
        "name": "kafka_consumer_group_offset_ratio"
    },
    "kafka_consumer_group_offset_sum_ratio": {
        "metric": "kafka_consumer_group_offset_sum_ratio",
        "description": "kafka_consumer_group_offset_sum_ratio",
        "query": "kafka_consumer_group_offset_sum_ratio",
        "name": "kafka_consumer_group_offset_sum_ratio"
    },
    "kafka_dlq_messages_current": {
        "metric": "kafka_dlq_messages_current",
        "description": "kafka_dlq_messages_current",
        "query": "kafka_dlq_messages_current",
        "name": "kafka_dlq_messages_current"
    },
    "kafka_partition_current_offset_ratio": {
        "metric": "kafka_partition_current_offset_ratio",
        "description": "kafka_partition_current_offset_ratio",
        "query": "kafka_partition_current_offset_ratio",
        "name": "kafka_partition_current_offset_ratio"
    },
    "kafka_partition_oldest_offset_ratio": {
        "metric": "kafka_partition_oldest_offset_ratio",
        "description": "kafka_partition_oldest_offset_ratio",
        "query": "kafka_partition_oldest_offset_ratio",
        "name": "kafka_partition_oldest_offset_ratio"
    },
    "kafka_topic_partitions": {
        "metric": "kafka_topic_partitions",
        "description": "kafka_topic_partitions",
        "query": "kafka_topic_partitions",
        "name": "kafka_topic_partitions"
    }
}
```

## Make Prometheus port configurable when calling POST /metrics/export
Currently the port on which Prometheus is exposed is hardcoded in PrometheusClient in src/kasbench_runner/services/prometheus_client.py.  Allow it to be passed as an argument in the POST /metrics/export request object.  Default to 31565.


## POST /prometheus/tsdb/export

The purpose of this API is to export a copy of the Prometheus TSDB database to S3.  
- Currently the port on which Prometheus is exposed is hardcoded in PrometheusClient in src/kasbench_runner/services/prometheus_client.py.  Allow it to be passed as an argument in the POST /prometheus/tsdb/export request object.  Default to 31565.
- Use the s3Bucket, runIdentifier, and trialIdentifier values that were supplied in the POST /init API and previously saved (src/kasbench_runner/models/requests.py).
- Store the tsdb file at s3Bucket/runIdentifier/trialIdentifier/tsdb-snapshots.
- The following commands are how I would do this manually.  You can implement comparable functionality using the `kr8s` module for Kubernetes commands and `boto3` for AWS S3.
1. Take a Prometheus snapshot.  I use the command: `curl -XPOST http://{node-name}:{port-number}/api/v1/admin/tsdb/snapshot`.  Use the PrometheusClient and port discussed above to POST to the /api/v1/admin/tsdb/snapshot endpoint. This will place the snapshot in the /data/snapshots directory on the Prometheus Server pod.
2. Copy the data locally.  I use the following command: `kubectl cp $(kubectl get pod -l app.kubernetes.io/component=server,app.kubernetes.io/instance=prometheus -o jsonpath='{.items[0].metadata.name}' -n monitoring):/data/snapshots ./snapshots -c prometheus-server -n monitoring`
3. Sync the data to S3 at s3Bucket/runIdentifier/trialIdentifier/tsdb-snapshots.  The following is an example: `aws s3 sync ./snapshots s3://kasbench-test-20260528-377288663341-us-east-1-an/run001/trial040/tsdb-snapshots/`

## POST /output/export and POST /output/export/{role}

The purpose of this API is to post the results that would be obtained by calling GET /output/{role} to S3.  If the API is invoked at the /output/export, export 5 output documents, one for each role (back-office, portfolio-manager, trader, investor, and it-operations).  If it is invoked at endpoint /output/export/{role}, only export 1 document for the specified role.  Output should be exported to `s3bucket/runIdentifier/trialIdentifier/output/{role}-output.txt`.


## POST /db/export and POST /db/export/{role}


The purpose of this API is to post the results that would be obtained by calling GET /db/{role} to S3.  If the API is invoked at the /db/export, export 5 databases, one for each role (back-office, portfolio-manager, trader, investor, and it-operations).  If it is invoked at endpoint /db/export/{role}, only export 1 database for the specified role.  Output should be exported to `s3bucket/runIdentifier/trialIdentifier/db/{role}.db`.


## POST /metadata/export

Create a JSON document with the following data and export it to S3 at s3Bucket/runIdentifier/trialIdentifier/run_details.json:

- Current date and time
- All configuration variables, including the following:

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8080` | Server port |
| `SSH_USER` | `ubuntu` | SSH username for remote nodes |
| `SSH_CONNECT_TIMEOUT` | `30` | SSH connection timeout (seconds) |
| `NODE_READINESS_TIMEOUT_SECONDS` | `300` | Max wait for all nodes Ready (60–1800) |
| `NODE_READINESS_POLL_INTERVAL` | `10` | Node polling interval (seconds) |
| `HEALTH_CHECK_MAX_ATTEMPTS` | `3` | Health check retry count (1–10) |
| `HEALTH_CHECK_INTERVAL_SECONDS` | `5` | Wait between health checks (1–60) |
| `RABBITMQ_IMAGE` | `rabbitmq:4-management` | RabbitMQ Docker image |
| `HTTP_CONNECT_TIMEOUT` | `10` | HTTP client connect timeout (seconds) |
| `HTTP_READ_TIMEOUT` | `30` | HTTP client read timeout (seconds) |
| `MANIFEST_FETCH_TIMEOUT` | `30` | Timeout for fetching k8s.lst files |

- All initialization variables, including the following:

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `autoscaler` | string | yes | — | Autoscaler identifier |
| `controlPlaneNode` | string | yes | — | Control plane hostname |
| `amdWorkerNodes` | string[] | yes | — | AMD64 worker hostnames |
| `armWorkerNodes` | string[] | yes | — | ARM64 worker hostnames |
| `s3Bucket` | string | yes | — | S3 bucket for artifacts |
| `globecoUrl` | string | yes | — | GlobeCo application URL |
| `runIdentifier` | string | no | `"run001"` | Run identifier |
| `trialIdentifier` | string | no | `"trial001"` | Trial identifier |
| `clusterCidrRange` | string | no | `"10.244.0.0/16"` | Pod network CIDR |
| `kubernetesVersion` | string | no | `"1.36.1"` | Kubernetes version |
| `loadGeneratorImage` | string | no | `"kasbench/kasbench-load-generator:latest"` | Load generator image |
| `runDurationMinutes` | int | no | `5` | Benchmark duration |
| `globecoPort` | int | no | `8080` | GlobeCo port |
| `skipKubernetesInstall` | bool | no | `false` | Skip k8s cluster setup |
| `skipManifestInstall` | bool | no | `false` | Skip manifest deployment |
| `forceManifestInstall` | bool | no | `false` | Continue on manifest errors |

- The base load intensity, base_delay_percentage, and spawn rate for each role.  This can be obtained in config.py, as shown below:

```python
@dataclass(frozen=True)
class RoleParameters:
    """Per-role parameters for load generation."""

    base_load_intensity: int
    base_delay_percentage: int
    spawn_rate: int


ROLE_PARAMS: dict[str, RoleParameters] = {
    "back-office": RoleParameters(100, 100, 10),
    "portfolio-manager": RoleParameters(100, 100, 10),
    "trader": RoleParameters(100, 100, 10),
    "investor": RoleParameters(10, 100, 10),
    "it-operations": RoleParameters(100, 100, 1),
}
```

- The Kubernetes manifests and version numbers installed.  This can be found in config.py, as shown below:

```python
MANIFEST_REPOS: list[dict[str, str]] = [
    {"owner": "kasbench", "repo": "globeco-observability", "tag": "v1.1.5"},
    {"owner": "kasbench", "repo": "globeco-kafka", "tag": "v1.1.5"},
    {"owner": "kasbench", "repo": "globeco-order-generation-service", "tag": "v1.1.5"},
    {"owner": "kasbench", "repo": "globeco-order-service", "tag": "v1.1.5"},
    {"owner": "kasbench", "repo": "globeco-portfolio-accounting-service", "tag": "v1.1.5"},
    {"owner": "kasbench", "repo": "globeco-portfolio-management-portal", "tag": "v1.1.5"},
    {"owner": "kasbench", "repo": "globeco-portfolio-service", "tag": "v1.1.5"},
    {"owner": "kasbench", "repo": "globeco-pricing-service", "tag": "v1.1.5"},
    {"owner": "kasbench", "repo": "globeco-security-service", "tag": "v1.1.5"},
    {"owner": "kasbench", "repo": "globeco-trade-service", "tag": "v1.1.5"},
    {"owner": "kasbench", "repo": "globeco-execution-service", "tag": "v1.1.5"},
    {"owner": "kasbench", "repo": "globeco-confirmation-service", "tag": "v1.1.5"},
    {"owner": "kasbench", "repo": "globeco-fix-engine", "tag": "v1.1.5"},
    {"owner": "kasbench", "repo": "globeco-allocation-service", "tag": "v1.1.5"},
]
```

- The response object from a call to GET /status, such as the following example:

```json
{
  "status": "running",
  "startTime": "2026-06-10T14:30:00.123456+00:00",
  "endTime": null,
  "loadGenerators": [
    {"role": "back-office", "status": "running", "startTime": "2026-06-10T14:30:00.200000+00:00", "endTime": null},
    {"role": "portfolio-manager", "status": "running", "startTime": "2026-06-10T14:30:00.210000+00:00", "endTime": null},
    {"role": "trader", "status": "running", "startTime": "2026-06-10T14:30:00.220000+00:00", "endTime": null},
    {"role": "investor", "status": "running", "startTime": "2026-06-10T14:30:00.230000+00:00", "endTime": null},
    {"role": "it-operations", "status": "running", "startTime": "2026-06-10T14:30:00.240000+00:00", "endTime": null}
  ]
}
```

## POST /shutdown

The objective of this step is to delete the namespaces that have Kubernetes PVCs, so that claimed storage is released prior to destroying the Kubernetes environment.  This assures that no volumes remain after the environment is destroyed.  Execute the equivalent of the following.

```bash
kubectl delete ns globeco
kubectl delete ns elasticsearch
kubectl delete ns observability
kubectl delete ns monitoring
```

## Update README.md

Update the README.md file to reflect these changes.

