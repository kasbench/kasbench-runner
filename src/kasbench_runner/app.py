"""FastAPI application factory for the KASBench Benchmark Runner.

Creates and configures the FastAPI application with lifespan management,
route registration, and global error handling.

Requirements: 1.1, 11.1
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from kasbench_runner.config import RunnerConfig
from kasbench_runner.errors import RunnerError, build_error_response
from kasbench_runner.logging import configure_logging
from kasbench_runner.models.state import BenchmarkState
from kasbench_runner.routes import abort, db, initialize, metrics, output, start, status

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown lifecycle.

    On startup:
      - Configures structured logging
      - Creates RunnerConfig from environment variables
      - Creates BenchmarkState with NOT_INITIALIZED status
      - Stores both on app.state for dependency injection

    On shutdown:
      - Logs shutdown event
    """
    configure_logging()

    config = RunnerConfig()
    benchmark_state = BenchmarkState()

    app.state.config = config
    app.state.benchmark_state = benchmark_state

    logger.info(
        "application_started",
        host=config.host,
        port=config.port,
    )

    yield

    logger.info("application_shutdown")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Fully configured FastAPI instance with routes and error handlers registered.
    """
    app = FastAPI(
        title="KASBench Benchmark Runner",
        lifespan=lifespan,
    )

    # Register route modules
    app.include_router(initialize.router)
    app.include_router(start.router)
    app.include_router(status.router)
    app.include_router(output.router)
    app.include_router(db.router)
    app.include_router(abort.router)
    app.include_router(metrics.router)

    # Register global exception handler for RunnerError
    @app.exception_handler(RunnerError)
    async def runner_error_handler(request: Request, exc: RunnerError) -> JSONResponse:
        return build_error_response(
            error=exc.error,
            message=exc.message,
            status_code=500,
            **exc.context,
        )

    return app
