from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from porter.cli.commands import tray


def test_tray_install(monkeypatch: pytest.MonkeyPatch, capsys, tmp_path: Path) -> None:
    calls: list[str] = []
    manager = SimpleNamespace(
        desktop_path=tmp_path / "porter-tray.desktop",
        install=lambda: calls.append("install"),
    )
    monkeypatch.setattr(tray, "_autostart_manager", lambda: manager)

    assert tray.run(["install"]) == 0
    assert calls == ["install"]
    assert "installed: yes" in capsys.readouterr().out


def test_tray_status_returns_nonzero_when_absent(
    monkeypatch: pytest.MonkeyPatch,
    capsys,
    tmp_path: Path,
) -> None:
    manager = SimpleNamespace(
        desktop_path=tmp_path / "porter-tray.desktop",
        installed=False,
    )
    monkeypatch.setattr(tray, "_autostart_manager", lambda: manager)

    assert tray.run(["status"]) == 1
    assert "installed: no" in capsys.readouterr().out


def test_tray_uninstall(monkeypatch: pytest.MonkeyPatch, capsys, tmp_path: Path) -> None:
    calls: list[str] = []
    manager = SimpleNamespace(
        desktop_path=tmp_path / "porter-tray.desktop",
        uninstall=lambda: calls.append("uninstall"),
    )
    monkeypatch.setattr(tray, "_autostart_manager", lambda: manager)

    assert tray.run(["uninstall"]) == 0
    assert calls == ["uninstall"]
    assert "installed: no" in capsys.readouterr().out


def test_tray_without_management_action_runs_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_main() -> None:
        calls.append("run")
        raise SystemExit(0)

    monkeypatch.setattr(tray, "tray_main", fake_main)

    assert tray.run([]) == 0
    assert calls == ["run"]
