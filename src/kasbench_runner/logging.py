"""Structured logging configuration for the KASBench Benchmark Runner.

Configures structlog with JSON output, ISO 8601 timestamps in UTC,
log level, event name, and support for bound context fields.

Requirements: 13.1
"""

import logging
import sys

import structlog


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog with JSON output and ISO 8601 UTC timestamps.

    Sets up the structlog processor chain to produce structured JSON log
    entries containing timestamp, log level, event name, and any bound
    context fields.

    Args:
        level: Minimum log level (DEBUG, INFO, WARNING, ERROR). Defaults to INFO.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Configure the standard library logging to route through structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
