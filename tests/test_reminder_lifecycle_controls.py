from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import count
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from porter.reminders import (
    Reminder,
    ReminderNotFoundError,
    ReminderService,
    ReminderStateError,
    ReminderStatus,
    ReminderValidationError,
    SqliteReminderRepository,
)
from porter.storage.database import Database
from porter.storage.migrations import MigrationRunner

NOW = datetime(2026, 8, 15, 20, tzinfo=UTC)
TORONTO = ZoneInfo("America/Toronto")


def _build_service(
    tmp_path: Path,
    *,
    clock=None,
) -> tuple[SqliteReminderRepository, ReminderService]:
    database = Database(tmp_path / "porter.db")
    MigrationRunner(database).apply_all()
    repository = SqliteReminderRepository(database)
    identifiers = count(1)
    service = ReminderService(
        repository,
        clock=clock or (lambda: NOW),
        id_generator=lambda: f"reminder-{next(identifiers)}",
    )
    return repository, service


def _claim(
    repository: SqliteReminderRepository,
    reminder: Reminder,
    *,
    claimed_at: datetime = NOW,
) -> Reminder:
    claimed = repository.claim_due_reminder(
        reminder.principal_id,
        reminder.id,
        claimed_at=claimed_at,
    )
    assert claimed is not None
    assert claimed.delivery_claimed_at is not None
    return claimed


def test_edit_scheduled_reminder_updates_message_and_trigger(tmp_path: Path) -> None:
    repository, service = _build_service(tmp_path)
    reminder = service.create_reminder(
        "alice",
        "Original message",
        NOW,
    )
    claimed = _claim(repository, reminder)
    service.record_delivery_failure(
        "alice",
        reminder.id,
        claimed_at=claimed.delivery_claimed_at,
    )
    trigger = datetime(2026, 8, 15, 18, 30, tzinfo=TORONTO)

    edited = service.edit_reminder(
        "alice",
        reminder.id,
        message=" Edited message ",
        trigger_at=trigger,
    )

    assert edited.message == "Edited message"
    assert edited.trigger_at == trigger
    assert edited.status is ReminderStatus.SCHEDULED
    assert edited.delivery_attempt_count == 0
    assert edited.next_delivery_attempt_at is None


def test_edit_reminder_rejects_terminal_empty_and_nonfuture_values(tmp_path: Path) -> None:
    repository, service = _build_service(tmp_path)
    scheduled = service.create_reminder(
        "alice",
        "Scheduled",
        NOW + timedelta(hours=1),
    )
    delivered = service.create_reminder("alice", "Delivered", NOW)
    claimed = _claim(repository, delivered)
    service.mark_delivered(
        "alice",
        delivered.id,
        claimed_at=claimed.delivery_claimed_at,
    )

    with pytest.raises(ReminderStateError, match="only scheduled reminders"):
        service.edit_reminder(
            "alice",
            delivered.id,
            message="Again",
            trigger_at=NOW + timedelta(hours=1),
        )

    with pytest.raises(ReminderValidationError, match="must not be empty"):
        service.edit_reminder(
            "alice",
            scheduled.id,
            message="   ",
            trigger_at=NOW + timedelta(hours=1),
        )

    with pytest.raises(ReminderValidationError, match="must be in the future"):
        service.edit_reminder(
            "alice",
            scheduled.id,
            message="Still scheduled",
            trigger_at=NOW,
        )


def test_reschedule_reactivates_delivered_reminder(tmp_path: Path) -> None:
    delivered_at = NOW + timedelta(minutes=1)
    rescheduled_at = NOW + timedelta(minutes=2)
    times = iter((NOW, delivered_at, rescheduled_at))
    repository, service = _build_service(tmp_path, clock=lambda: next(times))
    reminder = service.create_reminder("alice", "Call Mom", NOW)
    claimed = _claim(repository, reminder)
    delivered = service.mark_delivered(
        "alice",
        reminder.id,
        claimed_at=claimed.delivery_claimed_at,
    )
    trigger = datetime(2026, 8, 15, 18, tzinfo=TORONTO)

    rescheduled = service.reschedule_reminder("alice", delivered.id, trigger)

    assert rescheduled.id == reminder.id
    assert rescheduled.message == "Call Mom"
    assert rescheduled.trigger_at == trigger
    assert rescheduled.status is ReminderStatus.SCHEDULED
    assert rescheduled.updated_at == rescheduled_at
    assert rescheduled.delivered_at is None
    assert rescheduled.cancelled_at is None
    assert rescheduled.delivery_attempt_count == 0
    assert rescheduled.next_delivery_attempt_at is None
    assert rescheduled.delivery_claimed_at is None


