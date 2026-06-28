# Requirement 3: Miscellaneous improvements to the KASBench Runner

## Rename the POST /metrics API endpoint
Change the endpoint from POST /metrics to POST /metrics/export

## Add additional metrics

### Counters

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


## POST /prometheus/tsdb/export

## POST /output/export

## POST /db/export

