"""Metric definitions for Prometheus queries.

This module defines all metric queries used to collect performance data
from the Kubernetes cluster. Metrics are split into counter-type (which
require rate() wrapping) and gauge-type (instantaneous values).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricDefinition:
    """A single metric query definition."""

    metric: str
    description: str
    query: str
    name: str
    metric_type: str


COUNTER_METRICS: list[MetricDefinition] = [
    MetricDefinition(
        metric="container_blkio_device_usage_total",
        description="sum of container_blkio_device_usage_total by container, device, and operation",
        query='sum by (container, device, operation) (rate(container_blkio_device_usage_total{namespace="globeco"}[__INTERVAL__]))',
        name="container_blkio_device_usage_total-container-_device-_operation",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_cpu_cfs_periods_total",
        description="sum of container_cpu_cfs_periods_total by container.",
        query='sum by (container) (rate(container_cpu_cfs_periods_total{namespace="globeco"}[__INTERVAL__]))',
        name="container_cpu_cfs_periods_total-container",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_cpu_cfs_periods_total",
        description="sum of container_cpu_cfs_periods_total by container and pod.  Container level.",
        query='sum by (container, pod) (rate(container_cpu_cfs_periods_total{namespace="globeco"}[__INTERVAL__]))',
        name="container_cpu_cfs_periods_total-container-_pod",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_cpu_cfs_throttled_periods_total",
        description="sum of container_cpu_cfs_throttled_periods_total by container.",
        query='sum by (container) (rate(container_cpu_cfs_throttled_periods_total{namespace="globeco"}[__INTERVAL__]))',
        name="container_cpu_cfs_throttled_periods_total-container",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_cpu_cfs_throttled_periods_total",
        description="sum of container_cpu_cfs_throttled_periods_total by container and pod.",
        query='sum by (container, pod) (rate(container_cpu_cfs_throttled_periods_total{namespace="globeco"}[__INTERVAL__]))',
        name="container_cpu_cfs_throttled_periods_total-container-_pod",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_cpu_cfs_throttled_seconds_total",
        description="sum of container_cpu_cfs_throttled_seconds_total by container.",
        query='sum by (container) (rate(container_cpu_cfs_throttled_seconds_total{namespace="globeco"}[__INTERVAL__]))',
        name="container_cpu_cfs_throttled_seconds_total-container",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_cpu_cfs_throttled_seconds_total",
        description="sum of container_cpu_cfs_throttled_seconds_total by container and pod.",
        query='sum by (container, pod) (rate(container_cpu_cfs_throttled_seconds_total{namespace="globeco"}[__INTERVAL__]))',
        name="container_cpu_cfs_throttled_seconds_total-container-_pod",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_cpu_system_seconds_total",
        description="sum of container_cpu_system_seconds_total by container.",
        query='sum by (container) (rate(container_cpu_system_seconds_total{namespace="globeco"}[__INTERVAL__]))',
        name="container_cpu_system_seconds_total-container",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_cpu_system_seconds_total",
        description="sum of container_cpu_system_seconds_total by container and pod.",
        query='sum by (container, pod) (rate(container_cpu_system_seconds_total{namespace="globeco"}[__INTERVAL__]))',
        name="container_cpu_system_seconds_total-container-_pod",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_cpu_usage_seconds_total",
        description="sum of container_cpu_usage_seconds_total by container and pod.",
        query='sum by (container, pod) (rate(container_cpu_usage_seconds_total{namespace="globeco", cpu="total"}[__INTERVAL__]))',
        name="container_cpu_usage_seconds_total-container-_pod",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_cpu_usage_seconds_total",
        description="sum of container_cpu_usage_seconds_total by container.",
        query='sum by (container) (rate(container_cpu_usage_seconds_total{namespace="globeco", cpu="total"}[__INTERVAL__]))',
        name="container_cpu_usage_seconds_total-container",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_cpu_user_seconds_total",
        description="sum of container_cpu_user_seconds_total by container.",
        query='sum by (container) (rate(container_cpu_user_seconds_total{namespace="globeco"}[__INTERVAL__]))',
        name="container_cpu_user_seconds_total-container",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_cpu_user_seconds_total",
        description="sum of container_cpu_user_seconds_total by container and pod.",
        query='sum by (container, pod) (rate(container_cpu_user_seconds_total{namespace="globeco"}[__INTERVAL__]))',
        name="container_cpu_user_seconds_total-container-_pod",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_fs_reads_bytes_total",
        description="sum of container_fs_reads_bytes_total by container and device.",
        query='sum by (container, device) (rate(container_fs_reads_bytes_total{namespace="globeco"}[__INTERVAL__]))',
        name="container_fs_reads_bytes_total-container-_device",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_fs_reads_bytes_total",
        description="sum of container_fs_reads_bytes_total by container, pod, and device.",
        query='sum by (container, pod, device) (rate(container_fs_reads_bytes_total{namespace="globeco"}[__INTERVAL__]))',
        name="container_fs_reads_bytes_total-container-_pod-_device",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_fs_reads_total",
        description="sum of container_fs_reads_total by container and device.",
        query='sum by (container, device) (rate(container_fs_reads_total{namespace="globeco"}[__INTERVAL__]))',
        name="container_fs_reads_total-container-_device",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_fs_reads_total",
        description="sum of container_fs_reads_total by container, pod, and device.",
        query='sum by (container, pod, device) (rate(container_fs_reads_total{namespace="globeco"}[__INTERVAL__]))',
        name="container_fs_reads_total-container-_pod-_device",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_fs_writes_bytes_total",
        description="sum of container_fs_writes_bytes_total by container and device.",
        query='sum by (container, device) (rate(container_fs_writes_bytes_total{namespace="globeco"}[__INTERVAL__]))',
        name="container_fs_writes_bytes_total-container-_device",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_fs_writes_bytes_total",
        description="sum of container_fs_writes_bytes_total by container, pod, and device.",
        query='sum by (container, pod, device) (rate(container_fs_writes_bytes_total{namespace="globeco"}[__INTERVAL__]))',
        name="container_fs_writes_bytes_total-container-_pod-_device",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_fs_writes_total",
        description="sum of container_fs_writes_total by container and device.",
        query='sum by (container, device) (rate(container_fs_writes_total{namespace="globeco"}[__INTERVAL__]))',
        name="container_fs_writes_total-container-_device",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_fs_writes_total",
        description="sum of container_fs_writes_total by container, pod, and device.",
        query='sum by (container, pod, device) (rate(container_fs_writes_total{namespace="globeco"}[__INTERVAL__]))',
        name="container_fs_writes_total-container-_pod-_device",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_memory_failcnt",
        description="sum of container_memory_failcnt by container.",
        query='sum by (container) (rate(container_memory_failcnt{namespace="globeco"}[__INTERVAL__]))',
        name="container_memory_failcnt-container",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_memory_failcnt",
        description="sum of container_memory_failcnt by container and pod.",
        query='sum by (container, pod) (rate(container_memory_failcnt{namespace="globeco"}[__INTERVAL__]))',
        name="container_memory_failcnt-container-_pod",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_memory_failures_total",
        description="sum of container_memory_failures_total by container and failure_type.",
        query='sum by (container) (rate(container_memory_failures_total{namespace="globeco", scope="container"}[__INTERVAL__]))',
        name="container_memory_failures_total-container-_failure_type",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_memory_failures_total",
        description="sum of container_memory_failures_total by container, pod, and failure_type.",
        query='sum by (container, pod, failure_type) (rate(container_memory_failures_total{namespace="globeco", scope="container"}[__INTERVAL__]))',
        name="container_memory_failures_total-container-_pod-_failure_type",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_network_receive_bytes_total",
        description="sum of container_network_receive_bytes_total by pod.",
        query='sum by (pod) (rate(container_network_receive_bytes_total{namespace="globeco"}[__INTERVAL__]))',
        name="container_network_receive_bytes_total-pod",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_network_receive_errors_total",
        description="sum of container_network_receive_errors_total by pod.",
        query='sum by (pod) (rate(container_network_receive_errors_total{namespace="globeco"}[__INTERVAL__]))',
        name="container_network_receive_errors_total-pod",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_network_receive_packets_dropped_total",
        description="sum of container_network_receive_packets_dropped_total by pod.",
        query='sum by (pod) (rate(container_network_receive_packets_dropped_total{namespace="globeco"}[__INTERVAL__]))',
        name="container_network_receive_packets_dropped_total-pod",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_network_receive_packets_total",
        description="sum of container_network_receive_packets_total by pod.",
        query='sum by (pod) (rate(container_network_receive_packets_total{namespace="globeco"}[__INTERVAL__]))',
        name="container_network_receive_packets_total-pod",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_network_transmit_bytes_total",
        description="sum of container_network_transmit_bytes_total by pod.",
        query='sum by (pod) (rate(container_network_transmit_bytes_total{namespace="globeco"}[__INTERVAL__]))',
        name="container_network_transmit_bytes_total-pod",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_network_transmit_errors_total",
        description="sum of container_network_transmit_errors_total by pod.",
        query='sum by (pod) (rate(container_network_transmit_errors_total{namespace="globeco"}[__INTERVAL__]))',
        name="container_network_transmit_errors_total-pod",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_network_transmit_packets_dropped_total",
        description="sum of container_network_transmit_packets_dropped_total by pod.",
        query='sum by (pod) (rate(container_network_transmit_packets_dropped_total{namespace="globeco"}[__INTERVAL__]))',
        name="container_network_transmit_packets_dropped_total-pod",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_network_transmit_packets_total",
        description="sum of container_network_transmit_packets_total by pod.",
        query='sum by (pod) (rate(container_network_transmit_packets_total{namespace="globeco"}[__INTERVAL__]))',
        name="container_network_transmit_packets_total-pod",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_oom_events_total",
        description="sum of container_oom_events_total by container.",
        query='sum by (container) (rate(container_oom_events_total{namespace="globeco"}[__INTERVAL__]))',
        name="container_oom_events_total-container",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_pressure_cpu_stalled_seconds_total",
        description="sum of container_pressure_cpu_stalled_seconds_total by container_label_io_kubernetes_container_name.",
        query='sum by (container_label_io_kubernetes_container_name) (rate(container_pressure_cpu_stalled_seconds_total{container_label_io_kubernetes_pod_namespace="globeco"}[__INTERVAL__]))',
        name="container_pressure_cpu_stalled_seconds_total-container_label_io_kubernetes_container_name",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_pressure_cpu_waiting_seconds_total",
        description="sum of container_pressure_cpu_waiting_seconds_total by container_label_io_kubernetes_container_name.",
        query='sum by (container_label_io_kubernetes_container_name) (rate(container_pressure_cpu_waiting_seconds_total{container_label_io_kubernetes_pod_namespace="globeco"}[__INTERVAL__]))',
        name="container_pressure_cpu_waiting_seconds_total-container_label_io_kubernetes_container_name",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_pressure_io_stalled_seconds_total",
        description="sum of container_pressure_io_stalled_seconds_total by container_label_io_kubernetes_container_name.",
        query='sum by (container_label_io_kubernetes_container_name) (rate(container_pressure_io_stalled_seconds_total{container_label_io_kubernetes_pod_namespace="globeco"}[__INTERVAL__]))',
        name="container_pressure_io_stalled_seconds_total-container_label_io_kubernetes_container_name",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_pressure_io_waiting_seconds_total",
        description="sum of container_pressure_io_waiting_seconds_total by container_label_io_kubernetes_container_name.",
        query='sum by (container_label_io_kubernetes_container_name) (rate(container_pressure_io_waiting_seconds_total{container_label_io_kubernetes_pod_namespace="globeco"}[__INTERVAL__]))',
        name="container_pressure_io_waiting_seconds_total-container_label_io_kubernetes_container_name",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_pressure_memory_stalled_seconds_total",
        description="sum of container_pressure_memory_stalled_seconds_total by container_label_io_kubernetes_container_name.",
        query='sum by (container_label_io_kubernetes_container_name) (rate(container_pressure_memory_stalled_seconds_total{container_label_io_kubernetes_pod_namespace="globeco"}[__INTERVAL__]))',
        name="container_pressure_memory_stalled_seconds_total-container_label_io_kubernetes_container_name",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="container_pressure_memory_waiting_seconds_total",
        description="sum of container_pressure_memory_waiting_seconds_total by container_label_io_kubernetes_container_name.",
        query='sum by (container_label_io_kubernetes_container_name) (rate(container_pressure_memory_waiting_seconds_total{container_label_io_kubernetes_pod_namespace="globeco"}[__INTERVAL__]))',
        name="container_pressure_memory_waiting_seconds_total-container_label_io_kubernetes_container_name",
        metric_type="counter",
    ),
    # Kafka consumer counter metrics
    MetricDefinition(
        metric="kafka_consumer_messages_processed_total",
        description="sum of kafka_consumer_messages_processed_total by service_name and topic.",
        query='sum by (service_name, topic) (rate(kafka_consumer_messages_processed_total{service_namespace="globeco"}[__INTERVAL__]))',
        name="kafka_consumer_messages_processed_total-service_name-topic",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="kafka_consumer_messages_failed_total",
        description="sum of kafka_consumer_messages_failed_total by service_name and topic.",
        query='sum by (service_name, topic) (rate(kafka_consumer_messages_failed_total{service_namespace="globeco"}[__INTERVAL__]))',
        name="kafka_consumer_messages_failed_total-service_name-topic",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="kafka_consumer_processing_seconds_total",
        description="sum of kafka_consumer_processing_seconds_total by service_name and topic.",
        query='sum by (service_name, topic) (rate(kafka_consumer_processing_seconds_total{service_namespace="globeco"}[__INTERVAL__]))',
        name="kafka_consumer_processing_seconds_total-service_name-topic",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="kafka_consumer_idle_seconds_total",
        description="sum of kafka_consumer_idle_seconds_total by service_name and topic.",
        query='sum by (service_name, topic) (rate(kafka_consumer_idle_seconds_total{service_namespace="globeco"}[__INTERVAL__]))',
        name="kafka_consumer_idle_seconds_total-service_name-topic",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="kafka_consumer_records_polled_total",
        description="sum of kafka_consumer_records_polled_total by service_name and topic.",
        query='sum by (service_name, topic) (rate(kafka_consumer_records_polled_total{service_namespace="globeco"}[__INTERVAL__]))',
        name="kafka_consumer_records_polled_total-service_name-topic",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="kafka_consumer_poll_seconds_total",
        description="sum of kafka_consumer_poll_seconds_total by service_name and topic.",
        query='sum by (service_name, topic) (rate(kafka_consumer_poll_seconds_total{service_namespace="globeco"}[__INTERVAL__]))',
        name="kafka_consumer_poll_seconds_total-service_name-topic",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="kafka_dlq_messages",
        description="sum of kafka_dlq_messages by service_name and topic.",
        query='sum by (service_name, topic) (rate(kafka_dlq_messages{service_namespace="globeco"}[__INTERVAL__]))',
        name="kafka_dlq_messages-service_name-topic",
        metric_type="counter",
    ),
    MetricDefinition(
        metric="kafka_publish_success_total",
        description="kafka arrival rate",
        query='sum(rate(kafka_publish_success_total[__INTERVAL__]))',
        name="kafka_publish_success_total",
        metric_type="counter",
    ),
]


GAUGE_METRICS: list[MetricDefinition] = [
    MetricDefinition(
        metric="container_cpu_load_average_10s",
        description="sum of container_cpu_load_average_10s by container.",
        query='sum by (container) (container_cpu_load_average_10s{namespace="globeco"})',
        name="container_cpu_load_average_10s-container",
        metric_type="gauge",
    ),
    MetricDefinition(
        metric="container_cpu_load_d_average_10s",
        description="sum of container_cpu_load_d_average_10s by container.",
        query='sum by (container) (container_cpu_load_d_average_10s{namespace="globeco"})',
        name="container_cpu_load_d_average_10s-container",
        metric_type="gauge",
    ),
    MetricDefinition(
        metric="container_memory_max_usage_bytes",
        description="sum of container_memory_max_usage_bytes by container.",
        query='sum by (container) (container_memory_max_usage_bytes{namespace="globeco"})',
        name="container_memory_max_usage_bytes-container",
        metric_type="gauge",
    ),
    MetricDefinition(
        metric="container_memory_rss",
        description="sum of container_memory_rss by container.",
        query='sum by (container) (container_memory_rss{namespace="globeco"})',
        name="container_memory_rss-container",
        metric_type="gauge",
    ),
    MetricDefinition(
        metric="container_memory_swap",
        description="sum of container_memory_swap by container.",
        query='sum by (container) (container_memory_swap{namespace="globeco"})',
        name="container_memory_swap-container",
        metric_type="gauge",
    ),
    MetricDefinition(
        metric="container_memory_usage_bytes",
        description="sum of container_memory_usage_bytes by container.",
        query='sum by (container) (container_memory_usage_bytes{namespace="globeco"})',
        name="container_memory_usage_bytes-container",
        metric_type="gauge",
    ),
    MetricDefinition(
        metric="container_memory_working_set_bytes",
        description="sum of container_memory_working_set_bytes by container.",
        query='sum by (container) (container_memory_working_set_bytes{namespace="globeco"})',
        name="container_memory_working_set_bytes-container",
        metric_type="gauge",
    ),
    MetricDefinition(
        metric="container_spec_cpu_period",
        description="sum of container_spec_cpu_period by container.",
        query='sum by (container) (container_spec_cpu_period{namespace="globeco"})',
        name="container_spec_cpu_period-container",
        metric_type="gauge",
    ),
    MetricDefinition(
        metric="container_spec_cpu_quota",
        description="sum of container_spec_cpu_quota by container.",
        query='sum by (container) (container_spec_cpu_quota{namespace="globeco"})',
        name="container_spec_cpu_quota-container",
        metric_type="gauge",
    ),
    MetricDefinition(
        metric="container_spec_cpu_shares",
        description="sum of container_spec_cpu_shares by container.",
        query='sum by (container) (container_spec_cpu_shares{namespace="globeco"})',
        name="container_spec_cpu_shares-container",
        metric_type="gauge",
    ),
    MetricDefinition(
        metric="container_spec_memory_limit_bytes",
        description="sum of container_spec_memory_limit_bytes by container.",
        query='sum by (container) (container_spec_memory_limit_bytes{namespace="globeco"})',
        name="container_spec_memory_limit_bytes-container",
        metric_type="gauge",
    ),
    MetricDefinition(
        metric="container_spec_memory_reservation_limit_bytes",
        description="sum of container_spec_memory_reservation_limit_bytes by container.",
        query='sum by (container) (container_spec_memory_reservation_limit_bytes{namespace="globeco"})',
        name="container_spec_memory_reservation_limit_bytes-container",
        metric_type="gauge",
    ),
    MetricDefinition(
        metric="container_spec_memory_swap_limit_bytes",
        description="sum of container_spec_memory_swap_limit_bytes by container.",
        query='sum by (container) (container_spec_memory_swap_limit_bytes{namespace="globeco"})',
        name="container_spec_memory_swap_limit_bytes-container",
        metric_type="gauge",
    ),
    MetricDefinition(
        metric="kube_deployment_status_replicas",
        description="sum of kube_deployment_status_replicas by deployment.",
        query='sum by (deployment) (kube_deployment_status_replicas{namespace="globeco"})',
        name="kube_deployment_status_replicas-deployment",
        metric_type="gauge",
    ),
    MetricDefinition(
        metric="kube_pod_container_resource_requests",
        description="sum of kube_pod_container_resource_requests by container for cpu.",
        query='sum by (container) (kube_pod_container_resource_requests{namespace="globeco", resource="cpu"})',
        name="kube_pod_container_resource_requests-container,cpu",
        metric_type="gauge",
    ),
    MetricDefinition(
        metric="kube_pod_container_resource_requests",
        description="sum of kube_pod_container_resource_requests by container for memory.",
        query='sum by (container) (kube_pod_container_resource_requests{namespace="globeco", resource="memory", unit="byte"})',
        name="kube_pod_container_resource_requests-container,memory",
        metric_type="gauge",
    ),
    MetricDefinition(
        metric="kube_pod_container_resource_limits",
        description="sum of kube_pod_container_resource_limits by container for cpu.",
        query='sum by (container) (kube_pod_container_resource_limits{namespace="globeco", resource="cpu"})',
        name="kube_pod_container_resource_limits-container,cpu",
        metric_type="gauge",
    ),
    MetricDefinition(
        metric="kube_pod_container_resource_limits",
        description="sum of kube_pod_container_resource_limits by container for memory.",
        query='sum by (container) (kube_pod_container_resource_limits{namespace="globeco", resource="memory", unit="byte"})',
        name="kube_pod_container_resource_limits-container,memory",
        metric_type="gauge",
    ),
    # Kafka consumer group and partition gauge metrics
    MetricDefinition(
        metric="kafka_consumer_group_lag_ratio",
        description="kafka_consumer_group_lag_ratio gauge.",
        query="kafka_consumer_group_lag_ratio",
        name="kafka_consumer_group_lag_ratio",
        metric_type="gauge",
    ),
    MetricDefinition(
        metric="kafka_consumer_group_lag_sum_ratio",
        description="kafka_consumer_group_lag_sum_ratio gauge.",
        query="kafka_consumer_group_lag_sum_ratio",
        name="kafka_consumer_group_lag_sum_ratio",
        metric_type="gauge",
    ),
    MetricDefinition(
        metric="kafka_consumer_group_members",
        description="sum of kafka_consumer_group_members by instance and group.",
        query="sum by (instance,group) (kafka_consumer_group_members)",
        name="kafka_consumer_group_members-instance-group",
        metric_type="gauge",
    ),
    MetricDefinition(
        metric="kafka_consumer_group_offset_ratio",
        description="kafka_consumer_group_offset_ratio gauge.",
        query="kafka_consumer_group_offset_ratio",
        name="kafka_consumer_group_offset_ratio",
        metric_type="gauge",
    ),
    MetricDefinition(
        metric="kafka_consumer_group_offset_sum_ratio",
        description="kafka_consumer_group_offset_sum_ratio gauge.",
        query="kafka_consumer_group_offset_sum_ratio",
        name="kafka_consumer_group_offset_sum_ratio",
        metric_type="gauge",
    ),
    MetricDefinition(
        metric="kafka_dlq_messages_current",
        description="kafka_dlq_messages_current gauge.",
        query="kafka_dlq_messages_current",
        name="kafka_dlq_messages_current",
        metric_type="gauge",
    ),
    MetricDefinition(
        metric="kafka_partition_current_offset_ratio",
        description="kafka_partition_current_offset_ratio gauge.",
        query="kafka_partition_current_offset_ratio",
        name="kafka_partition_current_offset_ratio",
        metric_type="gauge",
    ),
    MetricDefinition(
        metric="kafka_partition_oldest_offset_ratio",
        description="kafka_partition_oldest_offset_ratio gauge.",
        query="kafka_partition_oldest_offset_ratio",
        name="kafka_partition_oldest_offset_ratio",
        metric_type="gauge",
    ),
    MetricDefinition(
        metric="kube_deployment_spec_replicas",
        description="kube_deployment_spec_replicas gauge.",
        query='sum by (deployment) (kube_deployment_spec_replicas{namespace="globeco"})',
        name="kube_deployment_spec_replicas",
        metric_type="gauge",
    ),MetricDefinition(
        metric="kube_deployment_status_replicas_available",
        description="kube_deployment_status_replicas_available gauge.",
        query='sum by (deployment) (kube_deployment_status_replicas_available{namespace="globeco"})',
        name="kube_deployment_status_replicas_available",
        metric_type="gauge",
    ),
    # Cluster/node-level resource request and usage ratios
    MetricDefinition(
        metric="cluster_pod_requested",
        description="ratio of running/pending pods to allocatable pods by node.",
        query="""
