"""Prometheus client for executing PromQL range queries.

This module handles URL construction, interval substitution, and sequential
execution of range queries against the cluster's Prometheus instance.
"""

from dataclasses import dataclass

import httpx
import structlog

from kasbench_runner.services.metrics_config import MetricDefinition

logger = structlog.get_logger(__name__)


@dataclass
class QueryResult:
    """Result of a single Prometheus range query."""

    metric_name: str
    success: bool
    response_json: dict | None = None
    error_message: str | None = None


@dataclass
class QuerySummary:
    """Aggregate result after all queries complete."""

    results: list[QueryResult]

    @property
    def successful(self) -> list[QueryResult]:
        return [r for r in self.results if r.success]

    @property
    def failed(self) -> list[QueryResult]:
        return [r for r in self.results if not r.success]

    @property
    def all_succeeded(self) -> bool:
        return len(self.failed) == 0


class PrometheusClient:
    """Client for executing PromQL range queries against Prometheus.

    Constructs the Prometheus URL from the control plane node hostname,
    performs interval substitution on query templates, and executes all
    configured metric queries sequentially.
    """

    def __init__(
        self,
        control_plane_node: str,
        connect_timeout: float = 10.0,
        read_timeout: float = 30.0,
    ) -> None:
        self._control_plane_node = control_plane_node
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout

    def build_url(self) -> str:
        """Return the Prometheus range query API URL.

        Returns:
            URL in the format http://{control_plane_node}:32080/api/v1/query_range
        """
        return f"http://{self._control_plane_node}:32080/api/v1/query_range"

    def substitute_interval(self, query: str, interval: str) -> str:
        """Replace __INTERVAL__ placeholders with the interval value.

        If the interval is empty or blank, defaults to "60s".
        If the query does not contain __INTERVAL__, it is returned unchanged.

        Args:
            query: PromQL query template, may contain __INTERVAL__ placeholders.
            interval: Duration string to substitute (e.g. "60s", "5m").

        Returns:
            The query with all __INTERVAL__ occurrences replaced.
        """
        if not interval or not interval.strip():
            interval = "60s"

        return query.replace("__INTERVAL__", interval)

    async def execute_all(
        self,
        metrics: list[MetricDefinition],
        start_ts: float,
        end_ts: float,
        step: str,
        interval: str,
    ) -> QuerySummary:
        """Execute all metric queries sequentially, accumulating results.

        Each query is executed as a Prometheus range query. Failures are
        recorded without halting execution of remaining queries.

        Args:
            metrics: List of metric definitions to query.
            start_ts: Start time as Unix timestamp (seconds).
            end_ts: End time as Unix timestamp (seconds).
            step: Prometheus step duration string (e.g. "15s").
            interval: Interval value for __INTERVAL__ substitution.

        Returns:
            QuerySummary containing results for all attempted queries.
        """
        url = self.build_url()
        results: list[QueryResult] = []

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=self._connect_timeout,
                read=self._read_timeout,
                write=10.0,
                pool=10.0,
            ),
        ) as client:
            for metric in metrics:
                log = logger.bind(metric_name=metric.name, url=url)
                query = self.substitute_interval(metric.query, interval)

                params = {
                    "query": query,
                    "start": str(start_ts),
                    "end": str(end_ts),
                    "step": step,
                }

                try:
                    log.info("prometheus_query_start", query=query)
                    response = await client.get(url, params=params)
                except httpx.HTTPError as exc:
                    error_msg = (
                        f"Connection error querying {url}: "
                        f"{type(exc).__name__}: {exc}"
                    )
                    log.error("prometheus_query_connection_error", error=error_msg)
                    results.append(
                        QueryResult(
                            metric_name=metric.name,
                            success=False,
                            error_message=error_msg,
                        )
                    )
                    continue

                if response.status_code == 200:
                    log.info("prometheus_query_success")
                    results.append(
                        QueryResult(
                            metric_name=metric.name,
                            success=True,
                            response_json=response.json(),
                        )
                    )
                else:
                    error_msg = (
                        f"Prometheus returned HTTP {response.status_code} "
                        f"for {url}: {response.text}"
                    )
                    log.error(
                        "prometheus_query_http_error",
                        status_code=response.status_code,
                        response_body=response.text[:500],
                    )
                    results.append(
                        QueryResult(
                            metric_name=metric.name,
                            success=False,
                            error_message=error_msg,
                        )
                    )

        return QuerySummary(results=results)
