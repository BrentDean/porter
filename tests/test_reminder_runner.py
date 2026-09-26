from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import count
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from porter.reminders import (
    Reminder,
    ReminderDeliveryError,
    ReminderRunFailureStage,
    ReminderRunner,
    ReminderService,
    ReminderStatus,
    ReminderValidationError,
    SqliteReminderRepository,
)
from porter.storage.database import Database
from porter.storage.migrations import MigrationRunner

NOW = datetime(2026, 8, 15, 16, tzinfo=UTC)
TORONTO = ZoneInfo("America/Toronto")


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class RecordingDelivery:
    def __init__(self, *, fail_ids: frozenset[str] | None = None) -> None:
        self.fail_ids = fail_ids or frozenset()
        self.reminders: list[Reminder] = []

    async def deliver(self, reminder: Reminder) -> None:
        self.reminders.append(reminder)
        if reminder.id in self.fail_ids:
            raise ReminderDeliveryError(
                f"delivery endpoint unavailable for {reminder.id}"
            )


class BuggyDelivery:
    async def deliver(self, reminder: Reminder) -> None:
        raise RuntimeError(f"programming bug for {reminder.id}")


def _build_reminders(
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


def test_system_due_query_crosses_principals_and_filters_state(
    tmp_path: Path,
) -> None:
    repository, service = _build_reminders(tmp_path)
    later = service.create_reminder(
        "alice",
        "Later",
        NOW - timedelta(minutes=10),
    )
    earlier = service.create_reminder(
        "bob",
        "Earlier",
        NOW - timedelta(hours=1),
    )
    cancelled = service.create_reminder(
        "carol",
        "Cancelled",
        NOW - timedelta(hours=2),
    )
    service.cancel_reminder("carol", cancelled.id)
    service.create_reminder(
        "dave",
        "Future",
        NOW + timedelta(minutes=1),
    )

    assert repository.list_all_due_reminders(as_of=NOW) == (earlier, later)


def test_system_due_query_respects_delivery_backoff(tmp_path: Path) -> None:
    repository, service = _build_reminders(tmp_path)
    backed_off = service.create_reminder(
        "alice",
        "Retry later",
        NOW - timedelta(minutes=2),
    )
    ready = service.create_reminder(
        "bob",
        "Ready now",
        NOW - timedelta(minutes=1),
    )
    claimed = _claim(repository, backed_off)
    deferred = service.record_delivery_failure(
        "alice",
        backed_off.id,
        claimed_at=claimed.delivery_claimed_at,
    )

    assert deferred.next_delivery_attempt_at == NOW + timedelta(seconds=5)
    assert repository.list_all_due_reminders(as_of=NOW) == (ready,)
    assert repository.list_all_due_reminders(
        as_of=NOW + timedelta(seconds=5)
    ) == (deferred, ready)


def test_system_due_query_rejects_naive_as_of(tmp_path: Path) -> None:
    repository, _ = _build_reminders(tmp_path)

    with pytest.raises(ReminderValidationError, match="timezone-aware"):
        repository.list_all_due_reminders(
            as_of=datetime(2026, 8, 15, 16),
        )


@pytest.mark.asyncio
async def test_runner_delivers_due_reminders_across_principals(
    tmp_path: Path,
) -> None:
    repository, service = _build_reminders(tmp_path)
    alice = service.create_reminder(
        "alice",
        "Take out the garbage",
        (NOW - timedelta(minutes=5)).astimezone(TORONTO),
    )
    bob = service.create_reminder(
        "bob",
        "Call home",
        NOW - timedelta(minutes=1),
    )
    service.create_reminder(
        "alice",
        "Not yet",
        NOW + timedelta(minutes=1),
    )
    delivery = RecordingDelivery()
    runner = ReminderRunner(
        repository,
        service,
        delivery,
        clock=lambda: NOW,
    )

    result = await runner.run_once()

    assert result.attempted == 2
    assert result.delivered == 2
    assert result.failed == 0
    assert result.attempted_reminder_ids == (alice.id, bob.id)
    assert result.delivered_reminder_ids == (alice.id, bob.id)
    assert result.failures == ()
    assert [reminder.id for reminder in delivery.reminders] == [alice.id, bob.id]
    assert all(
        reminder.status is ReminderStatus.DELIVERING
        for reminder in delivery.reminders
    )
    assert delivery.reminders[0].principal_id == "alice"
    assert getattr(delivery.reminders[0].trigger_at.tzinfo, "key", None) == (
        "America/Toronto"
    )
    alice_loaded = service.get_reminder("alice", alice.id)
    bob_loaded = service.get_reminder("bob", bob.id)
    assert alice_loaded.status is ReminderStatus.DELIVERED
    assert bob_loaded.status is ReminderStatus.DELIVERED


@pytest.mark.resilience
@pytest.mark.asyncio
async def test_expected_delivery_failure_backs_off_and_does_not_block_later_reminder(
    tmp_path: Path,
) -> None:
    repository, service = _build_reminders(tmp_path)
    failed = service.create_reminder(
        "alice",
        "Fail first",
        NOW - timedelta(minutes=2),
    )
    succeeded = service.create_reminder(
        "bob",
        "Still deliver",
        NOW - timedelta(minutes=1),
    )
    delivery = RecordingDelivery(fail_ids=frozenset({failed.id}))
    runner = ReminderRunner(
        repository,
        service,
        delivery,
        clock=lambda: NOW,
    )

    result = await runner.run_once()

    assert result.attempted == 2
    assert result.delivered == 1
    assert result.failed == 1
    assert result.delivered_reminder_ids == (succeeded.id,)
    assert result.failures[0].reminder_id == failed.id
    assert result.failures[0].principal_id == "alice"
    assert result.failures[0].stage is ReminderRunFailureStage.DELIVERY
    assert result.failures[0].error_type == "ReminderDeliveryError"
    failed_loaded = service.get_reminder("alice", failed.id)
    succeeded_loaded = service.get_reminder("bob", succeeded.id)
    assert failed_loaded.status is ReminderStatus.SCHEDULED
    assert failed_loaded.delivery_attempt_count == 1
    assert failed_loaded.next_delivery_attempt_at == NOW + timedelta(seconds=5)
    assert failed_loaded.delivery_claimed_at is None
    assert succeeded_loaded.status is ReminderStatus.DELIVERED


@pytest.mark.resilience
@pytest.mark.asyncio
async def test_failed_reminder_is_not_retried_on_each_service_poll(
    tmp_path: Path,
) -> None:
    clock = MutableClock(NOW)
    repository, service = _build_reminders(tmp_path, clock=clock)
    reminder = service.create_reminder(
        "alice",
        "Back off",
        NOW - timedelta(minutes=1),
    )
    delivery = RecordingDelivery(fail_ids=frozenset({reminder.id}))
    runner = ReminderRunner(repository, service, delivery, clock=clock)

    first = await runner.run_once()
    assert first.failed == 1
    assert [item.id for item in delivery.reminders] == [reminder.id]

    clock.value = NOW + timedelta(seconds=1)
    second = await runner.run_once()
    assert second.attempted == 0
    assert [item.id for item in delivery.reminders] == [reminder.id]

    clock.value = NOW + timedelta(seconds=5)
    third = await runner.run_once()
    assert third.failed == 1
    assert [item.id for item in delivery.reminders] == [reminder.id, reminder.id]
    loaded = service.get_reminder("alice", reminder.id)
    assert loaded.delivery_attempt_count == 2
    assert loaded.next_delivery_attempt_at == NOW + timedelta(seconds=20)


@pytest.mark.asyncio
async def test_delivery_backoff_survives_repository_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "porter.db"
    database = Database(database_path)
    MigrationRunner(database).apply_all()
    repository = SqliteReminderRepository(database)
    service = ReminderService(
        repository,
        clock=lambda: NOW,
        id_generator=lambda: "reminder-restart",
    )
    reminder = service.create_reminder(
        "alice",
        "Persist retry",
        NOW - timedelta(minutes=1),
    )
    delivery = RecordingDelivery(fail_ids=frozenset({reminder.id}))
    runner = ReminderRunner(repository, service, delivery, clock=lambda: NOW)

    await runner.run_once()

    reopened_database = Database(database_path)
    MigrationRunner(reopened_database).apply_all()
    reopened_repository = SqliteReminderRepository(reopened_database)
    reopened_service = ReminderService(reopened_repository, clock=lambda: NOW)
    loaded = reopened_service.get_reminder("alice", reminder.id)

    assert loaded.delivery_attempt_count == 1
    assert loaded.next_delivery_attempt_at == NOW + timedelta(seconds=5)
    assert reopened_repository.list_all_due_reminders(as_of=NOW) == ()
    assert reopened_repository.list_all_due_reminders(
        as_of=NOW + timedelta(seconds=5)
    ) == (loaded,)


@pytest.mark.resilience
@pytest.mark.asyncio
async def test_successful_retry_clears_retry_state(tmp_path: Path) -> None:
    clock = MutableClock(NOW)
    repository, service = _build_reminders(tmp_path, clock=clock)
    reminder = service.create_reminder(
        "alice",
        "Eventually succeeds",
        NOW - timedelta(minutes=1),
    )
    failing_delivery = RecordingDelivery(fail_ids=frozenset({reminder.id}))
    runner = ReminderRunner(repository, service, failing_delivery, clock=clock)

    await runner.run_once()
    clock.value = NOW + timedelta(seconds=5)

    successful_delivery = RecordingDelivery()
    retry_runner = ReminderRunner(
        repository,
        service,
        successful_delivery,
        clock=clock,
    )
    result = await retry_runner.run_once()

    assert result.delivered_reminder_ids == (reminder.id,)
    loaded = service.get_reminder("alice", reminder.id)
    assert loaded.status is ReminderStatus.DELIVERED
    assert loaded.delivery_attempt_count == 0
    assert loaded.next_delivery_attempt_at is None
    assert loaded.delivery_claimed_at is None


@pytest.mark.asyncio
async def test_unexpected_delivery_exception_leaves_recoverable_claim(
    tmp_path: Path,
) -> None:
    repository, service = _build_reminders(tmp_path)
    reminder = service.create_reminder(
        "alice",
        "Bug should stop service",
        NOW - timedelta(minutes=1),
    )
    runner = ReminderRunner(
        repository,
        service,
        BuggyDelivery(),
        clock=lambda: NOW,
    )

    with pytest.raises(RuntimeError, match="programming bug"):
        await runner.run_once()

    loaded = service.get_reminder("alice", reminder.id)
    assert loaded.status is ReminderStatus.DELIVERING
    assert loaded.delivery_claimed_at == NOW
    assert loaded.delivery_attempt_count == 0
    assert loaded.next_delivery_attempt_at is None


@pytest.mark.asyncio
async def test_finalization_failure_preserves_at_least_once_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, service = _build_reminders(tmp_path)
    reminder = service.create_reminder(
        "alice",
        "Delivered but not finalized",
        NOW - timedelta(minutes=1),
    )
    delivery = RecordingDelivery()

    def fail_finalization(
        principal_id: str,
        reminder_id: str,
        *,
        claimed_at: datetime,
    ) -> Reminder:
        assert claimed_at == NOW
        raise RuntimeError(f"database unavailable for {principal_id}/{reminder_id}")

    monkeypatch.setattr(service, "mark_delivered", fail_finalization)
    runner = ReminderRunner(
        repository,
        service,
        delivery,
        clock=lambda: NOW,
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        await runner.run_once()

    assert [item.id for item in delivery.reminders] == [reminder.id]
    loaded = service.get_reminder("alice", reminder.id)
    assert loaded.status is ReminderStatus.DELIVERING
    assert loaded.delivery_claimed_at == NOW
    assert loaded.delivery_attempt_count == 0
    assert loaded.next_delivery_attempt_at is None


@pytest.mark.asyncio
async def test_runner_processes_reminders_that_became_due_while_offline(
    tmp_path: Path,
) -> None:
    repository, service = _build_reminders(tmp_path)
    overdue = service.create_reminder(
        "alice",
        "Missed while offline",
        NOW - timedelta(days=2),
    )
    delivery = RecordingDelivery()
    runner = ReminderRunner(
        repository,
        service,
        delivery,
        clock=lambda: NOW,
    )

    result = await runner.run_once()

    assert result.delivered_reminder_ids == (overdue.id,)
    loaded = service.get_reminder("alice", overdue.id)
    assert loaded.status is ReminderStatus.DELIVERED


@pytest.mark.asyncio
async def test_runner_with_no_due_reminders_is_a_noop(tmp_path: Path) -> None:
    repository, service = _build_reminders(tmp_path)
    service.create_reminder(
        "alice",
        "Future",
        NOW + timedelta(hours=1),
    )
    delivery = RecordingDelivery()
    runner = ReminderRunner(
        repository,
        service,
        delivery,
        clock=lambda: NOW,
    )

    result = await runner.run_once()

    assert result.attempted == 0
    assert result.delivered == 0
    assert result.failed == 0
    assert result.attempted_reminder_ids == ()
    assert result.delivered_reminder_ids == ()
    assert result.failures == ()
    assert delivery.reminders == []


@pytest.mark.asyncio
async def test_runner_rejects_naive_clock_before_delivery(tmp_path: Path) -> None:
    repository, service = _build_reminders(tmp_path)
    service.create_reminder(
        "alice",
        "Due",
        NOW - timedelta(minutes=1),
    )
    delivery = RecordingDelivery()
    runner = ReminderRunner(
        repository,
        service,
        delivery,
        clock=lambda: datetime(2026, 8, 15, 16),
    )

    with pytest.raises(ReminderValidationError, match="runner clock"):
        await runner.run_once()

    assert delivery.reminders == []
