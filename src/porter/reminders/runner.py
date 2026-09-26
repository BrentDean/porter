from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from porter.core.clock import utc_now
from porter.reminders.delivery import ReminderDelivery
from porter.reminders.errors import (
    ReminderDeliveryError,
    ReminderValidationError,
)
from porter.reminders.repository import ReminderRepository
from porter.reminders.service import ReminderService

_DELIVERY_CLAIM_TIMEOUT = timedelta(minutes=5)


class ReminderRunFailureStage(StrEnum):
    DELIVERY = "delivery"


@dataclass(frozen=True, slots=True)
class ReminderRunFailure:
    reminder_id: str
    principal_id: str
    stage: ReminderRunFailureStage
    error_type: str
    error_message: str


@dataclass(frozen=True, slots=True)
class ReminderRunResult:
    attempted_reminder_ids: tuple[str, ...]
    delivered_reminder_ids: tuple[str, ...]
    failures: tuple[ReminderRunFailure, ...]

    @property
    def attempted(self) -> int:
        return len(self.attempted_reminder_ids)

    @property
    def delivered(self) -> int:
        return len(self.delivered_reminder_ids)

    @property
    def failed(self) -> int:
        return len(self.failures)


class ReminderRunner:
    """Single-pass executor for delivery-ready one-shot reminders."""

    def __init__(
        self,
        repository: ReminderRepository,
        reminder_service: ReminderService,
        delivery: ReminderDelivery,
        *,
        clock: Callable[[], datetime] | None = None,
        claim_timeout: timedelta = _DELIVERY_CLAIM_TIMEOUT,
    ) -> None:
        if claim_timeout <= timedelta(0):
            raise ReminderValidationError("delivery claim timeout must be positive")
        self._repository = repository
        self._reminder_service = reminder_service
        self._delivery = delivery
        self._clock = clock or utc_now
        self._claim_timeout = claim_timeout

    async def run_once(self) -> ReminderRunResult:
        as_of = self._now()
        self._repository.recover_stale_delivery_claims(
            stale_before=as_of - self._claim_timeout,
            retry_at=as_of,
        )
        due = self._repository.list_all_due_reminders(as_of=as_of)
        attempted: list[str] = []
        delivered: list[str] = []
        failures: list[ReminderRunFailure] = []

        for candidate in due:
            claimed = self._repository.claim_due_reminder(
                candidate.principal_id,
                candidate.id,
                claimed_at=as_of,
            )
            if claimed is None:
                continue
            claim_time = claimed.delivery_claimed_at
            if claim_time is None:
                raise ReminderValidationError(
                    "claimed reminder is missing delivery_claimed_at"
                )

            attempted.append(claimed.id)

            try:
                await self._delivery.deliver(claimed)
            except ReminderDeliveryError as exc:
                self._reminder_service.record_delivery_failure(
                    claimed.principal_id,
                    claimed.id,
                    claimed_at=claim_time,
                )
                failures.append(
                    self._failure(
                        reminder_id=claimed.id,
                        principal_id=claimed.principal_id,
                        exc=exc,
                    )
                )
                continue

            self._reminder_service.mark_delivered(
                claimed.principal_id,
                claimed.id,
                claimed_at=claim_time,
            )
            delivered.append(claimed.id)

        return ReminderRunResult(
            attempted_reminder_ids=tuple(attempted),
            delivered_reminder_ids=tuple(delivered),
            failures=tuple(failures),
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ReminderValidationError(
                "reminder runner clock must be timezone-aware"
            )
        return value.astimezone(UTC)

    @staticmethod
    def _failure(
        *,
        reminder_id: str,
        principal_id: str,
        exc: ReminderDeliveryError,
    ) -> ReminderRunFailure:
        return ReminderRunFailure(
            reminder_id=reminder_id,
            principal_id=principal_id,
            stage=ReminderRunFailureStage.DELIVERY,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
