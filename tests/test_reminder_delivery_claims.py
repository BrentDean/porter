from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import count
from pathlib import Path

import pytest

from porter.reminders import (
    ReminderService,
    ReminderStateError,
    ReminderStatus,
    SqliteReminderRepository,
)
from porter.storage.database import Database
from porter.storage.migrations import MigrationRunner

NOW = datetime(2026, 8, 15, 20, tzinfo=UTC)


def _build(
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


def test_due_reminder_can_only_be_claimed_once(tmp_path: Path) -> None:
    repository, service = _build(tmp_path)
    reminder = service.create_reminder(
        "alice",
        "Only once",
        NOW - timedelta(minutes=1),
    )

    first = repository.claim_due_reminder(
        "alice",
        reminder.id,
        claimed_at=NOW,
    )
    second = repository.claim_due_reminder(
        "alice",
        reminder.id,
        claimed_at=NOW,
    )

    assert first is not None
    assert first.status is ReminderStatus.DELIVERING
    assert first.delivery_claimed_at == NOW
    assert second is None


def test_edit_after_due_query_prevents_stale_delivery_claim(tmp_path: Path) -> None:
    repository, service = _build(tmp_path)
    reminder = service.create_reminder(
        "alice",
        "Move me later",
        NOW - timedelta(minutes=1),
    )
    candidates = repository.list_all_due_reminders(as_of=NOW)
    assert candidates == (reminder,)

    edited = service.edit_reminder(
        "alice",
        reminder.id,
        message="Moved later",
        trigger_at=NOW + timedelta(hours=1),
    )
    claimed = repository.claim_due_reminder(
        "alice",
        reminder.id,
        claimed_at=NOW,
    )

    assert edited.status is ReminderStatus.SCHEDULED
    assert claimed is None


def test_cancel_after_due_query_prevents_stale_delivery_claim(tmp_path: Path) -> None:
    repository, service = _build(tmp_path)
    reminder = service.create_reminder(
        "alice",
        "Cancel before claim",
        NOW - timedelta(minutes=1),
    )
    candidates = repository.list_all_due_reminders(as_of=NOW)
    assert candidates == (reminder,)

    cancelled = service.cancel_reminder("alice", reminder.id)
    claimed = repository.claim_due_reminder(
        "alice",
        reminder.id,
        claimed_at=NOW,
    )

    assert cancelled.status is ReminderStatus.CANCELLED
    assert claimed is None


def test_active_delivery_claim_blocks_interactive_mutations(tmp_path: Path) -> None:
    repository, service = _build(tmp_path)
    reminder = service.create_reminder(
        "alice",
        "In flight",
        NOW - timedelta(minutes=1),
    )
    claimed = repository.claim_due_reminder(
        "alice",
        reminder.id,
        claimed_at=NOW,
    )
    assert claimed is not None

    with pytest.raises(ReminderStateError, match="only scheduled reminders"):
        service.edit_reminder(
            "alice",
            reminder.id,
            message="Edited",
            trigger_at=NOW + timedelta(hours=1),
        )
    with pytest.raises(ReminderStateError, match="cannot be snoozed"):
        service.snooze_reminder("alice", reminder.id)
    with pytest.raises(ReminderStateError, match="cannot be cancelled"):
        service.cancel_reminder("alice", reminder.id)
    with pytest.raises(ReminderStateError, match="cannot be rescheduled"):
        service.reschedule_reminder(
            "alice",
            reminder.id,
            NOW + timedelta(hours=1),
        )


def test_stale_delivery_claim_is_recovered_without_stealing_live_claim(
    tmp_path: Path,
) -> None:
    repository, service = _build(tmp_path)
    reminder = service.create_reminder(
        "alice",
        "Recover me",
        NOW - timedelta(minutes=1),
    )
    claimed = repository.claim_due_reminder(
        "alice",
        reminder.id,
        claimed_at=NOW,
    )
    assert claimed is not None

    recovered = repository.recover_stale_delivery_claims(
        stale_before=NOW - timedelta(seconds=1),
        retry_at=NOW,
    )
    assert recovered == 0
    assert service.get_reminder("alice", reminder.id).status is ReminderStatus.DELIVERING

    later = NOW + timedelta(minutes=5)
    recovered = repository.recover_stale_delivery_claims(
        stale_before=NOW,
        retry_at=later,
    )
    loaded = service.get_reminder("alice", reminder.id)

    assert recovered == 1
    assert loaded.status is ReminderStatus.SCHEDULED
    assert loaded.delivery_claimed_at is None
    assert loaded.next_delivery_attempt_at is None
    assert repository.list_all_due_reminders(as_of=later) == (loaded,)


@pytest.mark.resilience
def test_stale_claim_recovery_preserves_prior_failure_count(tmp_path: Path) -> None:
    repository, service = _build(tmp_path)
    reminder = service.create_reminder("alice", "Retry and recover", NOW)
    claimed = repository.claim_due_reminder(
        "alice",
        reminder.id,
        claimed_at=NOW,
    )
    assert claimed is not None
    assert claimed.delivery_claimed_at is not None
    failed = service.record_delivery_failure(
        "alice",
        reminder.id,
        claimed_at=claimed.delivery_claimed_at,
    )
    assert failed.delivery_attempt_count == 1

    retry_at = failed.next_delivery_attempt_at
    assert retry_at is not None
    claimed_again = repository.claim_due_reminder(
        "alice",
        reminder.id,
        claimed_at=retry_at,
    )
    assert claimed_again is not None
    assert claimed_again.delivery_attempt_count == 1
    assert claimed_again.next_delivery_attempt_at is None

    recovered_at = retry_at + timedelta(minutes=5)
    recovered = repository.recover_stale_delivery_claims(
        stale_before=retry_at,
        retry_at=recovered_at,
    )
    loaded = service.get_reminder("alice", reminder.id)

    assert recovered == 1
    assert loaded.status is ReminderStatus.SCHEDULED
    assert loaded.delivery_attempt_count == 1
    assert loaded.next_delivery_attempt_at == recovered_at


def test_expired_worker_cannot_finalize_newer_delivery_claim(tmp_path: Path) -> None:
    repository, service = _build(tmp_path)
    reminder = service.create_reminder(
        "alice",
        "Claim ownership",
        NOW - timedelta(minutes=1),
    )
    first_claim = repository.claim_due_reminder(
        "alice",
        reminder.id,
        claimed_at=NOW,
    )
    assert first_claim is not None
    assert first_claim.delivery_claimed_at == NOW

    reclaimed_at = NOW + timedelta(minutes=5)
    assert repository.recover_stale_delivery_claims(
        stale_before=NOW,
        retry_at=reclaimed_at,
    ) == 1
    second_claim = repository.claim_due_reminder(
        "alice",
        reminder.id,
        claimed_at=reclaimed_at,
    )
    assert second_claim is not None
    assert second_claim.delivery_claimed_at == reclaimed_at

    with pytest.raises(ReminderStateError, match="claim changed"):
        service.mark_delivered(
            "alice",
            reminder.id,
            claimed_at=NOW,
        )

    loaded = service.get_reminder("alice", reminder.id)
    assert loaded.status is ReminderStatus.DELIVERING
    assert loaded.delivery_claimed_at == reclaimed_at
