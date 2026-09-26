from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from itertools import count
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from porter.storage.database import Database
from porter.storage.migrations import MigrationRunner
from porter.tasks import (
    SqliteTaskRepository,
    Task,
    TaskService,
    TaskStatus,
)
from porter.tasks.planning import PlannerService

ALICE = "alice"
BOB = "bob"
TORONTO = ZoneInfo("America/Toronto")


@dataclass
class MutableClock:
    value: datetime

    def __call__(self) -> datetime:
        return self.value


def _services(
    tmp_path: Path,
    now: datetime,
) -> tuple[
    TaskService,
    PlannerService,
    SqliteTaskRepository,
    MutableClock,
]:
    database = Database(tmp_path / "porter.db")
    MigrationRunner(database).apply_all()
    repository = SqliteTaskRepository(database)
    clock = MutableClock(now)
    identifiers = count(1)
    task_service = TaskService(
        repository,
        clock=clock,
        id_generator=lambda: f"id-{next(identifiers)}",
    )
    planner_service = PlannerService(task_service, clock=clock)
    return task_service, planner_service, repository, clock


def _summaries(items) -> list[str]:
    return [item.task.summary for item in items]


def _all_snapshot_task_ids(snapshot) -> set[str]:
    return {
        item.task.id
        for bucket in (
            snapshot.unscheduled,
            snapshot.overdue,
            snapshot.today,
            snapshot.upcoming,
            snapshot.completed,
        )
        for item in bucket
    }


def test_snapshot_is_principal_scoped(tmp_path: Path) -> None:
    task_service, planner, _, _ = _services(
        tmp_path,
        datetime(2026, 8, 15, 16, tzinfo=UTC),
    )
    alice_list = task_service.create_list(ALICE, "Work")
    bob_list = task_service.create_list(BOB, "Work")
    alice_task = task_service.add_task(ALICE, alice_list.id, "Alice task")
    bob_task = task_service.add_task(BOB, bob_list.id, "Bob task")

    alice = planner.snapshot(ALICE, timezone=TORONTO)

    assert _all_snapshot_task_ids(alice) == {alice_task.id}
    assert bob_task.id not in _all_snapshot_task_ids(alice)


def test_snapshot_classifies_due_boundaries_and_window(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 15, 16, tzinfo=UTC)
    task_service, planner, _, _ = _services(tmp_path, now)
    work = task_service.create_list(ALICE, "Work")

    task_service.add_task(ALICE, work.id, "Unscheduled")
    task_service.add_task(
        ALICE,
        work.id,
        "Yesterday",
        due=date(2026, 8, 14),
    )
    task_service.add_task(
        ALICE,
        work.id,
        "All day today",
        due=date(2026, 8, 15),
    )
    task_service.add_task(
        ALICE,
        work.id,
        "Past timed",
        due=datetime(2026, 8, 15, 11, tzinfo=TORONTO),
    )
    task_service.add_task(
        ALICE,
        work.id,
        "Future timed",
        due=datetime(2026, 8, 15, 17, tzinfo=TORONTO),
    )
    task_service.add_task(
        ALICE,
        work.id,
        "Tomorrow",
        due=date(2026, 8, 16),
    )
    task_service.add_task(
        ALICE,
        work.id,
        "Window edge",
        due=date(2026, 8, 22),
    )
    task_service.add_task(
        ALICE,
        work.id,
        "Beyond window",
        due=date(2026, 8, 23),
    )

    snapshot = planner.snapshot(
        ALICE,
        timezone=TORONTO,
        upcoming_days=7,
    )

    assert snapshot.as_of == datetime(
        2026,
        8,
        15,
        12,
        tzinfo=TORONTO,
    )
    assert snapshot.timezone == "America/Toronto"
    assert _summaries(snapshot.unscheduled) == ["Unscheduled"]
    assert _summaries(snapshot.overdue) == ["Yesterday", "Past timed"]
    assert _summaries(snapshot.today) == ["Future timed", "All day today"]
    assert _summaries(snapshot.upcoming) == ["Tomorrow", "Window edge"]
    assert "Beyond window" not in {
        item.task.summary
        for item in snapshot.upcoming
    }


def test_datetime_buckets_use_requested_timezone(tmp_path: Path) -> None:
    now = datetime(2026, 8, 16, 2, tzinfo=UTC)
    task_service, planner, _, _ = _services(tmp_path, now)
    work = task_service.create_list(ALICE, "Work")

    task_service.add_task(
        ALICE,
        work.id,
        "Already passed locally",
        due=datetime(2026, 8, 16, 1, tzinfo=UTC),
    )
    task_service.add_task(
        ALICE,
        work.id,
        "Still today locally",
        due=datetime(2026, 8, 16, 3, tzinfo=UTC),
    )
    task_service.add_task(
        ALICE,
        work.id,
        "Tomorrow locally",
        due=datetime(2026, 8, 16, 5, tzinfo=UTC),
    )

    snapshot = planner.snapshot(ALICE, timezone=TORONTO)

    assert snapshot.as_of.date() == date(2026, 8, 15)
    assert _summaries(snapshot.overdue) == ["Already passed locally"]
    assert _summaries(snapshot.today) == ["Still today locally"]
    assert _summaries(snapshot.upcoming) == ["Tomorrow locally"]


