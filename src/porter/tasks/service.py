from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Final
from uuid import uuid4

from porter.core.clock import utc_now
from porter.tasks.errors import TaskValidationError
from porter.tasks.models import Due, Task, TaskList, TaskStatus
from porter.tasks.repository import TaskRepository


class _Unset:
    pass


_UNSET: Final = _Unset()


def _default_id_generator() -> str:
    return str(uuid4())


def _clean_required_text(value: str, field: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise TaskValidationError(f"{field} must not be empty")
    return cleaned


class TaskService:
    """Porter-owned task behavior over an interchangeable repository."""

    def __init__(
        self,
        repository: TaskRepository,
        *,
        clock: Callable[[], datetime] | None = None,
        id_generator: Callable[[], str] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or utc_now
        self._id_generator = id_generator or _default_id_generator

    def create_list(self, principal_id: str, name: str) -> TaskList:
        principal_id = _clean_required_text(principal_id, "principal id")
        now = self._now()
        task_list = TaskList(
            id=self._new_id(),
            principal_id=principal_id,
            name=_clean_required_text(name, "task list name"),
            position=0,
            created_at=now,
            updated_at=now,
        )
        return self._repository.create_list(task_list)

    def get_list(self, principal_id: str, list_id: str) -> TaskList:
        return self._repository.get_list(
            _clean_required_text(principal_id, "principal id"),
            _clean_required_text(list_id, "task list id"),
        )

    def get_list_by_name(self, principal_id: str, name: str) -> TaskList:
        return self._repository.get_list_by_name(
            _clean_required_text(principal_id, "principal id"),
            _clean_required_text(name, "task list name"),
        )

    def list_lists(self, principal_id: str) -> tuple[TaskList, ...]:
        return self._repository.list_lists(
            _clean_required_text(principal_id, "principal id")
        )

    def rename_list(
        self,
        principal_id: str,
        list_id: str,
        name: str,
    ) -> TaskList:
        return self._repository.rename_list(
            _clean_required_text(principal_id, "principal id"),
            _clean_required_text(list_id, "task list id"),
            name=_clean_required_text(name, "task list name"),
            updated_at=self._now(),
        )

    def add_task(
        self,
        principal_id: str,
        list_id: str,
        summary: str,
        *,
        description: str | None = None,
        due: Due | None = None,
        priority: int = 0,
    ) -> Task:
        principal_id = _clean_required_text(principal_id, "principal id")
        now = self._now()
        task = Task(
            id=self._new_id(),
            list_id=_clean_required_text(list_id, "task list id"),
            summary=_clean_required_text(summary, "task summary"),
            description=description,
            status=TaskStatus.NEEDS_ACTION,
            due=due,
            priority=priority,
            position=0,
            created_at=now,
            updated_at=now,
        )
        return self._repository.create_task(principal_id, task)

    def get_task(self, principal_id: str, task_id: str) -> Task:
        return self._repository.get_task(
            _clean_required_text(principal_id, "principal id"),
            _clean_required_text(task_id, "task id"),
        )

    def list_tasks(
        self,
        principal_id: str,
        *,
        list_id: str | None = None,
        status: TaskStatus | None = None,
    ) -> tuple[Task, ...]:
        principal_id = _clean_required_text(principal_id, "principal id")
        if list_id is not None:
            list_id = _clean_required_text(list_id, "task list id")
        return self._repository.list_tasks(
            principal_id,
            list_id=list_id,
            status=status,
        )

    def update_task(
        self,
        principal_id: str,
        task_id: str,
        *,
        summary: str | None = None,
        description: str | None | _Unset = _UNSET,
        due: Due | None | _Unset = _UNSET,
        priority: int | None = None,
    ) -> Task:
        principal_id = _clean_required_text(principal_id, "principal id")
        current = self._repository.get_task(
            principal_id,
            _clean_required_text(task_id, "task id"),
        )

        next_summary = (
            current.summary
            if summary is None
            else _clean_required_text(summary, "task summary")
        )
        next_description = (
            current.description
            if isinstance(description, _Unset)
            else description
        )
        next_due = current.due if isinstance(due, _Unset) else due
        next_priority = current.priority if priority is None else priority

        updated = replace(
            current,
            summary=next_summary,
            description=next_description,
            due=next_due,
            priority=next_priority,
            updated_at=self._now(),
        )
        return self._repository.update_task(principal_id, updated)

    def complete_task(self, principal_id: str, task_id: str) -> Task:
        principal_id = _clean_required_text(principal_id, "principal id")
        current = self._repository.get_task(
            principal_id,
            _clean_required_text(task_id, "task id"),
        )
        if current.status is TaskStatus.COMPLETED:
            return current

        now = self._now()
        return self._repository.update_task(
            principal_id,
            replace(
                current,
                status=TaskStatus.COMPLETED,
                updated_at=now,
                completed_at=now,
            ),
        )

    def reopen_task(self, principal_id: str, task_id: str) -> Task:
        principal_id = _clean_required_text(principal_id, "principal id")
        current = self._repository.get_task(
            principal_id,
            _clean_required_text(task_id, "task id"),
        )
        if current.status is TaskStatus.NEEDS_ACTION:
            return current

        return self._repository.update_task(
            principal_id,
            replace(
                current,
                status=TaskStatus.NEEDS_ACTION,
                updated_at=self._now(),
                completed_at=None,
            ),
        )

    def delete_task(self, principal_id: str, task_id: str) -> None:
        self._repository.delete_task(
            _clean_required_text(principal_id, "principal id"),
            _clean_required_text(task_id, "task id"),
        )

    def move_task(
        self,
        principal_id: str,
        task_id: str,
        previous_task_id: str | None = None,
    ) -> Task:
        principal_id = _clean_required_text(principal_id, "principal id")
        task_id = _clean_required_text(task_id, "task id")
        if previous_task_id is not None:
            previous_task_id = _clean_required_text(
                previous_task_id,
                "previous task id",
            )
        return self._repository.move_task(
            principal_id,
            task_id,
            previous_task_id=previous_task_id,
            updated_at=self._now(),
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise TaskValidationError(
                "task service clock must return a timezone-aware datetime"
            )
        return value.astimezone(UTC)

    def _new_id(self) -> str:
        return _clean_required_text(
            self._id_generator(),
            "generated task id",
        )
