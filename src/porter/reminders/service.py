from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from porter.core.clock import utc_now
from porter.reminders.errors import (
    ReminderStateError,
    ReminderValidationError,
)
from porter.reminders.models import Reminder, ReminderKind, ReminderStatus
from porter.reminders.repository import ReminderRepository

_DELIVERY_RETRY_DELAYS = (
    timedelta(seconds=5),
    timedelta(seconds=15),
    timedelta(seconds=30),
    timedelta(seconds=60),
    timedelta(seconds=120),
    timedelta(seconds=300),
)


def _default_id_generator() -> str:
    return str(uuid4())


def _clean_required_text(value: str, field: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ReminderValidationError(f"{field} must not be empty")
    return cleaned


def _normalize_aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ReminderValidationError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _delivery_retry_delay(attempt_count: int) -> timedelta:
    index = min(attempt_count, len(_DELIVERY_RETRY_DELAYS)) - 1
    return _DELIVERY_RETRY_DELAYS[index]


class ReminderService:
    """Porter-owned one-shot reminder behavior."""

    def __init__(
        self,
        repository: ReminderRepository,
        *,
        clock: Callable[[], datetime] | None = None,
        id_generator: Callable[[], str] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or utc_now
        self._id_generator = id_generator or _default_id_generator

    def create_reminder(
        self,
        principal_id: str,
        message: str,
        trigger_at: datetime,
    ) -> Reminder:
        now = self._now()
        reminder = Reminder(
            id=self._new_id(),
            principal_id=_clean_required_text(principal_id, "principal id"),
            message=_clean_required_text(message, "reminder message"),
            trigger_at=trigger_at,
            status=ReminderStatus.SCHEDULED,
            created_at=now,
            updated_at=now,
        )
        return self._repository.create_reminder(reminder)

    def create_timer(
        self,
        principal_id: str,
        duration: timedelta,
        *,
        label: str = "Timer",
    ) -> Reminder:
        seconds = duration.total_seconds()
        if not seconds.is_integer() or seconds <= 0 or seconds > 360_000:
            raise ReminderValidationError(
                "timer duration must be 1 to 360000 whole seconds"
            )
        now = self._now()
        timer = Reminder(
            id=self._new_id(),
            principal_id=_clean_required_text(principal_id, "principal id"),
            message=_clean_required_text(label, "timer label"),
            trigger_at=now + timedelta(seconds=int(seconds)),
            status=ReminderStatus.SCHEDULED,
            created_at=now,
            updated_at=now,
            kind=ReminderKind.TIMER,
            duration_seconds=int(seconds),
        )
        return self._repository.create_reminder(timer)

    def restart_timer(self, principal_id: str, timer_id: str) -> Reminder:
        principal_id = _clean_required_text(principal_id, "principal id")
        current = self.get_reminder(principal_id, timer_id)
        if current.kind is not ReminderKind.TIMER:
            raise ReminderValidationError("only a timer can be restarted")
        if current.duration_seconds is None:
            raise ReminderValidationError("timer has no original duration")
        return self.reschedule_reminder(
            principal_id,
            timer_id,
            self._now() + timedelta(seconds=current.duration_seconds),
        )

    def get_reminder(self, principal_id: str, reminder_id: str) -> Reminder:
        return self._repository.get_reminder(
            _clean_required_text(principal_id, "principal id"),
            _clean_required_text(reminder_id, "reminder id"),
        )

    def list_reminders(
        self,
        principal_id: str,
        *,
        status: ReminderStatus | None = None,
    ) -> tuple[Reminder, ...]:
        return self._repository.list_reminders(
            _clean_required_text(principal_id, "principal id"),
            status=status,
        )

    def due_reminders(
        self,
        principal_id: str,
        *,
        as_of: datetime | None = None,
    ) -> tuple[Reminder, ...]:
        return self._repository.list_due_reminders(
            _clean_required_text(principal_id, "principal id"),
            as_of=self._now() if as_of is None else _normalize_aware(as_of, "as_of"),
        )

    def record_delivery_failure(
        self,
        principal_id: str,
        reminder_id: str,
        *,
        claimed_at: datetime,
    ) -> Reminder:
        principal_id = _clean_required_text(principal_id, "principal id")
        claimed_at = _normalize_aware(claimed_at, "delivery claimed_at")
        current = self._repository.get_reminder(
            principal_id,
            _clean_required_text(reminder_id, "reminder id"),
        )
        if current.status is not ReminderStatus.DELIVERING:
            raise ReminderStateError(
                "delivery failure can only be recorded for delivering reminder"
            )
        if current.delivery_claimed_at != claimed_at:
            raise ReminderStateError("delivery claim changed before failure finalization")

        now = self._now()
        attempt_count = current.delivery_attempt_count + 1
        return self._repository.update_reminder(
            principal_id,
            replace(
                current,
                status=ReminderStatus.SCHEDULED,
                updated_at=now,
                delivery_attempt_count=attempt_count,
                next_delivery_attempt_at=(
                    now + _delivery_retry_delay(attempt_count)
                ),
                delivery_claimed_at=None,
            ),
            expected_status=ReminderStatus.DELIVERING,
            expected_claimed_at=claimed_at,
        )

    def edit_reminder(
        self,
        principal_id: str,
        reminder_id: str,
        *,
        message: str,
        trigger_at: datetime,
    ) -> Reminder:
        principal_id = _clean_required_text(principal_id, "principal id")
        current = self._repository.get_reminder(
            principal_id,
            _clean_required_text(reminder_id, "reminder id"),
        )
        if current.status is not ReminderStatus.SCHEDULED:
            raise ReminderStateError("only scheduled reminders can be edited")

        now = self._now()
        if _normalize_aware(trigger_at, "trigger_at") <= now:
            raise ReminderValidationError("edited trigger_at must be in the future")

        return self._repository.update_reminder(
            principal_id,
            replace(
                current,
                message=_clean_required_text(message, "reminder message"),
                trigger_at=trigger_at,
                updated_at=now,
                delivery_attempt_count=0,
                next_delivery_attempt_at=None,
            ),
            expected_status=ReminderStatus.SCHEDULED,
        )

    def reschedule_reminder(
        self,
        principal_id: str,
        reminder_id: str,
        trigger_at: datetime,
    ) -> Reminder:
        principal_id = _clean_required_text(principal_id, "principal id")
        current = self._repository.get_reminder(
            principal_id,
            _clean_required_text(reminder_id, "reminder id"),
        )
        if current.status is ReminderStatus.DELIVERING:
            raise ReminderStateError("delivering reminder cannot be rescheduled")

        now = self._now()
        if _normalize_aware(trigger_at, "trigger_at") <= now:
            raise ReminderValidationError("rescheduled trigger_at must be in the future")

        return self._repository.update_reminder(
            principal_id,
            replace(
                current,
                trigger_at=trigger_at,
                status=ReminderStatus.SCHEDULED,
                updated_at=now,
                delivered_at=None,
                cancelled_at=None,
                delivery_attempt_count=0,
                next_delivery_attempt_at=None,
                delivery_claimed_at=None,
            ),
            expected_status=current.status,
        )

    def snooze_reminder(
        self,
        principal_id: str,
        reminder_id: str,
        *,
        delay: timedelta = timedelta(minutes=10),
    ) -> Reminder:
        if delay <= timedelta(0):
            raise ReminderValidationError("snooze delay must be positive")

        principal_id = _clean_required_text(principal_id, "principal id")
        current = self._repository.get_reminder(
            principal_id,
            _clean_required_text(reminder_id, "reminder id"),
        )
        if current.status is ReminderStatus.DELIVERING:
            raise ReminderStateError("delivering reminder cannot be snoozed")

        now = self._now()
        existing_trigger = _normalize_aware(current.trigger_at, "trigger_at")
        snooze_base = max(now, existing_trigger)
        trigger_at = (snooze_base + delay).astimezone(current.trigger_at.tzinfo)
        return self._repository.update_reminder(
            principal_id,
            replace(
                current,
                trigger_at=trigger_at,
                status=ReminderStatus.SCHEDULED,
                updated_at=now,
                delivered_at=None,
                cancelled_at=None,
                delivery_attempt_count=0,
                next_delivery_attempt_at=None,
                delivery_claimed_at=None,
            ),
            expected_status=current.status,
        )

    def cancel_reminder(
        self,
        principal_id: str,
        reminder_id: str,
    ) -> Reminder:
        principal_id = _clean_required_text(principal_id, "principal id")
        current = self._repository.get_reminder(
            principal_id,
            _clean_required_text(reminder_id, "reminder id"),
        )
        if current.status is ReminderStatus.CANCELLED:
            return current
        if current.status is ReminderStatus.DELIVERED:
            raise ReminderStateError("delivered reminder cannot be cancelled")
        if current.status is ReminderStatus.DELIVERING:
            raise ReminderStateError("delivering reminder cannot be cancelled")

        now = self._now()
        return self._repository.update_reminder(
            principal_id,
            replace(
                current,
                status=ReminderStatus.CANCELLED,
                updated_at=now,
                cancelled_at=now,
                delivery_attempt_count=0,
                next_delivery_attempt_at=None,
                delivery_claimed_at=None,
            ),
            expected_status=ReminderStatus.SCHEDULED,
        )

    def mark_delivered(
        self,
        principal_id: str,
        reminder_id: str,
        *,
        claimed_at: datetime,
    ) -> Reminder:
        principal_id = _clean_required_text(principal_id, "principal id")
        claimed_at = _normalize_aware(claimed_at, "delivery claimed_at")
        current = self._repository.get_reminder(
            principal_id,
            _clean_required_text(reminder_id, "reminder id"),
        )
        if current.status is ReminderStatus.DELIVERED:
            return current
        if current.status is not ReminderStatus.DELIVERING:
            raise ReminderStateError(
                "only delivering reminder can be marked delivered"
            )
        if current.delivery_claimed_at != claimed_at:
            raise ReminderStateError("delivery claim changed before success finalization")

        now = self._now()
        return self._repository.update_reminder(
            principal_id,
            replace(
                current,
                status=ReminderStatus.DELIVERED,
                updated_at=now,
                delivered_at=now,
                delivery_attempt_count=0,
                next_delivery_attempt_at=None,
                delivery_claimed_at=None,
            ),
            expected_status=ReminderStatus.DELIVERING,
            expected_claimed_at=claimed_at,
        )

    def delete_terminal_reminder(
        self,
        principal_id: str,
        reminder_id: str,
    ) -> None:
        principal_id = _clean_required_text(principal_id, "principal id")
        reminder_id = _clean_required_text(reminder_id, "reminder id")
        current = self._repository.get_reminder(principal_id, reminder_id)
        if current.status not in {
            ReminderStatus.DELIVERED,
            ReminderStatus.CANCELLED,
        }:
            raise ReminderStateError(
                "only delivered or cancelled reminder can be cleared"
            )
        self._repository.delete_reminder(
            principal_id,
            reminder_id,
            expected_status=current.status,
        )

    def clear_reminder_history(self, principal_id: str) -> int:
        return self._repository.delete_terminal_reminders(
            _clean_required_text(principal_id, "principal id")
        )

    def _now(self) -> datetime:
        return _normalize_aware(self._clock(), "reminder service clock")

    def _new_id(self) -> str:
        return _clean_required_text(
            self._id_generator(),
            "generated reminder id",
        )
