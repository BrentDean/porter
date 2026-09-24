from __future__ import annotations

import stat
from pathlib import Path

from porter.tray.autostart import TrayAutostartManager, _quote_exec_arg


def _manager(tmp_path: Path) -> TrayAutostartManager:
    return TrayAutostartManager(
        porter_executable=tmp_path / "venv path" / "bin" / "porter",
        config_home=tmp_path / "config",
    )


def test_quote_exec_arg_escapes_desktop_exec_characters() -> None:
    assert _quote_exec_arg('a b"$`c\\d') == '"a b\\"\\$\\`c\\\\d"'


def test_install_writes_exact_porter_tray_autostart_entry(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    manager.install()

    assert manager.installed is True
    content = manager.desktop_path.read_text(encoding="utf-8")
    assert f'Exec="{tmp_path}/venv path/bin/porter" tray' in content
    assert "Terminal=false" in content
    assert "X-GNOME-Autostart-enabled=true" in content
    assert stat.S_IMODE(manager.desktop_path.stat().st_mode) == 0o644


def test_uninstall_removes_entry_and_is_idempotent(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.install()

    manager.uninstall()
    manager.uninstall()

    assert manager.installed is False
