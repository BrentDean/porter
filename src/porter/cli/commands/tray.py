from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from porter.telemetry.structured_logging import configure_structured_logging
from porter.tray.app import main as tray_main
from porter.tray.autostart import TrayAutostartManager


def _autostart_manager() -> TrayAutostartManager:
    porter_executable = shutil.which("porter")
    if porter_executable is None:
        raise RuntimeError("tray autostart requires the porter executable")

    configured_home = os.environ.get("XDG_CONFIG_HOME")
    config_home = (
        Path(configured_home).expanduser()
        if configured_home
        else Path.home() / ".config"
    )
    return TrayAutostartManager(
        porter_executable=Path(porter_executable),
        config_home=config_home,
    )


def run(args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="porter tray",
        description="Run or manage Porter's desktop tray application",
    )
    subparsers = parser.add_subparsers(dest="action")
    subparsers.add_parser(
        "install",
        help="install Porter tray desktop-session autostart",
    )
    subparsers.add_parser(
        "status",
        help="report whether Porter tray autostart is installed",
    )
    subparsers.add_parser(
        "uninstall",
        help="remove Porter tray desktop-session autostart",
    )
    parsed = parser.parse_args(args)

    if parsed.action is None:
        try:
            tray_main()
        except SystemExit as exc:
            if exc.code is None:
                return 0
            if isinstance(exc.code, int):
                return exc.code
            print(exc.code, file=sys.stderr)
            return 1
        return 0

    try:
        manager = _autostart_manager()
        if parsed.action == "install":
            manager.install()
            print("Porter tray autostart")
            print(f"  entry: {manager.desktop_path}")
            print("  installed: yes")
            return 0

        if parsed.action == "status":
            print("Porter tray autostart")
            print(f"  entry: {manager.desktop_path}")
            print(f"  installed: {'yes' if manager.installed else 'no'}")
            return 0 if manager.installed else 1

        if parsed.action == "uninstall":
            manager.uninstall()
            print("Porter tray autostart")
            print(f"  entry: {manager.desktop_path}")
            print("  installed: no")
            return 0
    except RuntimeError as exc:
        print(f"porter tray: {exc}", file=sys.stderr)
        return 1

    raise AssertionError(f"unhandled tray action: {parsed.action}")


def main() -> None:
    configure_structured_logging()
    try:
        exit_code = run(sys.argv[1:])
    except KeyboardInterrupt:
        exit_code = 130
    raise SystemExit(exit_code)
