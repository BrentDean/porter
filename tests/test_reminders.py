from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
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

NOW = datetime(2026, 8, 15, 16, tzinfo=UTC)
TORONTO = ZoneInfo("America/Toronto")


def _build_service(
    tmp_path: Path,
    *,
    clock=None,
) -> tuple[Database, SqliteReminderRepository, ReminderService]:
    database = Database(tmp_path / "porter.db")
    MigrationRunner(database).apply_all()
    repository = SqliteReminderRepository(database)
    identifiers = count(1)
    service = ReminderService(
        repository,
        clock=clock or (lambda: NOW),
        id_generator=lambda: f"reminder-{next(identifiers)}",
    )
    return database, repository, service


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


def test_reminder_migration_creates_schema_and_indexes(tmp_path: Path) -> None:
    database = Database(tmp_path / "porter.db")

    assert MigrationRunner(database).apply_all() == (
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
    )

    with database.connect() as connection:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(reminders)")
        }
        indexes = {
            row["name"]
            for row in connection.execute("PRAGMA index_list(reminders)")
        }

    assert columns == {
        "id",
        "principal_id",
        "message",
        "status",
        "trigger_at_utc",
        "trigger_timezone",
        "created_at",
        "updated_at",
        "delivered_at",
        "cancelled_at",
        "delivery_attempt_count",
        "next_delivery_attempt_at_utc",
        "delivery_claimed_at_utc",
        "kind",
        "duration_seconds",
    }
    assert "idx_reminders_principal_status" in indexes
    assert "idx_reminders_due" in indexes
    assert "idx_reminders_delivery_ready" in indexes
    assert "idx_reminders_delivery_claim" in indexes


def test_reminder_model_rejects_naive_trigger() -> None:
    with pytest.raises(ReminderValidationError, match="trigger_at"):
        Reminder(
            id="reminder-1",
            principal_id="alice",
            message="Do something",
            trigger_at=datetime(2026, 8, 15, 18),
            status=ReminderStatus.SCHEDULED,
            created_at=NOW,
            updated_at=NOW,
        )


def test_reminder_model_rejects_non_iana_trigger_timezone() -> None:
    fixed_offset = timezone(timedelta(hours=-4))

    with pytest.raises(ReminderValidationError, match="IANA timezone or UTC"):
        Reminder(
            id="reminder-1",
            principal_id="alice",
            message="Do something",
            trigger_at=datetime(2026, 8, 15, 18, tzinfo=fixed_offset),
            status=ReminderStatus.SCHEDULED,
            created_at=NOW,
            updated_at=NOW,
        )


@pytest.mark.parametrize(
    ("delivery_attempt_count", "next_delivery_attempt_at"),
    [
        (-1, None),
        (0, NOW),
        (1, None),
    ],
)
def test_reminder_model_rejects_invalid_retry_state(
    delivery_attempt_count: int,
    next_delivery_attempt_at: datetime | None,
) -> None:
    with pytest.raises(ReminderValidationError):
        Reminder(
            id="reminder-1",
            principal_id="alice",
            message="Do something",
            trigger_at=NOW,
            status=ReminderStatus.SCHEDULED,
            created_at=NOW,
            updated_at=NOW,
            delivery_attempt_count=delivery_attempt_count,
            next_delivery_attempt_at=next_delivery_attempt_at,
        )


@pytest.mark.parametrize(
    ("status", "delivered_at", "cancelled_at", "delivery_claimed_at"),
    [
        (ReminderStatus.SCHEDULED, NOW, None, None),
        (ReminderStatus.DELIVERING, None, None, None),
        (ReminderStatus.DELIVERED, None, None, None),
        (ReminderStatus.CANCELLED, None, None, None),
        (ReminderStatus.DELIVERED, NOW, NOW, None),
        (ReminderStatus.CANCELLED, NOW, NOW, None),
        (ReminderStatus.DELIVERED, NOW, None, NOW),
    ],
)
def test_reminder_model_rejects_inconsistent_state(
    status: ReminderStatus,
    delivered_at: datetime | None,
    cancelled_at: datetime | None,
    delivery_claimed_at: datetime | None,
) -> None:
    with pytest.raises(ReminderValidationError):
        Reminder(
            id="reminder-1",
            principal_id="alice",
            message="Do something",
            trigger_at=NOW,
            status=status,
            created_at=NOW,
            updated_at=NOW,
            delivered_at=delivered_at,
            cancelled_at=cancelled_at,
            delivery_claimed_at=delivery_claimed_at,
        )


