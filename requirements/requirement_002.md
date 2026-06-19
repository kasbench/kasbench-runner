# Requirement 2: Query and save metrics to S3

The purpose of this requirement is to define a new API endpoint that instructs the KASBench Runner to query Prometheus based on configured queries and save the result to AWS S3.

- The API endpoint will be POST /metrics
- POST /metrics takes an optional request object in the form `{overwrite: true, interval: "60s"}`,  If the request object is passed and if the value of `overwrite` is true, the API will be allowed to overwrite existing metrics.  If the request object is not present or if the value of `overwrite` is false, then the API will not overwrite any metrics and will return an appropriate http status code and error if any metric would have been overwritten.  If the field `interval` is valued, save that value as the interval.  Otherwise, interval is "60s".  The value of interval will be used below.1
- If the current status is `not-initialized`, `not-started`, or `running`, the endpoint will raise an appropriate error status and message.  Metrics are not available before the runner is has been initialized, started, and completed a run.
- POST /metrics will save files in the `s3Bucket` location configured at initialization.
- Each metric will be stored in an object named `{runIdentifier}/{trialIdentifier}/metrics/{name}`, where `runIdentifier` and `trialIdentifier` are the run and trial identifiers passed in at initialization, and `name` is the name provided in the configuration (discussed below)
- Metrics are obtain by executing promQL queries on the control plane.  The DNS name of the control plane is stored in the `controlPlaneNode` passed in during initialization.  The Kubernetes name of the Prometheus service is `prometheus-server` in the `monitoring` namespace, port 80.
- There are two JSON configurations below.  The first contains all the counter-type metrics, while the second contains gauge-type metrics.  Iterate through both configurations, performing the following for each item:
    - If the `query` contains the string literal `__INTERVAL__`, replace it with the `interval` value saved in a previous step.
    - Execute the resulting `query`.  If a substitution was performed in the prior step, use the new query; otherwise, execute the original query.
    - If the result of the promQL query is not an error, store the resulting output as a .json file using the naming format described above.
    - If the result is an error, accumulate the error name and associated error message in a structure that can be returned at the end.
- When all metrics have been iterated (both configurations), return success if there were no errors or failure if any errors were encountered.  Return the metric name and error message for each error as accumulated above.

**Important Notes**
- The metrics configuration will change over time.  It should be easy to make those changes.
- Error messages should be descriptive and helpful.  Security is not a concern, since this is a benchmark and there is no real data.
- Update the [README.md](../README.md) file to reflect these changes.








