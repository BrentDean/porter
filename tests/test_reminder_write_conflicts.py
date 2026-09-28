from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
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


def _build(tmp_path: Path) -> tuple[SqliteReminderRepository, ReminderService]:
    database = Database(tmp_path / "porter.db")
    MigrationRunner(database).apply_all()
    repository = SqliteReminderRepository(database)
    service = ReminderService(
        repository,
        clock=lambda: NOW,
        id_generator=lambda: "reminder-1",
    )
    return repository, service


def test_stale_scheduled_write_cannot_overwrite_delivery_claim(tmp_path: Path) -> None:
    repository, service = _build(tmp_path)
    reminder = service.create_reminder(
        "alice",
        "Original",
        NOW - timedelta(minutes=1),
    )
    stale = service.get_reminder("alice", reminder.id)

    claimed = repository.claim_due_reminder(
        "alice",
        reminder.id,
        claimed_at=NOW,
    )
    assert claimed is not None

    with pytest.raises(ReminderStateError, match="changed concurrently"):
        repository.update_reminder(
            "alice",
            replace(
                stale,
                message="Stale edit",
                trigger_at=NOW + timedelta(hours=1),
            ),
            expected_status=ReminderStatus.SCHEDULED,
        )

    loaded = service.get_reminder("alice", reminder.id)
    assert loaded.status is ReminderStatus.DELIVERING
    assert loaded.message == "Original"
    assert loaded.delivery_claimed_at == NOW


def test_stale_terminal_delete_cannot_delete_reactivated_reminder(tmp_path: Path) -> None:
    repository, service = _build(tmp_path)
    reminder = service.create_reminder("alice", "Again later", NOW)
    claimed = repository.claim_due_reminder(
        "alice",
        reminder.id,
        claimed_at=NOW,
    )
    assert claimed is not None
    assert claimed.delivery_claimed_at is not None
    delivered = service.mark_delivered(
        "alice",
        reminder.id,
        claimed_at=claimed.delivery_claimed_at,
    )

    service.reschedule_reminder(
        "alice",
        reminder.id,
        NOW + timedelta(hours=1),
    )

    with pytest.raises(ReminderStateError, match="changed concurrently"):
        repository.delete_reminder(
            "alice",
            reminder.id,
            expected_status=delivered.status,
        )

    loaded = service.get_reminder("alice", reminder.id)
    assert loaded.status is ReminderStatus.SCHEDULED