def test_service_uses_injected_clock_and_id_and_round_trips_timezone(
    tmp_path: Path,
) -> None:
    _, repository, service = _build_service(tmp_path)
    trigger = datetime(2026, 8, 15, 19, 30, tzinfo=TORONTO)

    created = service.create_reminder(
        " alice ",
        " Take out the garbage ",
        trigger,
    )
    loaded = repository.get_reminder("alice", created.id)

    assert created.id == "reminder-1"
    assert created.principal_id == "alice"
    assert created.message == "Take out the garbage"
    assert created.created_at == NOW
    assert created.updated_at == NOW
    assert created.delivery_attempt_count == 0
    assert created.next_delivery_attempt_at is None
    assert created.delivery_claimed_at is None
    assert loaded.trigger_at == trigger
    assert getattr(loaded.trigger_at.tzinfo, "key", None) == "America/Toronto"


def test_principal_isolation_hides_other_users_reminders(tmp_path: Path) -> None:
    _, _, service = _build_service(tmp_path)
    reminder = service.create_reminder("alice", "Private", NOW)

    with pytest.raises(ReminderNotFoundError):
        service.get_reminder("bob", reminder.id)
    with pytest.raises(ReminderNotFoundError):
        service.cancel_reminder("bob", reminder.id)

    assert service.list_reminders("bob") == ()
    assert service.list_reminders("alice") == (reminder,)


def test_list_reminders_can_filter_by_status(tmp_path: Path) -> None:
    _, _, service = _build_service(tmp_path)
    first = service.create_reminder("alice", "First", NOW)
    second = service.create_reminder("alice", "Second", NOW + timedelta(hours=1))
    cancelled = service.cancel_reminder("alice", first.id)

    assert service.list_reminders(
        "alice",
        status=ReminderStatus.SCHEDULED,
    ) == (second,)
    assert service.list_reminders(
        "alice",
        status=ReminderStatus.CANCELLED,
    ) == (cancelled,)


def test_due_reminders_are_filtered_and_ordered(tmp_path: Path) -> None:
    _, _, service = _build_service(tmp_path)
    later_due = service.create_reminder(
        "alice",
        "Later due",
        NOW - timedelta(minutes=10),
    )
    earlier_due = service.create_reminder(
        "alice",
        "Earlier due",
        NOW - timedelta(hours=1),
    )
    cancelled = service.create_reminder(
        "alice",
        "Cancelled",
        NOW - timedelta(hours=2),
    )
    service.cancel_reminder("alice", cancelled.id)
    service.create_reminder("alice", "Future", NOW + timedelta(minutes=1))
    service.create_reminder("bob", "Bob due", NOW - timedelta(hours=3))

    assert service.due_reminders("alice") == (earlier_due, later_due)


def test_principal_due_reminders_remain_due_during_delivery_backoff(
    tmp_path: Path,
) -> None:
    _, repository, service = _build_service(tmp_path)
    reminder = service.create_reminder(
        "alice",
        "Still logically due",
        NOW - timedelta(minutes=1),
    )
    claimed = _claim(repository, reminder)
    deferred = service.record_delivery_failure(
        "alice",
        reminder.id,
        claimed_at=claimed.delivery_claimed_at,
    )

    assert deferred.next_delivery_attempt_at == NOW + timedelta(seconds=5)
    assert service.due_reminders("alice") == (deferred,)


def test_due_reminders_accept_explicit_aware_as_of(tmp_path: Path) -> None:
    _, _, service = _build_service(tmp_path)
    reminder = service.create_reminder(
        "alice",
        "Later",
        NOW + timedelta(hours=2),
    )

    assert service.due_reminders("alice") == ()
    assert service.due_reminders(
        "alice",
        as_of=NOW + timedelta(hours=2),
    ) == (reminder,)

    with pytest.raises(ReminderValidationError, match="as_of"):
        service.due_reminders(
            "alice",
            as_of=datetime(2026, 8, 15, 18),
        )