count by (node) (
  kube_pod_info
  * on (pod, namespace) group_left()
  (kube_pod_status_phase{phase=~"Running|Pending"} == 1)
)
/
sum by (node) (kube_node_status_allocatable{resource="pods"})
""",
        name="cluster_pod_requested",
        metric_type="gauge",
    ),
    MetricDefinition(
        metric="cluster_memory_requested",
        description="ratio of requested memory to allocatable memory by node.",
        query="""
sum by (node) (
  kube_pod_container_resource_requests{resource="memory"}
   *on (pod, namespace) group_left(node)
  (
    kube_pod_info
*     on (pod, namespace) group_left()
    (kube_pod_status_phase{phase=~"Running|Pending"} == 1)
  )
)
/
sum by (node) (
  kube_node_status_allocatable{resource="memory"}
)
""",
        name="cluster_memory_requested",
        metric_type="gauge",
    ),
    MetricDefinition(
        metric="cluster_cpu_requested",
        description="ratio of requested cpu to allocatable cpu by node.",
        query="""
sum by (node) (
  kube_pod_container_resource_requests{resource="cpu"}
   *on (pod, namespace) group_left(node)
  (
    kube_pod_info
*     on (pod, namespace) group_left()
    (kube_pod_status_phase{phase=~"Running|Pending"} == 1)
  )
)
/
sum by (node) (
  kube_node_status_allocatable{resource="cpu"}
)
""",
        name="cluster_cpu_requested",
        metric_type="gauge",
    ),
    MetricDefinition(
        metric="cpu_cores_by_node",
        description="requested cpu cores by node.",
        query="""sum by (node) (
  kube_pod_container_resource_requests{resource="cpu"}
  * on (namespace, pod) group_left(node)
  kube_pod_info
)""",
        name="cpu_cores_by_node",
        metric_type="gauge",
    ),
    MetricDefinition(
        metric="node_cpu_usage",
        description="average cpu usage by node.",
        query="""
  avg(1 - rate(node_cpu_seconds_total{mode="idle"}[__INTERVAL__])) by (node)""",
        name="node_cpu_usage",
        metric_type="gauge",
    ),
    MetricDefinition(
        metric="allocatable_cpu_usage_ratio",
        description="ratio of container cpu usage to allocatable cpu by node.",
        query="""
sum by (node) (
  label_replace(
    rate(container_cpu_usage_seconds_total{container!="", container!="POD"}[__INTERVAL__]),
    "node",
    "$1",
    "instance",
    "(.*)"
  )
)
/
sum by (node) (
  kube_node_status_allocatable{resource="cpu"}
)
""",
        name="allocatable_cpu_usage_ratio",
        metric_type="gauge",
    ),
    MetricDefinition(
        metric="cluster_cpu_usage",
        description="ratio of container cpu usage to allocatable cpu by node.",
        query="""
sum by (node) (
  label_replace(
    rate(
      container_cpu_usage_seconds_total{
        container!="",
        container!="POD"
      }[__INTERVAL__]
    ),
    "node",
    "$1",
    "instance",
    "(.*)"
  )
)
/
sum by (node) (
  kube_node_status_allocatable{resource="cpu"}
)
""",
        name="cluster_cpu_usage",
        metric_type="gauge",
    ),
]

ALL_METRICS: list[MetricDefinition] = COUNTER_METRICS + GAUGE_METRICS
