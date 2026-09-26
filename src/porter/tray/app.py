from __future__ import annotations

import sys


def main() -> None:
    try:
        from porter.tray.qt_app import run_tray
    except ModuleNotFoundError as exc:
        if exc.name == "PySide6" or (exc.name and exc.name.startswith("PySide6.")):
            print(
                "porter-tray: Qt support is not installed; "
                "install Porter with the 'tray' extra",
                file=sys.stderr,
            )
            raise SystemExit(1) from None
        raise

    raise SystemExit(run_tray())
