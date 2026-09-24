from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping

import uvicorn

from porter.telemetry.structured_logging import configure_structured_logging
from porter.web.app import create_web_app

_LOCAL_HOST = "127.0.0.1"
_DEFAULT_PORT = 8000
_WEB_HOST_ENV = "PORTER_WEB_HOST"


def _port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65_535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _parser(*, prog: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Run Porter's HTTP API (localhost by default)",
    )
    parser.add_argument(
        "--port",
        type=_port,
        default=_DEFAULT_PORT,
        help=f"TCP port (default: {_DEFAULT_PORT})",
    )
    return parser


def _host(env: Mapping[str, str]) -> str:
    configured = env.get(_WEB_HOST_ENV)
    if configured is None:
        return _LOCAL_HOST

    host = configured.strip()
    if not host:
        raise ValueError(f"{_WEB_HOST_ENV} must not be empty")
    return host


def run(
    args: list[str],
    *,
    prog: str = "porter web",
    env: Mapping[str, str] | None = None,
) -> int:
    parsed = _parser(prog=prog).parse_args(args)
    uvicorn.run(
        create_web_app(),
        host=_host(os.environ if env is None else env),
        port=parsed.port,
    )
    return 0


def main() -> None:
    configure_structured_logging()
    try:
        exit_code = run(sys.argv[1:], prog="porter-web")
    except KeyboardInterrupt:
        exit_code = 130
    raise SystemExit(exit_code)