- Configuration for counters:
```json
{
    "container_blkio_device_usage_total(container, device, operation)": {
        "metric": "container_blkio_device_usage_total",
        "description": "sum of container_blkio_device_usage_total by container, device, and operation",
        "query": "sum by (container, device, operation) (rate(container_blkio_device_usage_total{namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_blkio_device_usage_total-container-_device-_operation"
    },
    "container_cpu_cfs_periods_total(container)": {
        "metric": "container_cpu_cfs_periods_total",
        "description": "sum of container_cpu_cfs_periods_total by container.",
        "query": "sum by (container) (rate(container_cpu_cfs_periods_total{namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_cpu_cfs_periods_total-container"
    },
    "container_cpu_cfs_periods_total(container, pod)": {
        "metric": "container_cpu_cfs_periods_total",
        "description": "sum of container_cpu_cfs_periods_total by container and pod.  Container level.",
        "query": "sum by (container, pod) (rate(container_cpu_cfs_periods_total{namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_cpu_cfs_periods_total-container-_pod"
    },
    "container_cpu_cfs_throttled_periods_total(container)": {
        "metric": "container_cpu_cfs_throttled_periods_total",
        "description": "sum of container_cpu_cfs_throttled_periods_total by container.",
        "query": "sum by (container) (rate(container_cpu_cfs_throttled_periods_total{namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_cpu_cfs_throttled_periods_total-container"
    },
    "container_cpu_cfs_throttled_periods_total(container, pod)": {
        "metric": "container_cpu_cfs_throttled_periods_total",
        "description": "sum of container_cpu_cfs_throttled_periods_total by container and pod.",
        "query": "sum by (container, pod) (rate(container_cpu_cfs_throttled_periods_total{namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_cpu_cfs_throttled_periods_total-container-_pod"
    },
    "container_cpu_cfs_throttled_seconds_total(container)": {
        "metric": "container_cpu_cfs_throttled_seconds_total",
        "description": "sum of container_cpu_cfs_throttled_seconds_total by container.",
        "query": "sum by (container) (rate(container_cpu_cfs_throttled_seconds_total{namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_cpu_cfs_throttled_seconds_total-container"
    },
    "container_cpu_cfs_throttled_seconds_total(container, pod)": {
        "metric": "container_cpu_cfs_throttled_seconds_total",
        "description": "sum of container_cpu_cfs_throttled_seconds_total by container and pod.",
        "query": "sum by (container, pod) (rate(container_cpu_cfs_throttled_seconds_total{namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_cpu_cfs_throttled_seconds_total-container-_pod"
    },
    "container_cpu_system_seconds_total(container)": {
        "metric": "container_cpu_system_seconds_total",
        "description": "sum of container_cpu_system_seconds_total by container.",
        "query": "sum by (container) (rate(container_cpu_system_seconds_total{namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_cpu_system_seconds_total-container"
    },
    "container_cpu_system_seconds_total(container, pod)": {
        "metric": "container_cpu_system_seconds_total",
        "description": "sum of container_cpu_system_seconds_total by container and pod.",
        "query": "sum by (container, pod) (rate(container_cpu_system_seconds_total{namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_cpu_system_seconds_total-container-_pod"
    },
    "container_cpu_usage_seconds_total(container, pod)": {
        "metric": "container_cpu_usage_seconds_total",
        "description": "sum of container_cpu_usage_seconds_total by container and pod.",
        "query": "sum by (container, pod) (rate(container_cpu_usage_seconds_total{namespace=\"globeco\", cpu=\"total\"}[__INTERVAL__]))",
        "name": "container_cpu_usage_seconds_total-container-_pod"
    },
    "container_cpu_usage_seconds_total(container)": {
        "metric": "container_cpu_usage_seconds_total",
        "description": "sum of container_cpu_usage_seconds_total by container.",
        "query": "sum by (container) (rate(container_cpu_usage_seconds_total{namespace=\"globeco\", cpu=\"total\"}[__INTERVAL__]))",
        "name": "container_cpu_usage_seconds_total-container"
    },
    "container_cpu_user_seconds_total(container)": {
        "metric": "container_cpu_user_seconds_total",
        "description": "sum of container_cpu_user_seconds_total by container.",
        "query": "sum by (container) (rate(container_cpu_user_seconds_total{namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_cpu_user_seconds_total-container"
    },
    "container_cpu_user_seconds_total(container, pod)": {
        "metric": "container_cpu_user_seconds_total",
        "description": "sum of container_cpu_user_seconds_total by container and pod.",
        "query": "sum by (container, pod) (rate(container_cpu_user_seconds_total{namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_cpu_user_seconds_total-container-_pod"
    },
    "container_fs_reads_bytes_total(container, device)": {
        "metric": "container_fs_reads_bytes_total",
        "description": "sum of container_fs_reads_bytes_total by container and device.",
        "query": "sum by (container, device) (rate(container_fs_reads_bytes_total{namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_fs_reads_bytes_total-container-_device"
    },
    "container_fs_reads_bytes_total(container, pod, device": {
        "metric": "container_fs_reads_bytes_total",
        "description": "sum of container_fs_reads_bytes_total by container, pod, and device.",
        "query": "sum by (container, pod, device) (rate(container_fs_reads_bytes_total{namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_fs_reads_bytes_total-container-_pod-_device"
    },
    "container_fs_reads_total(container, device)": {
        "metric": "container_fs_reads_total",
        "description": "sum of container_fs_reads_total by container and device.",
        "query": "sum by (container, device) (rate(container_fs_reads_total{namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_fs_reads_total-container-_device"
    },
    "container_fs_reads_total(container, pod, device": {
        "metric": "container_fs_reads_total",
        "description": "sum of container_fs_reads_total by container, pod, and device.",
        "query": "sum by (container, pod, device) (rate(container_fs_reads_total{namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_fs_reads_total-container-_pod-_device"
    },
    "container_fs_writes_bytes_total(container, device)": {
        "metric": "container_fs_writes_bytes_total",
        "description": "sum of container_fs_writes_bytes_total by container and device.",
        "query": "sum by (container, device) (rate(container_fs_writes_bytes_total{namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_fs_writes_bytes_total-container-_device"
    },
    "container_fs_writes_bytes_total(container, pod, device": {
        "metric": "container_fs_writes_bytes_total",
        "description": "sum of container_fs_writes_bytes_total by container, pod, and device.",
        "query": "sum by (container, pod, device) (rate(container_fs_writes_bytes_total{namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_fs_writes_bytes_total-container-_pod-_device"
    },
    "container_fs_writes_total(container, device)": {
        "metric": "container_fs_writes_total",
        "description": "sum of container_fs_writes_total by container and device.",
        "query": "sum by (container, device) (rate(container_fs_writes_total{namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_fs_writes_total-container-_device"
    },
    "container_fs_writes_total(container, pod, device": {
        "metric": "container_fs_writes_total",
        "description": "sum of container_fs_writes_total by container, pod, and device.",
        "query": "sum by (container, pod, device) (rate(container_fs_writes_total{namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_fs_writes_total-container-_pod-_device"
    },
    "container_memory_failcnt(container)": {
        "metric": "container_memory_failcnt",
        "description": "sum of container_memory_failcnt by container.",
        "query": "sum by (container) (rate(container_memory_failcnt{namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_memory_failcnt-container"
    },
    "container_memory_failcnt(container, pod)": {
        "metric": "container_memory_failcnt",
        "description": "sum of container_memory_failcnt by container and pod.",
        "query": "sum by (container, pod) (rate(container_memory_failcnt{namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_memory_failcnt-container-_pod"
    },
    "container_memory_failures_total(container, failure_type)": {
        "metric": "container_memory_failures_total",
        "description": "sum of container_memory_failures_total by container and failure_type.",
        "query": "sum by (container) (rate(container_memory_failures_total{namespace=\"globeco\", scope=\"container\"}[__INTERVAL__]))",
        "name": "container_memory_failures_total-container-_failure_type"
    },
    "container_memory_failures_total(container, pod, failure_type)": {
        "metric": "container_memory_failures_total",
        "description": "sum of container_memory_failures_total by container, pod, and failure_type.",
        "query": "sum by (container, pod, failure_type) (rate(container_memory_failures_total{namespace=\"globeco\", scope=\"container\"}[__INTERVAL__]))",
        "name": "container_memory_failures_total-container-_pod-_failure_type"
    },
    "container_network_receive_bytes_total(pod)": {
        "metric": "container_network_receive_bytes_total",
        "description": "sum of container_network_receive_bytes_total by pod.",
        "query": "sum by (pod) (rate(container_network_receive_bytes_total{namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_network_receive_bytes_total-pod"
    },
    "container_network_receive_errors_total(pod)": {
        "metric": "container_network_receive_errors_total",
        "description": "sum of container_network_receive_errors_total by pod.",
        "query": "sum by (pod) (rate(container_network_receive_errors_total{namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_network_receive_errors_total-pod"
    },
    "container_network_receive_packets_dropped_total(pod)": {
        "metric": "container_network_receive_packets_dropped_total",
        "description": "sum of container_network_receive_packets_dropped_total by pod.",
        "query": "sum by (pod) (rate(container_network_receive_packets_dropped_total{namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_network_receive_packets_dropped_total-pod"
    },
    "container_network_receive_packets_total(pod)": {
        "metric": "container_network_receive_packets_total",
        "description": "sum of container_network_receive_packets_total by pod.",
        "query": "sum by (pod) (rate(container_network_receive_packets_total{namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_network_receive_packets_total-pod"
    },
    "container_network_transmit_bytes_total(pod)": {
        "metric": "container_network_transmit_bytes_total",
        "description": "sum of container_network_transmit_bytes_total by pod.",
        "query": "sum by (pod) (rate(container_network_transmit_bytes_total{namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_network_transmit_bytes_total-pod"
    },
    "container_network_transmit_errors_total(pod)": {
        "metric": "container_network_transmit_errors_total",
        "description": "sum of container_network_transmit_errors_total by pod.",
        "query": "sum by (pod) (rate(container_network_transmit_errors_total{namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_network_transmit_errors_total-pod"
    },
    "container_network_transmit_packets_dropped_total(pod)": {
        "metric": "container_network_transmit_packets_dropped_total",
        "description": "sum of container_network_transmit_packets_dropped_total by pod.",
        "query": "sum by (pod) (rate(container_network_transmit_packets_dropped_total{namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_network_transmit_packets_dropped_total-pod"
    },
    "container_network_transmit_packets_total(pod)": {
        "metric": "container_network_transmit_packets_total",
        "description": "sum of container_network_transmit_packets_total by pod.",
        "query": "sum by (pod) (rate(container_network_transmit_packets_total{namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_network_transmit_packets_total-pod"
    },
    "container_oom_events_total(container)": {
        "metric": "container_oom_events_total",
        "description": "sum of container_oom_events_total by container.",
        "query": "sum by (container) (rate(container_oom_events_total{namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_oom_events_total-container"
    },
    "container_pressure_cpu_stalled_seconds_total(container_label_io_kubernetes_container_name)": {
        "metric": "container_pressure_cpu_stalled_seconds_total",
        "description": "sum of container_pressure_cpu_stalled_seconds_total by container_label_io_kubernetes_container_name.",
        "query": "sum by (container_label_io_kubernetes_container_name) (rate(container_pressure_cpu_stalled_seconds_total{container_label_io_kubernetes_pod_namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_pressure_cpu_stalled_seconds_total-container_label_io_kubernetes_container_name"
    },
    "container_pressure_cpu_waiting_seconds_total(container_label_io_kubernetes_container_name)": {
        "metric": "container_pressure_cpu_waiting_seconds_total",
        "description": "sum of container_pressure_cpu_waiting_seconds_total by container_label_io_kubernetes_container_name.",
        "query": "sum by (container_label_io_kubernetes_container_name) (rate(container_pressure_cpu_waiting_seconds_total{container_label_io_kubernetes_pod_namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_pressure_cpu_waiting_seconds_total-container_label_io_kubernetes_container_name"
    },
    "container_pressure_io_stalled_seconds_total(container_label_io_kubernetes_container_name)": {
        "metric": "container_pressure_io_stalled_seconds_total",
        "description": "sum of container_pressure_io_stalled_seconds_total by container_label_io_kubernetes_container_name.",
        "query": "sum by (container_label_io_kubernetes_container_name) (rate(container_pressure_io_stalled_seconds_total{container_label_io_kubernetes_pod_namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_pressure_io_stalled_seconds_total-container_label_io_kubernetes_container_name"
    },
    "container_pressure_io_waiting_seconds_total(container_label_io_kubernetes_container_name)": {
        "metric": "container_pressure_io_waiting_seconds_total",
        "description": "sum of container_pressure_io_waiting_seconds_total by container_label_io_kubernetes_container_name.",
        "query": "sum by (container_label_io_kubernetes_container_name) (rate(container_pressure_io_waiting_seconds_total{container_label_io_kubernetes_pod_namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_pressure_io_waiting_seconds_total-container_label_io_kubernetes_container_name"
    },
    "container_pressure_memory_stalled_seconds_total(container_label_io_kubernetes_container_name)": {
        "metric": "container_pressure_memory_stalled_seconds_total",
        "description": "sum of container_pressure_memory_stalled_seconds_total by container_label_io_kubernetes_container_name.",
        "query": "sum by (container_label_io_kubernetes_container_name) (rate(container_pressure_memory_stalled_seconds_total{container_label_io_kubernetes_pod_namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_pressure_memory_stalled_seconds_total-container_label_io_kubernetes_container_name"
    },
    "container_pressure_memory_waiting_seconds_total(container_label_io_kubernetes_container_name)": {
        "metric": "container_pressure_memory_waiting_seconds_total",
        "description": "sum of container_pressure_memory_waiting_seconds_total by container_label_io_kubernetes_container_name.",
        "query": "sum by (container_label_io_kubernetes_container_name) (rate(container_pressure_memory_waiting_seconds_total{container_label_io_kubernetes_pod_namespace=\"globeco\"}[__INTERVAL__]))",
        "name": "container_pressure_memory_waiting_seconds_total-container_label_io_kubernetes_container_name"
    }
}
```


