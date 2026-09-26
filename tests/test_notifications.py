from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from porter.notifications import (
    FallbackReminderDelivery,
    TrayNotificationRequest,
    TraySocketReminderDelivery,
    decode_tray_notification,
    encode_tray_notification,
    tray_socket_path,
)
from porter.reminders import (
    Reminder,
    ReminderDeliveryError,
    ReminderKind,
    ReminderStatus,
)

NOW = datetime(2026, 9, 22, 15, tzinfo=UTC)


def _reminder() -> Reminder:
    return Reminder(
        id="reminder-1",
        principal_id="local-user",
        message="Tray delivery test",
        trigger_at=NOW,
        status=ReminderStatus.DELIVERING,
        created_at=NOW,
        updated_at=NOW,
        delivery_claimed_at=NOW,
    )


def test_tray_notification_round_trip() -> None:
    request = TrayNotificationRequest.from_reminder(_reminder())

    encoded = encode_tray_notification(request)

    assert encoded.endswith(b"\n")
    assert decode_tray_notification(encoded.rstrip(b"\n")) == request


def test_timer_notification_preserves_timer_identity() -> None:
    timer = _reminder()
    timer = replace(timer, kind=ReminderKind.TIMER, duration_seconds=30)
    request = TrayNotificationRequest.from_reminder(timer)
    assert request.kind is ReminderKind.TIMER
    assert decode_tray_notification(encode_tray_notification(request)) == request

    legacy = decode_tray_notification(
        b'{"reminder_id":"legacy","principal_id":"local-user","message":"Hi"}'
    )
    assert legacy.kind is ReminderKind.REMINDER


def test_tray_notification_rejects_invalid_payload() -> None:
    with pytest.raises(ValueError, match="must be non-empty text"):
        decode_tray_notification(
            b'{"reminder_id":"","principal_id":"local-user","message":"x"}'
        )


def test_tray_socket_path_uses_runtime_directory() -> None:
    assert tray_socket_path({"XDG_RUNTIME_DIR": "/run/user/1000"}) == Path(
        "/run/user/1000/porter/reminders.sock"
    )
    assert tray_socket_path({}) is None


@pytest.mark.asyncio
async def test_tray_socket_delivery_sends_request_and_requires_ack(
    tmp_path: Path,
) -> None:
    socket_path = tmp_path / "tray.sock"
    received: list[TrayNotificationRequest] = []

    async def handle(reader, writer) -> None:
        payload = await reader.readline()
        received.append(decode_tray_notification(payload.rstrip(b"\n")))
        writer.write(b"OK\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_unix_server(handle, path=socket_path)
    try:
        await TraySocketReminderDelivery(socket_path=socket_path).deliver(_reminder())
    finally:
        server.close()
        await server.wait_closed()

    assert received == [TrayNotificationRequest.from_reminder(_reminder())]


class _Delivery:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    async def deliver(self, _reminder: Reminder) -> None:
        self.calls += 1
        if self.fail:
            raise ReminderDeliveryError("unavailable")


@pytest.mark.asyncio
async def test_fallback_delivery_uses_fallback_only_when_primary_fails() -> None:
    primary = _Delivery(fail=True)
    fallback = _Delivery()
    delivery = FallbackReminderDelivery(primary, fallback)

    await delivery.deliver(_reminder())

    assert primary.calls == 1
    assert fallback.calls == 1


@pytest.mark.asyncio
async def test_fallback_delivery_skips_fallback_after_primary_success() -> None:
    primary = _Delivery()
    fallback = _Delivery()
    delivery = FallbackReminderDelivery(primary, fallback)

    await delivery.deliver(_reminder())

    assert primary.calls == 1
    assert fallback.calls == 0
