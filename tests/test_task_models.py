from datetime import UTC, date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from porter.tasks import Task, TaskList, TaskStatus, TaskValidationError

NOW = datetime(2026, 8, 15, 12, tzinfo=UTC)


def _task(**changes):
    values = {
        "id": "task-1",
        "list_id": "list-1",
        "summary": "Buy milk",
        "description": None,
        "status": TaskStatus.NEEDS_ACTION,
        "due": None,
        "priority": 0,
        "position": 0,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(changes)
    return Task(**values)


def test_task_list_requires_principal() -> None:
    with pytest.raises(TaskValidationError, match="principal id"):
        TaskList(
            id="list-1",
            principal_id=" ",
            name="Work",
            position=0,
            created_at=NOW,
            updated_at=NOW,
        )


def test_task_accepts_date_only_due() -> None:
    task = _task(due=date(2026, 8, 20))

    assert task.due == date(2026, 8, 20)


def test_task_accepts_iana_timezone_aware_due_datetime() -> None:
    due = datetime(
        2026,
        8,
        20,
        17,
        30,
        tzinfo=ZoneInfo("America/Toronto"),
    )

    assert _task(due=due).due == due


def test_task_rejects_naive_due_datetime() -> None:
    with pytest.raises(TaskValidationError, match="timezone-aware"):
        _task(due=datetime(2026, 8, 20, 17, 30))


def test_task_rejects_non_iana_non_utc_due_timezone() -> None:
    with pytest.raises(TaskValidationError, match="IANA timezone or UTC"):
        _task(
            due=datetime(
                2026,
                8,
                20,
                17,
                30,
                tzinfo=timezone(timedelta(hours=-5)),
            )
        )


@pytest.mark.parametrize("priority", [-1, 10])
def test_task_rejects_priority_outside_rfc5545_range(
    priority: int,
) -> None:
    with pytest.raises(TaskValidationError, match="between 0 and 9"):
        _task(priority=priority)


def test_completed_at_requires_completed_status() -> None:
    with pytest.raises(TaskValidationError, match="completed status"):
        _task(
            completed_at=datetime(
                2026,
                8,
                15,
                13,
                tzinfo=UTC,
            )
        )
