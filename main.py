"""KASBench Benchmark Runner application entrypoint."""

import uvicorn

from kasbench_runner.app import create_app
from kasbench_runner.config import RunnerConfig

app = create_app()


def main():
    config = RunnerConfig()
    uvicorn.run(
        "main:app",
        host=config.host,
        port=config.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
