"""Tests for metrics configuration structure.

Validates that COUNTER_METRICS, GAUGE_METRICS, and ALL_METRICS are
correctly defined with expected counts, non-empty fields, and appropriate
query patterns.
"""

from kasbench_runner.services.metrics_config import (
    ALL_METRICS,
    COUNTER_METRICS,
    GAUGE_METRICS,
    MetricDefinition,
)


def test_counter_metrics_count():
    """COUNTER_METRICS should have exactly 36 entries."""
    assert len(COUNTER_METRICS) == 36


def test_gauge_metrics_count():
    """GAUGE_METRICS should have exactly 18 entries."""
    assert len(GAUGE_METRICS) == 18


def test_all_metrics_count():
    """ALL_METRICS should have exactly 54 entries (36 + 18)."""
    assert len(ALL_METRICS) == 54


def test_all_metrics_is_concatenation():
    """ALL_METRICS should be COUNTER_METRICS + GAUGE_METRICS."""
    assert ALL_METRICS == COUNTER_METRICS + GAUGE_METRICS


def test_all_entries_have_non_empty_fields():
    """Every metric definition must have non-empty metric, description, query, name, and metric_type."""
    for entry in ALL_METRICS:
        assert isinstance(entry, MetricDefinition)
        assert entry.metric.strip(), f"Empty 'metric' field in entry: {entry.name}"
        assert entry.description.strip(), f"Empty 'description' field in entry: {entry.name}"
        assert entry.query.strip(), f"Empty 'query' field in entry: {entry.name}"
        assert entry.name.strip(), f"Empty 'name' field in entry: {entry.name}"
        assert entry.metric_type.strip(), f"Empty 'metric_type' field in entry: {entry.name}"


def test_counter_queries_contain_interval_placeholder():
    """All counter metric queries must contain the __INTERVAL__ placeholder."""
    for entry in COUNTER_METRICS:
        assert "__INTERVAL__" in entry.query, (
            f"Counter metric '{entry.name}' query missing __INTERVAL__ placeholder"
        )


def test_gauge_queries_do_not_contain_interval_placeholder():
    """No gauge metric query should contain the __INTERVAL__ placeholder."""
    for entry in GAUGE_METRICS:
        assert "__INTERVAL__" not in entry.query, (
            f"Gauge metric '{entry.name}' query should not contain __INTERVAL__ placeholder"
        )
