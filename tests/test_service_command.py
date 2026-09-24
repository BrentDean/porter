from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from porter.cli.commands import service


@pytest.mark.asyncio
async def test_service_install_enable_now(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    calls: list[bool] = []
    manager = SimpleNamespace(
        unit_path=tmp_path / "porter-reminders.service",
        install=lambda *, enable_now: calls.append(enable_now),
    )
    monkeypatch.setattr(service, "_user_service_manager", lambda: manager)

    result = await service.run(["install", "--enable-now"])

    assert result == 0
    assert calls == [True]
    output = capsys.readouterr().out
    assert "installed: yes" in output
    assert "active: requested" in output


@pytest.mark.asyncio
async def test_service_status_returns_nonzero_when_inactive(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    manager = SimpleNamespace(
        unit_path=tmp_path / "porter-reminders.service",
        installed=True,
        is_active=lambda: False,
    )
    monkeypatch.setattr(service, "_user_service_manager", lambda: manager)

    result = await service.run(["status"])

    assert result == 1
    output = capsys.readouterr().out
    assert "installed: yes" in output
    assert "active: no" in output


@pytest.mark.asyncio
async def test_service_uninstall(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    manager = SimpleNamespace(
        unit_path=tmp_path / "porter-reminders.service",
        uninstall=lambda: calls.append("uninstall"),
    )
    monkeypatch.setattr(service, "_user_service_manager", lambda: manager)

    result = await service.run(["uninstall"])

    assert result == 0
    assert calls == ["uninstall"]
    assert "installed: no" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_service_without_management_action_runs_foreground(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fake_run_service() -> None:
        calls.append("run")

    monkeypatch.setattr(service, "run_service", fake_run_service)

    result = await service.run([])

    assert result == 0
    assert calls == ["run"]