def test_snooze_scheduled_reminder_clears_retry_state(tmp_path: Path) -> None:
    failure_at = NOW + timedelta(seconds=1)
    snoozed_at = NOW + timedelta(seconds=2)
    times = iter((NOW, failure_at, snoozed_at))
    repository, service = _build_service(tmp_path, clock=lambda: next(times))
    reminder = service.create_reminder("alice", "Stretch", NOW)
    claimed = _claim(repository, reminder)
    failed = service.record_delivery_failure(
        "alice",
        reminder.id,
        claimed_at=claimed.delivery_claimed_at,
    )

    snoozed = service.snooze_reminder("alice", failed.id)

    assert failed.delivery_attempt_count == 1
    assert snoozed.status is ReminderStatus.SCHEDULED
    assert snoozed.trigger_at == snoozed_at + timedelta(minutes=10)
    assert snoozed.delivery_attempt_count == 0
    assert snoozed.next_delivery_attempt_at is None


def test_snooze_future_reminder_delays_existing_trigger(tmp_path: Path) -> None:
    _, service = _build_service(tmp_path)
    original_trigger = NOW + timedelta(hours=4)
    reminder = service.create_reminder("alice", "Tomorrow prep", original_trigger)

    snoozed = service.snooze_reminder("alice", reminder.id)

    assert snoozed.trigger_at == original_trigger + timedelta(minutes=10)


def test_snooze_can_remind_again_after_delivery(tmp_path: Path) -> None:
    delivered_at = NOW + timedelta(minutes=1)
    snoozed_at = NOW + timedelta(minutes=2)
    times = iter((NOW, delivered_at, snoozed_at))
    repository, service = _build_service(tmp_path, clock=lambda: next(times))
    reminder = service.create_reminder("alice", "Drink water", NOW)
    claimed = _claim(repository, reminder)
    service.mark_delivered(
        "alice",
        reminder.id,
        claimed_at=claimed.delivery_claimed_at,
    )

    snoozed = service.snooze_reminder(
        "alice",
        reminder.id,
        delay=timedelta(minutes=30),
    )

    assert snoozed.status is ReminderStatus.SCHEDULED
    assert snoozed.trigger_at == snoozed_at + timedelta(minutes=30)
    assert snoozed.delivered_at is None


@pytest.mark.parametrize(
    "trigger_at",
    [
        datetime(2026, 8, 15, 20),
        NOW,
        NOW - timedelta(seconds=1),
    ],
)
def test_reschedule_rejects_invalid_trigger(
    tmp_path: Path,
    trigger_at: datetime,
) -> None:
    _, service = _build_service(tmp_path)
    reminder = service.create_reminder("alice", "Later", NOW)

    with pytest.raises(ReminderValidationError):
        service.reschedule_reminder("alice", reminder.id, trigger_at)


def test_delete_terminal_reminder_refuses_scheduled_then_deletes_cancelled(
    tmp_path: Path,
) -> None:
    _, service = _build_service(tmp_path)
    reminder = service.create_reminder("alice", "Clear me", NOW)

    with pytest.raises(ReminderStateError, match="only delivered or cancelled"):
        service.delete_terminal_reminder("alice", reminder.id)

    service.cancel_reminder("alice", reminder.id)
    service.delete_terminal_reminder("alice", reminder.id)

    with pytest.raises(ReminderNotFoundError):
        service.get_reminder("alice", reminder.id)


def test_clear_history_preserves_scheduled_and_other_principals(tmp_path: Path) -> None:
    repository, service = _build_service(tmp_path)
    scheduled = service.create_reminder("alice", "Keep scheduled", NOW)
    delivered = service.create_reminder("alice", "Clear delivered", NOW)
    cancelled = service.create_reminder("alice", "Clear cancelled", NOW)
    bob_delivered = service.create_reminder("bob", "Bob history", NOW)
    alice_claim = _claim(repository, delivered)
    service.mark_delivered(
        "alice",
        delivered.id,
        claimed_at=alice_claim.delivery_claimed_at,
    )
    service.cancel_reminder("alice", cancelled.id)
    bob_claim = _claim(repository, bob_delivered)
    service.mark_delivered(
        "bob",
        bob_delivered.id,
        claimed_at=bob_claim.delivery_claimed_at,
    )

    deleted = service.clear_reminder_history("alice")

    assert deleted == 2
    assert service.list_reminders("alice") == (scheduled,)
    assert service.list_reminders("bob") == (
        service.get_reminder("bob", bob_delivered.id),
    )
    assert service.clear_reminder_history("alice") == 0
