from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from porter.reminders import (
    Reminder,
    ReminderRunner,
    ReminderService,
    ReminderStatus,
    SqliteReminderRepository,
)
from porter.storage.database import Database
from porter.storage.migrations import MigrationRunner

NOW = datetime(2026, 8, 15, 20, tzinfo=UTC)


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class RecordingDelivery:
    def __init__(self) -> None:
        self.reminders: list[Reminder] = []

    async def deliver(self, reminder: Reminder) -> None:
        self.reminders.append(reminder)


def _build(
    tmp_path: Path,
    clock: MutableClock,
) -> tuple[SqliteReminderRepository, ReminderService]:
    database = Database(tmp_path / "porter.db")
    MigrationRunner(database).apply_all()
    repository = SqliteReminderRepository(database)
    service = ReminderService(
        repository,
        clock=clock,
        id_generator=lambda: "reminder-1",
    )
    return repository, service


@pytest.mark.asyncio
async def test_runner_recovers_expired_claim_and_delivers_it(tmp_path: Path) -> None:
    clock = MutableClock(NOW)
    repository, service = _build(tmp_path, clock)
    reminder = service.create_reminder(
        "alice",
        "Interrupted delivery",
        NOW - timedelta(minutes=10),
    )
    claimed = repository.claim_due_reminder(
        "alice",
        reminder.id,
        claimed_at=NOW,
    )
    assert claimed is not None

    delivery = RecordingDelivery()
    recovered_at = NOW + timedelta(minutes=5)
    clock.value = recovered_at
    runner = ReminderRunner(
        repository,
        service,
        delivery,
        clock=clock,
        claim_timeout=timedelta(minutes=5),
    )

    result = await runner.run_once()

    assert result.delivered_reminder_ids == (reminder.id,)
    assert [item.id for item in delivery.reminders] == [reminder.id]
    loaded = service.get_reminder("alice", reminder.id)
    assert loaded.status is ReminderStatus.DELIVERED
    assert loaded.delivered_at == recovered_at
    assert loaded.delivery_claimed_at is None


@pytest.mark.asyncio
async def test_runner_does_not_steal_unexpired_claim(tmp_path: Path) -> None:
    clock = MutableClock(NOW)
    repository, service = _build(tmp_path, clock)
    reminder = service.create_reminder(
        "alice",
        "Still in flight",
        NOW - timedelta(minutes=10),
    )
    claimed = repository.claim_due_reminder(
        "alice",
        reminder.id,
        claimed_at=NOW,
    )
    assert claimed is not None

    delivery = RecordingDelivery()
    clock.value = NOW + timedelta(minutes=4, seconds=59)
    runner = ReminderRunner(
        repository,
        service,
        delivery,
        clock=clock,
        claim_timeout=timedelta(minutes=5),
    )

    result = await runner.run_once()

    assert result.attempted == 0
    assert delivery.reminders == []
    loaded = service.get_reminder("alice", reminder.id)
    assert loaded.status is ReminderStatus.DELIVERING
    assert loaded.delivery_claimed_at == NOW
