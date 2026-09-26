from __future__ import annotations

import argparse
import asyncio
import sys

from porter.app import build_application
from porter.cli.repl import _run_once, _run_repl
from porter.telemetry.structured_logging import configure_structured_logging

_INFO_LOG_COMMANDS = frozenset({"service", "web"})

_COMMANDS = (
    "ask",
    "backup",
    "config",
    "doctor",
    "reliability",
    "training",
    "service",
    "tray",
    "web",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="porter",
        description="Private local-first AI assistant",
        epilog=(
            "commands: ask, backup, config, doctor, reliability, training, service, tray, web; "
            "natural-language requests may also be passed directly"
        ),
    )
    parser.add_argument(
        "prompt",
        nargs="*",
        help="run one request instead of starting interactive mode",
    )
    return parser


async def _run_default(raw_args: list[str]) -> int:
    parsed = _parser().parse_args(raw_args)
    application = build_application()
    if parsed.prompt:
        return await _run_once(application, " ".join(parsed.prompt))
    return await _run_repl(application)


def _run_command(raw_args: list[str]) -> int | None:
    if not raw_args or raw_args[0] not in _COMMANDS:
        return None

    command, *command_args = raw_args
    if command == "ask":
        from porter.cli.commands import ask

        return asyncio.run(ask.run(command_args))
    if command == "backup":
        from porter.cli.commands import backup

        return backup.run(command_args)
    if command == "config":
        from porter.cli.commands import config

        return config.run(command_args)
    if command == "doctor":
        from porter.cli.commands import doctor

        return asyncio.run(doctor.run(command_args))
    if command == "reliability":
        from porter.cli.commands import reliability

        return reliability.run(command_args)
    if command == "training":
        from porter.cli.commands import training

        return training.run(build_application(), command_args)
    if command == "service":
        from porter.cli.commands import service

        return asyncio.run(service.run(command_args))
    if command == "tray":
        from porter.cli.commands import tray

        return tray.run(command_args)
    if command == "web":
        from porter.cli.commands import web

        return web.run(command_args)
    raise AssertionError(f"unhandled CLI command: {command}")


def _main(args: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if args is None else args)
    command_result = _run_command(raw_args)
    if command_result is not None:
        return command_result
    return asyncio.run(_run_default(raw_args))


def _default_log_level(raw_args: list[str]) -> str:
    if raw_args and raw_args[0] in _INFO_LOG_COMMANDS:
        return "INFO"
    return "WARNING"


def main() -> None:
    raw_args = list(sys.argv[1:])
    configure_structured_logging(
        default_level=_default_log_level(raw_args),
    )
    try:
        exit_code = _main(raw_args)
    except KeyboardInterrupt:
        exit_code = 130
    raise SystemExit(exit_code)