def test_delivery_failure_uses_bounded_retry_schedule(tmp_path: Path) -> None:
    _, repository, service = _build_service(tmp_path)
    reminder = service.create_reminder("alice", "Retry me", NOW)
    delays = (5, 15, 30, 60, 120, 300, 300)

    current = reminder
    claim_at = NOW
    for attempt_count, delay_seconds in enumerate(delays, start=1):
        claimed = _claim(repository, reminder, claimed_at=claim_at)
        current = service.record_delivery_failure(
            "alice",
            reminder.id,
            claimed_at=claimed.delivery_claimed_at,
        )
        assert current.delivery_attempt_count == attempt_count
        assert current.next_delivery_attempt_at == NOW + timedelta(
            seconds=delay_seconds
        )
        claim_at = current.next_delivery_attempt_at


def test_cancel_reminder_is_idempotent_and_clears_retry_state(
    tmp_path: Path,
) -> None:
    cancelled_at = NOW + timedelta(minutes=5)
    times = iter((NOW, NOW, cancelled_at))
    _, repository, service = _build_service(tmp_path, clock=lambda: next(times))
    reminder = service.create_reminder("alice", "Cancel me", NOW)
    claimed = _claim(repository, reminder)
    service.record_delivery_failure(
        "alice",
        reminder.id,
        claimed_at=claimed.delivery_claimed_at,
    )

    cancelled = service.cancel_reminder("alice", reminder.id)
    again = service.cancel_reminder("alice", reminder.id)

    assert cancelled.status is ReminderStatus.CANCELLED
    assert cancelled.cancelled_at == cancelled_at
    assert cancelled.delivered_at is None
    assert cancelled.delivery_attempt_count == 0
    assert cancelled.next_delivery_attempt_at is None
    assert cancelled.delivery_claimed_at is None
    assert again == cancelled


def test_mark_delivered_is_idempotent_and_clears_retry_state(
    tmp_path: Path,
) -> None:
    delivered_at = NOW + timedelta(minutes=5)
    times = iter((NOW, NOW, delivered_at))
    _, repository, service = _build_service(tmp_path, clock=lambda: next(times))
    reminder = service.create_reminder("alice", "Deliver me", NOW)
    first_claim = _claim(repository, reminder)
    service.record_delivery_failure(
        "alice",
        reminder.id,
        claimed_at=first_claim.delivery_claimed_at,
    )
    second_claim = _claim(
        repository,
        reminder,
        claimed_at=NOW + timedelta(seconds=5),
    )

    delivered = service.mark_delivered(
        "alice",
        reminder.id,
        claimed_at=second_claim.delivery_claimed_at,
    )
    again = service.mark_delivered(
        "alice",
        reminder.id,
        claimed_at=second_claim.delivery_claimed_at,
    )

    assert delivered.status is ReminderStatus.DELIVERED
    assert delivered.delivered_at == delivered_at
    assert delivered.cancelled_at is None
    assert delivered.delivery_attempt_count == 0
    assert delivered.next_delivery_attempt_at is None
    assert delivered.delivery_claimed_at is None
    assert again == delivered


def test_terminal_states_cannot_cross_over(tmp_path: Path) -> None:
    _, repository, service = _build_service(tmp_path)
    delivered = service.create_reminder("alice", "Delivered", NOW)
    cancelled = service.create_reminder("alice", "Cancelled", NOW)

    claimed = _claim(repository, delivered)
    service.mark_delivered(
        "alice",
        delivered.id,
        claimed_at=claimed.delivery_claimed_at,
    )
    service.cancel_reminder("alice", cancelled.id)

    with pytest.raises(ReminderStateError, match="cannot be cancelled"):
        service.cancel_reminder("alice", delivered.id)
    with pytest.raises(ReminderStateError, match="only delivering"):
        service.mark_delivered(
            "alice",
            cancelled.id,
            claimed_at=NOW,
        )
    with pytest.raises(ReminderStateError, match="only be recorded"):
        service.record_delivery_failure(
            "alice",
            delivered.id,
            claimed_at=NOW,
        )


def test_service_rejects_naive_clock(tmp_path: Path) -> None:
    _, _, service = _build_service(
        tmp_path,
        clock=lambda: datetime(2026, 8, 15, 16),
    )

    with pytest.raises(ReminderValidationError, match="clock"):
        service.create_reminder("alice", "Test", NOW)
