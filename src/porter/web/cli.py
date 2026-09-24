from __future__ import annotations

import argparse
import os

import uvicorn

from porter.web.app import create_web_app

_LOCAL_HOST = "127.0.0.1"
_DEFAULT_PORT = 8000
_WEB_HOST_ENV = "PORTER_WEB_HOST"


def _port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65_535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="porter-web",
        description="Run Porter's HTTP API (localhost by default)",
    )
    parser.add_argument(
        "--port",
        type=_port,
        default=_DEFAULT_PORT,
        help=f"TCP port (default: {_DEFAULT_PORT})",
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    host = os.environ.get(_WEB_HOST_ENV, _LOCAL_HOST).strip()
    if not host:
        raise ValueError(f"{_WEB_HOST_ENV} must not be empty")
    uvicorn.run(
        create_web_app(),
        host=host,
        port=args.port,
    )
