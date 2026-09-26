from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path

_UNIT_NAME = "porter-reminders.service"


def _quote_unit_arg(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


class UserServiceManager:
    """Manage Porter's reminder worker as a systemd user service."""

    def __init__(
        self,
        *,
        porter_executable: Path,
        systemctl_path: Path,
        config_home: Path,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self._porter_executable = Path(porter_executable)
        self._systemctl_path = Path(systemctl_path)
        self._config_home = Path(config_home)
        self._runner = runner

    @property
    def unit_path(self) -> Path:
        return (
            self._config_home
            / "systemd"
            / "user"
            / _UNIT_NAME
        )

    @property
    def installed(self) -> bool:
        return self.unit_path.is_file()

    def render_unit(self) -> str:
        porter_arg = _quote_unit_arg(str(self._porter_executable))
        return (
            "[Unit]\n"
            "Description=Porter local reminder delivery\n"
            "After=graphical-session.target\n"
            "\n"
            "[Service]\n"
            "Type=simple\n"
            f"ExecStart={porter_arg} service\n"
            "Restart=on-failure\n"
            "RestartSec=5s\n"
            "Environment=PYTHONUNBUFFERED=1\n"
            "\n"
            "[Install]\n"
            "WantedBy=default.target\n"
        )

    def install(self, *, enable_now: bool = False) -> None:
        self.unit_path.parent.mkdir(parents=True, exist_ok=True)

        temporary_path = self.unit_path.with_suffix(".service.tmp")
        temporary_path.write_text(self.render_unit(), encoding="utf-8")
        os.chmod(temporary_path, 0o644)
        os.replace(temporary_path, self.unit_path)

        self._systemctl("daemon-reload")
        if enable_now:
            self._systemctl("enable", "--now", _UNIT_NAME)

    def uninstall(self) -> None:
        if self.installed:
            self._systemctl(
                "disable",
                "--now",
                _UNIT_NAME,
                check=False,
            )
            self.unit_path.unlink()
            self._systemctl("daemon-reload")

    def is_active(self) -> bool:
        result = self._systemctl(
            "is-active",
            "--quiet",
            _UNIT_NAME,
            check=False,
        )
        return result.returncode == 0

    def _systemctl(
        self,
        *args: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return self._runner(
            [
                str(self._systemctl_path),
                "--user",
                *args,
            ],
            check=check,
            capture_output=True,
            text=True,
        )
