from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from porter.reminders.errors import ReminderValidationError


class ReminderKind(StrEnum):
    REMINDER = "reminder"
    TIMER = "timer"


class ReminderStatus(StrEnum):
    SCHEDULED = "scheduled"
    DELIVERING = "delivering"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


def _require_text(value: str, field: str) -> None:
    if not value.strip():
        raise ReminderValidationError(f"{field} must not be empty")


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ReminderValidationError(f"{field} must be timezone-aware")


def _require_trigger_timezone(value: datetime) -> None:
    _require_aware(value, "trigger_at")
    zone_key = getattr(value.tzinfo, "key", None)
    if zone_key:
        return
    if value.utcoffset() == timedelta(0):
        return
    raise ReminderValidationError(
        "trigger_at must use an IANA timezone or UTC"
    )


@dataclass(frozen=True, slots=True)
class Reminder:
    id: str
    principal_id: str
    message: str
    trigger_at: datetime
    status: ReminderStatus
    created_at: datetime
    updated_at: datetime
    delivered_at: datetime | None = None
    cancelled_at: datetime | None = None
    delivery_attempt_count: int = 0
    next_delivery_attempt_at: datetime | None = None
    delivery_claimed_at: datetime | None = None
    kind: ReminderKind = ReminderKind.REMINDER
    duration_seconds: int | None = None

    def __post_init__(self) -> None:
        _require_text(self.id, "reminder id")
        _require_text(self.principal_id, "principal id")
        _require_text(self.message, "reminder message")
        _require_trigger_timezone(self.trigger_at)

        if not isinstance(self.status, ReminderStatus):
            raise ReminderValidationError(
                "status must be a ReminderStatus value"
            )
        if not isinstance(self.kind, ReminderKind):
            raise ReminderValidationError("kind must be a ReminderKind value")
        if self.kind is ReminderKind.TIMER:
            if (
                not isinstance(self.duration_seconds, int)
                or isinstance(self.duration_seconds, bool)
                or self.duration_seconds <= 0
            ):
                raise ReminderValidationError(
                    "timer duration_seconds must be a positive integer"
                )
        elif self.duration_seconds is not None:
            raise ReminderValidationError(
                "reminder cannot have timer duration_seconds"
            )

        _require_aware(self.created_at, "created_at")
        _require_aware(self.updated_at, "updated_at")
        if self.delivered_at is not None:
            _require_aware(self.delivered_at, "delivered_at")
        if self.cancelled_at is not None:
            _require_aware(self.cancelled_at, "cancelled_at")
        if self.next_delivery_attempt_at is not None:
            _require_aware(
                self.next_delivery_attempt_at,
                "next_delivery_attempt_at",
            )
        if self.delivery_claimed_at is not None:
            _require_aware(self.delivery_claimed_at, "delivery_claimed_at")

        if (
            not isinstance(self.delivery_attempt_count, int)
            or isinstance(self.delivery_attempt_count, bool)
            or self.delivery_attempt_count < 0
        ):
            raise ReminderValidationError(
                "delivery_attempt_count must be a non-negative integer"
            )

        if self.status is ReminderStatus.SCHEDULED:
            self._validate_scheduled()
        elif self.status is ReminderStatus.DELIVERING:
            self._validate_delivering()
        elif self.status is ReminderStatus.DELIVERED:
            self._validate_delivered()
        elif self.status is ReminderStatus.CANCELLED:
            self._validate_cancelled()

    def _validate_scheduled(self) -> None:
        if (
            self.delivered_at is not None
            or self.cancelled_at is not None
            or self.delivery_claimed_at is not None
        ):
            raise ReminderValidationError(
                "scheduled reminder cannot have terminal or claim timestamps"
            )

        if self.delivery_attempt_count == 0:
            if self.next_delivery_attempt_at is not None:
                raise ReminderValidationError(
                    "next_delivery_attempt_at requires a delivery attempt"
                )
        elif self.next_delivery_attempt_at is None:
            raise ReminderValidationError(
                "failed delivery attempt requires next_delivery_attempt_at"
            )

    def _validate_delivering(self) -> None:
        if self.delivery_claimed_at is None:
            raise ReminderValidationError(
                "delivering reminder requires delivery_claimed_at"
            )
        if self.delivered_at is not None or self.cancelled_at is not None:
            raise ReminderValidationError(
                "delivering reminder cannot have terminal timestamps"
            )
        if self.next_delivery_attempt_at is not None:
            raise ReminderValidationError(
                "delivering reminder cannot retain next_delivery_attempt_at"
            )

    def _validate_delivered(self) -> None:
        if (
            self.delivered_at is None
            or self.cancelled_at is not None
            or self.delivery_claimed_at is not None
        ):
            raise ReminderValidationError(
                "delivered reminder requires delivered_at only"
            )
        self._validate_terminal_retry_state()

    def _validate_cancelled(self) -> None:
        if (
            self.cancelled_at is None
            or self.delivered_at is not None
            or self.delivery_claimed_at is not None
        ):
            raise ReminderValidationError(
                "cancelled reminder requires cancelled_at only"
            )
        self._validate_terminal_retry_state()

    def _validate_terminal_retry_state(self) -> None:
        if (
            self.delivery_attempt_count != 0
            or self.next_delivery_attempt_at is not None
        ):
            raise ReminderValidationError(
                "terminal reminder cannot retain delivery retry state"
            )
