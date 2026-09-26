from __future__ import annotations

from types import SimpleNamespace

import pytest

import porter.service.cli as service_cli
from porter.notifications import FallbackReminderDelivery


def test_desktop_service_runtime_requires_notify_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service_cli.shutil, "which", lambda _name: None)

    with pytest.raises(RuntimeError, match="require the notify-send executable"):
        service_cli.build_desktop_service_runtime()


def test_desktop_service_runtime_uses_tray_first_delivery_with_notify_send_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    expected_runtime = SimpleNamespace(service=object())

    monkeypatch.setattr(
        service_cli.shutil,
        "which",
        lambda name: "/usr/bin/notify-send" if name == "notify-send" else None,
    )

    def fake_build_service_runtime(delivery):
        captured["delivery"] = delivery
        return expected_runtime

    monkeypatch.setattr(
        service_cli,
        "build_service_runtime",
        fake_build_service_runtime,
    )

    runtime = service_cli.build_desktop_service_runtime()

    assert runtime is expected_runtime
    assert isinstance(captured["delivery"], FallbackReminderDelivery)


@pytest.mark.asyncio
async def test_run_uses_composed_service_until_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = object()
    runtime = SimpleNamespace(service=service)
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        service_cli,
        "build_desktop_service_runtime",
        lambda: runtime,
    )

    async def fake_run_until_shutdown(candidate) -> None:
        captured["service"] = candidate

    monkeypatch.setattr(
        service_cli,
        "run_until_shutdown",
        fake_run_until_shutdown,
    )

    await service_cli.run()

    assert captured["service"] is service
