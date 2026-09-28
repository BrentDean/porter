from __future__ import annotations

import os
from pathlib import Path

_DESKTOP_NAME = "porter-tray.desktop"


def _quote_exec_arg(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "\\$")
        .replace("`", "\\`")
    )
    return f'"{escaped}"'


class TrayAutostartManager:
    """Manage the desktop-session autostart entry for Porter's tray."""

    def __init__(
        self,
        *,
        porter_executable: Path,
        config_home: Path,
    ) -> None:
        self._porter_executable = Path(porter_executable)
        self._config_home = Path(config_home)

    @property
    def desktop_path(self) -> Path:
        return self._config_home / "autostart" / _DESKTOP_NAME

    @property
    def installed(self) -> bool:
        return self.desktop_path.is_file()

    def render_entry(self) -> str:
        porter_arg = _quote_exec_arg(str(self._porter_executable))
        return (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Porter Tray\n"
            "Comment=Porter reminders and desktop notifications\n"
            f"Exec={porter_arg} tray\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n"
        )

    def install(self) -> None:
        self.desktop_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.desktop_path.with_suffix(".desktop.tmp")
        temporary_path.write_text(self.render_entry(), encoding="utf-8")
        os.chmod(temporary_path, 0o644)
        os.replace(temporary_path, self.desktop_path)

    def uninstall(self) -> None:
        self.desktop_path.unlink(missing_ok=True)