def test_datetime_buckets_compare_real_instants_across_dst_fold(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
    task_service, planner, _, _ = _services(tmp_path, now)
    work = task_service.create_list(ALICE, "Work")

    first_115 = datetime(
        2026,
        11,
        1,
        1,
        15,
        tzinfo=TORONTO,
        fold=0,
    )
    second_115 = datetime(
        2026,
        11,
        1,
        1,
        15,
        tzinfo=TORONTO,
        fold=1,
    )
    task_service.add_task(
        ALICE,
        work.id,
        "First 1:15",
        due=first_115,
    )
    task_service.add_task(
        ALICE,
        work.id,
        "Second 1:15",
        due=second_115,
    )

    snapshot = planner.snapshot(ALICE, timezone=TORONTO)

    assert first_115.astimezone(UTC) < now
    assert second_115.astimezone(UTC) > now
    assert _summaries(snapshot.overdue) == ["First 1:15"]
    assert _summaries(snapshot.today) == ["Second 1:15"]


def test_priority_and_manual_positions_produce_stable_order(
    tmp_path: Path,
) -> None:
    task_service, planner, _, _ = _services(
        tmp_path,
        datetime(2026, 8, 15, 16, tzinfo=UTC),
    )
    work = task_service.create_list(ALICE, "Work")
    personal = task_service.create_list(ALICE, "Personal")

    task_service.add_task(
        ALICE,
        work.id,
        "Undefined",
        priority=0,
    )
    task_service.add_task(
        ALICE,
        work.id,
        "Work high",
        priority=1,
    )
    task_service.add_task(
        ALICE,
        work.id,
        "Normal",
        priority=5,
    )
    task_service.add_task(
        ALICE,
        personal.id,
        "Personal high",
        priority=1,
    )
    task_service.add_task(
        ALICE,
        work.id,
        "All day",
        due=date(2026, 8, 15),
    )
    task_service.add_task(
        ALICE,
        personal.id,
        "Timed",
        due=datetime(2026, 8, 15, 17, tzinfo=TORONTO),
    )

    snapshot = planner.snapshot(ALICE, timezone=TORONTO)

    assert _summaries(snapshot.unscheduled) == [
        "Work high",
        "Personal high",
        "Normal",
        "Undefined",
    ]
    assert _summaries(snapshot.today) == ["Timed", "All day"]


def test_completed_items_sort_known_completion_before_imported_unknown(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 15, 12, tzinfo=UTC)
    task_service, planner, repository, clock = _services(tmp_path, now)
    work = task_service.create_list(ALICE, "Work")
    older = task_service.add_task(ALICE, work.id, "Older completion")
    newer = task_service.add_task(ALICE, work.id, "Newer completion")

    clock.value = datetime(2026, 8, 15, 13, tzinfo=UTC)
    task_service.complete_task(ALICE, older.id)
    clock.value = datetime(2026, 8, 15, 14, tzinfo=UTC)
    task_service.complete_task(ALICE, newer.id)

    imported = Task(
        id="imported-completed",
        list_id=work.id,
        summary="Imported completion",
        description=None,
        status=TaskStatus.COMPLETED,
        due=None,
        priority=0,
        position=0,
        created_at=datetime(2026, 8, 15, 10, tzinfo=UTC),
        updated_at=datetime(2026, 8, 15, 15, tzinfo=UTC),
        completed_at=None,
    )
    repository.create_task(ALICE, imported)
    clock.value = datetime(2026, 8, 15, 16, tzinfo=UTC)

    snapshot = planner.snapshot(ALICE, timezone=TORONTO)

    assert _summaries(snapshot.completed) == [
        "Newer completion",
        "Older completion",
        "Imported completion",
    ]


def test_zero_upcoming_window_excludes_future_dates(tmp_path: Path) -> None:
    task_service, planner, _, _ = _services(
        tmp_path,
        datetime(2026, 8, 15, 16, tzinfo=UTC),
    )
    work = task_service.create_list(ALICE, "Work")
    task_service.add_task(
        ALICE,
        work.id,
        "Tomorrow",
        due=date(2026, 8, 16),
    )

    snapshot = planner.snapshot(
        ALICE,
        timezone=TORONTO,
        upcoming_days=0,
    )

    assert snapshot.upcoming == ()


def test_planner_rejects_invalid_window_and_naive_clock(
    tmp_path: Path,
) -> None:
    task_service, planner, _, _ = _services(
        tmp_path,
        datetime(2026, 8, 15, 16, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="upcoming_days"):
        planner.snapshot(
            ALICE,
            timezone=TORONTO,
            upcoming_days=-1,
        )

    naive_planner = PlannerService(
        task_service,
        clock=lambda: datetime(2026, 8, 15, 12),
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        naive_planner.snapshot(ALICE, timezone=TORONTO)
