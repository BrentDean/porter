from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import ceil

from porter.core.clock import system_timezone
from porter.reminders import Reminder, ReminderKind, ReminderService, ReminderStatus


@dataclass(frozen=True, slots=True)
class TrayReminderSnapshot:
    scheduled: tuple[Reminder, ...]
    recent_delivered: tuple[Reminder, ...]


def build_tray_snapshot(
    reminder_service: ReminderService,
    *,
    principal_id: str = "local-user",
    recent_limit: int = 5,
) -> TrayReminderSnapshot:
    if recent_limit < 0:
        raise ValueError("recent_limit must not be negative")

    scheduled = tuple(
        sorted(
            reminder_service.list_reminders(
                principal_id,
                status=ReminderStatus.SCHEDULED,
            ),
            key=lambda reminder: (reminder.trigger_at, reminder.created_at, reminder.id),
        )
    )
    delivered = tuple(
        sorted(
            reminder_service.list_reminders(
                principal_id,
                status=ReminderStatus.DELIVERED,
            ),
            key=lambda reminder: (
                reminder.delivered_at or reminder.updated_at,
                reminder.id,
            ),
            reverse=True,
        )[:recent_limit]
    )

    return TrayReminderSnapshot(
        scheduled=scheduled,
        recent_delivered=delivered,
    )


def format_tray_reminder(reminder: Reminder) -> str:
    local_trigger = reminder.trigger_at.astimezone(system_timezone())
    timestamp_format = (
        "%a %b %d, %I:%M:%S %p"
        if reminder.kind is ReminderKind.TIMER
        else "%a %b %d, %I:%M %p"
    )
    timestamp = local_trigger.strftime(timestamp_format).replace(" 0", " ")
    return f"{timestamp} — {reminder.message}"


def format_timer_countdown(
    timer: Reminder,
    *,
    now: datetime | None = None,
) -> str:
    if timer.kind is not ReminderKind.TIMER:
        raise ValueError("countdown requires a timer")
    reference = datetime.now(UTC) if now is None else now.astimezone(UTC)
    remaining = max(
        0,
        ceil((timer.trigger_at.astimezone(UTC) - reference).total_seconds()),
    )
    hours, remainder = divmod(remaining, 3600)
    minutes, seconds = divmod(remainder, 60)
    countdown = (
        f"{hours}:{minutes:02}:{seconds:02}"
        if hours
        else f"{minutes:02}:{seconds:02}"
    )
    return f"{countdown} remaining" if remaining else "Due"
