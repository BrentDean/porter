from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from porter.storage.database import Database
from porter.storage.migrations import MigrationRunner
from porter.tasks import (
    SqliteTaskRepository,
    TaskListAlreadyExistsError,
    TaskNotFoundError,
    TaskService,
    TaskStatus,
)

NOW = datetime(2026, 8, 15, 12, tzinfo=UTC)
ALICE = "alice"
BOB = "bob"


def _service(
    tmp_path: Path,
    identifiers: list[str],
) -> TaskService:
    database = Database(tmp_path / "porter.db")
    MigrationRunner(database).apply_all()
    generated = iter(identifiers)
    return TaskService(
        SqliteTaskRepository(database),
        clock=lambda: NOW,
        id_generator=lambda: next(generated),
    )


def test_service_crud_completion_reopen_and_persistence(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path, ["list-1", "task-1"])
    task_list = service.create_list(ALICE, "Work")
    task = service.add_task(
        ALICE,
        task_list.id,
        "Write report",
        description="Draft the report",
        due=date(2026, 8, 20),
        priority=3,
    )

    updated = service.update_task(
        ALICE,
        task.id,
        summary="Write final report",
        description=None,
        due=None,
        priority=1,
    )
    assert updated.summary == "Write final report"
    assert updated.description is None
    assert updated.due is None
    assert updated.priority == 1

    completed = service.complete_task(ALICE, task.id)
    assert completed.status is TaskStatus.COMPLETED
    assert completed.completed_at == NOW

    reopened = service.reopen_task(ALICE, task.id)
    assert reopened.status is TaskStatus.NEEDS_ACTION
    assert reopened.completed_at is None

    restarted = TaskService(
        SqliteTaskRepository(Database(tmp_path / "porter.db")),
        clock=lambda: NOW,
        id_generator=lambda: "unused",
    )
    assert restarted.get_task(ALICE, task.id) == reopened


def test_service_scopes_list_names_and_tasks_by_principal(
    tmp_path: Path,
) -> None:
    service = _service(
        tmp_path,
        ["alice-list", "bob-list", "alice-task", "duplicate-list"],
    )
    alice_list = service.create_list(ALICE, "Shopping")
    bob_list = service.create_list(BOB, "Shopping")
    task = service.add_task(ALICE, alice_list.id, "Buy milk")

    assert service.get_list_by_name(ALICE, "shopping") == alice_list
    assert service.get_list_by_name(BOB, "shopping") == bob_list

    with pytest.raises(TaskListAlreadyExistsError):
        service.create_list(ALICE, "SHOPPING")
    with pytest.raises(TaskNotFoundError):
        service.get_task(BOB, task.id)
    with pytest.raises(TaskNotFoundError):
        service.complete_task(BOB, task.id)


def test_service_preserves_iana_timezone_deadline(tmp_path: Path) -> None:
    service = _service(tmp_path, ["list-1", "task-1"])
    task_list = service.create_list(ALICE, "Work")
    due = datetime(
        2026,
        8,
        20,
        17,
        30,
        tzinfo=ZoneInfo("America/Toronto"),
    )

    task = service.add_task(ALICE, task_list.id, "Deploy", due=due)

    assert service.get_task(ALICE, task.id).due == due


def test_task_mutations_are_id_authoritative(tmp_path: Path) -> None:
    service = _service(
        tmp_path,
        ["list-1", "task-1", "task-2"],
    )
    task_list = service.create_list(ALICE, "Work")
    first = service.add_task(ALICE, task_list.id, "Submit report")
    second = service.add_task(ALICE, task_list.id, "Submit report")

    with pytest.raises(TaskNotFoundError):
        service.complete_task(ALICE, "Submit report")

    assert (
        service.get_task(ALICE, first.id).status
        is TaskStatus.NEEDS_ACTION
    )
    assert (
        service.get_task(ALICE, second.id).status
        is TaskStatus.NEEDS_ACTION
    )


def test_service_move_and_delete_keep_order(tmp_path: Path) -> None:
    service = _service(
        tmp_path,
        ["list-1", "task-a", "task-b", "task-c"],
    )
    task_list = service.create_list(ALICE, "Work")
    a = service.add_task(ALICE, task_list.id, "A")
    b = service.add_task(ALICE, task_list.id, "B")
    c = service.add_task(ALICE, task_list.id, "C")

    service.move_task(ALICE, c.id, previous_task_id=None)
    assert [
        task.id
        for task in service.list_tasks(ALICE, list_id=task_list.id)
    ] == [
        c.id,
        a.id,
        b.id,
    ]

    service.delete_task(ALICE, a.id)
    assert [
        (task.id, task.position)
        for task in service.list_tasks(ALICE, list_id=task_list.id)
    ] == [
        (c.id, 0),
        (b.id, 1),
    ]
