from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

from porter.service.cli import run as run_service
from porter.service.systemd import UserServiceManager
from porter.telemetry.structured_logging import configure_structured_logging


def _user_service_manager() -> UserServiceManager:
    systemctl = shutil.which("systemctl")
    if systemctl is None:
        raise RuntimeError("systemd service management requires systemctl")

    porter_executable = shutil.which("porter")
    if porter_executable is None:
        raise RuntimeError("service installation requires the porter executable")

    configured_home = os.environ.get("XDG_CONFIG_HOME")
    config_home = (
        Path(configured_home).expanduser()
        if configured_home
        else Path.home() / ".config"
    )

    return UserServiceManager(
        porter_executable=Path(porter_executable),
        systemctl_path=Path(systemctl),
        config_home=config_home,
    )


async def run(args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="porter service",
        description="Run or manage Porter's local reminder service",
    )
    subparsers = parser.add_subparsers(dest="action")

    install_parser = subparsers.add_parser(
        "install",
        help="install the reminder worker as a systemd user service",
    )
    install_parser.add_argument(
        "--enable-now",
        action="store_true",
        help="enable and start the installed user service immediately",
    )

    subparsers.add_parser(
        "status",
        help="report whether the installed user service is active",
    )
    subparsers.add_parser(
        "uninstall",
        help="stop, disable, and remove the systemd user service",
    )

    parsed = parser.parse_args(args)
    if parsed.action is None:
        await run_service()
        return 0

    try:
        manager = _user_service_manager()
        if parsed.action == "install":
            manager.install(enable_now=parsed.enable_now)
            print("Porter reminder service")
            print(f"  unit: {manager.unit_path}")
            print("  installed: yes")
            print(
                "  active: requested"
                if parsed.enable_now
                else "  active: unchanged (use --enable-now to start)"
            )
            return 0

        if parsed.action == "status":
            active = manager.is_active()
            print("Porter reminder service")
            print(f"  unit: {manager.unit_path}")
            print(f"  installed: {'yes' if manager.installed else 'no'}")
            print(f"  active: {'yes' if active else 'no'}")
            return 0 if active else 1

        if parsed.action == "uninstall":
            manager.uninstall()
            print("Porter reminder service")
            print(f"  unit: {manager.unit_path}")
            print("  installed: no")
            return 0
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"porter service: {exc}", file=sys.stderr)
        return 1

    raise AssertionError(f"unhandled service action: {parsed.action}")


def main() -> None:
    configure_structured_logging()
    try:
        exit_code = asyncio.run(run(sys.argv[1:]))
    except KeyboardInterrupt:
        exit_code = 130
    raise SystemExit(exit_code)
