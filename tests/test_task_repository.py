from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from porter.storage.database import Database
from porter.storage.migrations import MigrationRunner
from porter.tasks import (
    InvalidTaskMoveError,
    SqliteTaskRepository,
    Task,
    TaskList,
    TaskListAlreadyExistsError,
    TaskListNotFoundError,
    TaskNotFoundError,
    TaskStatus,
)

NOW = datetime(2026, 8, 15, 12, tzinfo=UTC)
ALICE = "alice"
BOB = "bob"


def _repository(tmp_path: Path) -> SqliteTaskRepository:
    database = Database(tmp_path / "porter.db")
    MigrationRunner(database).apply_all()
    return SqliteTaskRepository(database)


def _list(identifier: str, principal_id: str, name: str) -> TaskList:
    return TaskList(
        id=identifier,
        principal_id=principal_id,
        name=name,
        position=0,
        created_at=NOW,
        updated_at=NOW,
    )


def _task(
    identifier: str,
    list_id: str,
    summary: str,
    *,
    due=None,
) -> Task:
    return Task(
        id=identifier,
        list_id=list_id,
        summary=summary,
        description=None,
        status=TaskStatus.NEEDS_ACTION,
        due=due,
        priority=0,
        position=0,
        created_at=NOW,
        updated_at=NOW,
    )


def test_list_names_are_unique_per_principal(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    alice = repository.create_list(_list("list-a", ALICE, "Shopping"))
    bob = repository.create_list(_list("list-b", BOB, "Shopping"))

    assert repository.get_list_by_name(ALICE, "shopping") == alice
    assert repository.get_list_by_name(BOB, "shopping") == bob

    with pytest.raises(TaskListAlreadyExistsError):
        repository.create_list(_list("list-c", ALICE, " SHOPPING "))


def test_principals_cannot_read_or_mutate_each_others_tasks(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    repository.create_list(_list("list-a", ALICE, "Work"))
    repository.create_list(_list("list-b", BOB, "Work"))
    alice_task = repository.create_task(
        ALICE,
        _task("task-a", "list-a", "Private task"),
    )

    with pytest.raises(TaskListNotFoundError):
        repository.get_list(BOB, "list-a")
    with pytest.raises(TaskNotFoundError):
        repository.get_task(BOB, alice_task.id)
    with pytest.raises(TaskNotFoundError):
        repository.delete_task(BOB, alice_task.id)

    assert repository.get_task(ALICE, alice_task.id) == alice_task


def test_duplicate_task_summaries_are_allowed(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    repository.create_list(_list("list-1", ALICE, "Work"))

    first = repository.create_task(
        ALICE,
        _task("task-1", "list-1", "Submit report"),
    )
    second = repository.create_task(
        ALICE,
        _task("task-2", "list-1", "Submit report"),
    )

    assert first.position == 0
    assert second.position == 1
    assert [
        task.id
        for task in repository.list_tasks(ALICE, list_id="list-1")
    ] == [
        "task-1",
        "task-2",
    ]


def test_due_values_round_trip_across_repository_instances(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    repository.create_list(_list("list-1", ALICE, "Work"))

    date_task = repository.create_task(
        ALICE,
        _task(
            "task-date",
            "list-1",
            "All day",
            due=date(2026, 8, 20),
        ),
    )
    due_datetime = datetime(
        2026,
        8,
        20,
        17,
        30,
        tzinfo=ZoneInfo("America/Toronto"),
    )
    datetime_task = repository.create_task(
        ALICE,
        _task(
            "task-datetime",
            "list-1",
            "Timed",
            due=due_datetime,
        ),
    )

    restarted = SqliteTaskRepository(Database(tmp_path / "porter.db"))

    assert restarted.get_task(ALICE, date_task.id).due == date(2026, 8, 20)
    restored = restarted.get_task(ALICE, datetime_task.id).due
    assert restored == due_datetime
    assert getattr(restored.tzinfo, "key", None) == "America/Toronto"


def test_move_task_uses_previous_task_semantics(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    repository.create_list(_list("list-1", ALICE, "Work"))
    for identifier in ("a", "b", "c"):
        repository.create_task(
            ALICE,
            _task(identifier, "list-1", identifier.upper()),
        )

    repository.move_task(
        ALICE,
        "c",
        previous_task_id=None,
        updated_at=NOW,
    )
    assert [
        task.id
        for task in repository.list_tasks(ALICE, list_id="list-1")
    ] == [
        "c",
        "a",
        "b",
    ]

    repository.move_task(
        ALICE,
        "c",
        previous_task_id="b",
        updated_at=NOW,
    )
    assert [
        task.id
        for task in repository.list_tasks(ALICE, list_id="list-1")
    ] == [
        "a",
        "b",
        "c",
    ]


def test_move_task_rejects_cross_list_previous_task(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    repository.create_list(_list("list-1", ALICE, "One"))
    repository.create_list(_list("list-2", ALICE, "Two"))
    repository.create_task(ALICE, _task("task-1", "list-1", "One"))
    repository.create_task(ALICE, _task("task-2", "list-2", "Two"))

    with pytest.raises(InvalidTaskMoveError):
        repository.move_task(
            ALICE,
            "task-1",
            previous_task_id="task-2",
            updated_at=NOW,
        )


def test_delete_task_compacts_manual_positions(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    repository.create_list(_list("list-1", ALICE, "Work"))
    for identifier in ("a", "b", "c"):
        repository.create_task(
            ALICE,
            _task(identifier, "list-1", identifier.upper()),
        )

    repository.delete_task(ALICE, "b")

    tasks = repository.list_tasks(ALICE, list_id="list-1")
    assert [(task.id, task.position) for task in tasks] == [
        ("a", 0),
        ("c", 1),
    ]


def test_missing_records_fail_predictably(tmp_path: Path) -> None:
    repository = _repository(tmp_path)

    with pytest.raises(TaskListNotFoundError):
        repository.get_list(ALICE, "missing-list")
    with pytest.raises(TaskNotFoundError):
        repository.get_task(ALICE, "missing-task")
