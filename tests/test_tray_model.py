from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from porter.reminders import Reminder, ReminderKind, ReminderStatus
from porter.tray.model import (
    build_tray_snapshot,
    format_timer_countdown,
    format_tray_reminder,
)

NOW = datetime(2026, 8, 15, 20, tzinfo=UTC)


class FakeReminderService:
    def __init__(self, reminders: tuple[Reminder, ...]) -> None:
        self._reminders = reminders

    def list_reminders(self, principal_id: str, *, status=None):
        return tuple(
            reminder
            for reminder in self._reminders
            if reminder.principal_id == principal_id
            and (status is None or reminder.status is status)
        )


def _scheduled(reminder_id: str, message: str, minutes: int) -> Reminder:
    return Reminder(
        id=reminder_id,
        principal_id="local-user",
        message=message,
        trigger_at=NOW + timedelta(minutes=minutes),
        status=ReminderStatus.SCHEDULED,
        created_at=NOW,
        updated_at=NOW,
    )


def _delivered(reminder_id: str, message: str, minutes_ago: int) -> Reminder:
    delivered_at = NOW - timedelta(minutes=minutes_ago)
    return Reminder(
        id=reminder_id,
        principal_id="local-user",
        message=message,
        trigger_at=delivered_at - timedelta(minutes=1),
        status=ReminderStatus.DELIVERED,
        created_at=delivered_at - timedelta(minutes=2),
        updated_at=delivered_at,
        delivered_at=delivered_at,
    )


def test_tray_snapshot_orders_scheduled_and_recent_delivered() -> None:
    service = FakeReminderService(
        (
            _scheduled("later", "Later", 20),
            _delivered("old", "Old notification", 30),
            _scheduled("soon", "Soon", 5),
            _delivered("new", "New notification", 2),
        )
    )

    snapshot = build_tray_snapshot(service, recent_limit=1)  # type: ignore[arg-type]

    assert [reminder.id for reminder in snapshot.scheduled] == ["soon", "later"]
    assert [reminder.id for reminder in snapshot.recent_delivered] == ["new"]


def test_tray_snapshot_is_principal_scoped() -> None:
    other = Reminder(
        id="other",
        principal_id="other-user",
        message="Other user's reminder",
        trigger_at=NOW + timedelta(minutes=1),
        status=ReminderStatus.SCHEDULED,
        created_at=NOW,
        updated_at=NOW,
    )
    service = FakeReminderService((_scheduled("mine", "Mine", 5), other))

    snapshot = build_tray_snapshot(service)  # type: ignore[arg-type]

    assert [reminder.id for reminder in snapshot.scheduled] == ["mine"]


def test_tray_snapshot_rejects_negative_recent_limit() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        build_tray_snapshot(FakeReminderService(()), recent_limit=-1)  # type: ignore[arg-type]


def test_tray_reminder_label_contains_message() -> None:
    assert "Soon" in format_tray_reminder(_scheduled("soon", "Soon", 5))


def test_countdown_formats_seconds_and_hours_without_negative_time() -> None:
    timer = Reminder(
        id="timer",
        principal_id="local-user",
        message="Timer",
        trigger_at=NOW + timedelta(seconds=90),
        status=ReminderStatus.SCHEDULED,
        created_at=NOW,
        updated_at=NOW,
        kind=ReminderKind.TIMER,
        duration_seconds=90,
    )

    assert format_timer_countdown(timer, now=NOW) == "01:30 remaining"
    assert format_timer_countdown(timer, now=NOW + timedelta(seconds=1)) == (
        "01:29 remaining"
    )
    assert format_timer_countdown(timer, now=NOW + timedelta(seconds=90)) == "Due"
    assert format_timer_countdown(
        timer, now=NOW - timedelta(seconds=3600)
    ) == "1:01:30 remaining"
    assert ":01:30 " in format_tray_reminder(timer)


def test_countdown_rejects_non_timer() -> None:
    with pytest.raises(ValueError, match="requires a timer"):
        format_timer_countdown(_scheduled("reminder", "Not a timer", 1), now=NOW)