- Configuration for gauges:
```json
{
    "container_cpu_load_average_10s(container)": {
        "metric": "container_cpu_load_average_10s",
        "description": "sum of container_cpu_load_average_10s by container.",
        "query": "sum by (container) (container_cpu_load_average_10s{namespace=\"globeco\"})",
        "name": "container_cpu_load_average_10s-container"
    },
    "container_cpu_load_d_average_10s(container)": {
        "metric": "container_cpu_load_d_average_10s",
        "description": "sum of container_cpu_load_d_average_10s by container.",
        "query": "sum by (container) (container_cpu_load_d_average_10s{namespace=\"globeco\"})",
        "name": "container_cpu_load_d_average_10s-container"
    },
    "container_memory_max_usage_bytes(container)": {
        "metric": "container_memory_max_usage_bytes",
        "description": "sum of container_memory_max_usage_bytes by container.",
        "query": "sum by (container) (container_memory_max_usage_bytes{namespace=\"globeco\"})",
        "name": "container_memory_max_usage_bytes-container"
    },
    "container_memory_rss(container)": {
        "metric": "container_memory_rss",
        "description": "sum of container_memory_rss by container.",
        "query": "sum by (container) (container_memory_rss{namespace=\"globeco\"})",
        "name": "container_memory_rss-container"
    },
    "container_memory_swap(container)": {
        "metric": "container_memory_swap",
        "description": "sum of container_memory_swap by container.",
        "query": "sum by (container) (container_memory_swap{namespace=\"globeco\"})",
        "name": "container_memory_swap-container"
    },
    "container_memory_usage_bytes(container)": {
        "metric": "container_memory_usage_bytes",
        "description": "sum of container_memory_usage_bytes by container.",
        "query": "sum by (container) (container_memory_usage_bytes{namespace=\"globeco\"})",
        "name": "container_memory_usage_bytes-container"
    },
    "container_memory_working_set_bytes(container)": {
        "metric": "container_memory_working_set_bytes",
        "description": "sum of container_memory_working_set_bytes by container.",
        "query": "sum by (container) (container_memory_working_set_bytes{namespace=\"globeco\"})",
        "name": "container_memory_working_set_bytes-container"
    },
    "container_spec_cpu_period(container)": {
        "metric": "container_spec_cpu_period",
        "description": "sum of container_spec_cpu_period by container.",
        "query": "sum by (container) (container_spec_cpu_period{namespace=\"globeco\"})",
        "name": "container_spec_cpu_period-container"
    },
    "container_spec_cpu_quota(container)": {
        "metric": "container_spec_cpu_quota",
        "description": "sum of container_spec_cpu_quota by container.",
        "query": "sum by (container) (container_spec_cpu_quota{namespace=\"globeco\"})",
        "name": "container_spec_cpu_quota-container"
    },
    "container_spec_cpu_shares(container)": {
        "metric": "container_spec_cpu_shares",
        "description": "sum of container_spec_cpu_shares by container.",
        "query": "sum by (container) (container_spec_cpu_shares{namespace=\"globeco\"})",
        "name": "container_spec_cpu_shares-container"
    },
    "container_spec_memory_limit_bytes(container)": {
        "metric": "container_spec_memory_limit_bytes",
        "description": "sum of container_spec_memory_limit_bytes by container.",
        "query": "sum by (container) (container_spec_memory_limit_bytes{namespace=\"globeco\"})",
        "name": "container_spec_memory_limit_bytes-container"
    },
    "container_spec_memory_reservation_limit_bytes(container)": {
        "metric": "container_spec_memory_reservation_limit_bytes",
        "description": "sum of container_spec_memory_reservation_limit_bytes by container.",
        "query": "sum by (container) (container_spec_memory_reservation_limit_bytes{namespace=\"globeco\"})",
        "name": "container_spec_memory_reservation_limit_bytes-container"
    },
    "container_spec_memory_swap_limit_bytes(container)": {
        "metric": "container_spec_memory_swap_limit_bytes",
        "description": "sum of container_spec_memory_swap_limit_bytes by container.",
        "query": "sum by (container) (container_spec_memory_swap_limit_bytes{namespace=\"globeco\"})",
        "name": "container_spec_memory_swap_limit_bytes-container"
    },
    "kube_deployment_status_replicas(deployment)": {
        "metric": "kube_deployment_status_replicas",
        "description": "sum of kube_deployment_status_replicas by deployment.",
        "query": "sum by (deployment) (kube_deployment_status_replicas{namespace=\"globeco\"})",
        "name": "kube_deployment_status_replicas-deployment"
    },
    "kube_pod_container_resource_requests(container,cpu)": {
        "metric": "kube_pod_container_resource_requests",
        "description": "sum of kube_pod_container_resource_requests by container for cpu.",
        "query": "sum by (container) (kube_pod_container_resource_requests{namespace=\"globeco\", resource=\"cpu\"})",
        "name": "kube_pod_container_resource_requests-container,cpu"
    },
    "kube_pod_container_resource_requests(container,memory)": {
        "metric": "kube_pod_container_resource_requests",
        "description": "sum of kube_pod_container_resource_requests by container for memory.",
        "query": "sum by (container) (kube_pod_container_resource_requests{namespace=\"globeco\", resource=\"memory\", unit=\"byte\"})",
        "name": "kube_pod_container_resource_requests-container,memory"
    },
    "kube_pod_container_resource_limits(container,cpu)": {
        "metric": "kube_pod_container_resource_limits",
        "description": "sum of kube_pod_container_resource_limits by container for cpu.",
        "query": "sum by (container) (kube_pod_container_resource_limits{namespace=\"globeco\", resource=\"cpu\"})",
        "name": "kube_pod_container_resource_limits-container,cpu"
    },
    "kube_pod_container_resource_limits(container,memory)": {
        "metric": "kube_pod_container_resource_limits",
        "description": "sum of kube_pod_container_resource_limits by container for memory.",
        "query": "sum by (container) (kube_pod_container_resource_limits{namespace=\"globeco\", resource=\"memory\", unit=\"byte\"})",
        "name": "kube_pod_container_resource_limits-container,memory"
    }
}
```