from __future__ import annotations

from datetime import datetime
from typing import Protocol

from porter.tasks.models import Task, TaskList, TaskStatus


class TaskRepository(Protocol):
    """Persistence boundary for Porter task lists and tasks."""

    def create_list(self, task_list: TaskList) -> TaskList:
        ...

    def get_list(self, principal_id: str, list_id: str) -> TaskList:
        ...

    def get_list_by_name(self, principal_id: str, name: str) -> TaskList:
        ...

    def list_lists(self, principal_id: str) -> tuple[TaskList, ...]:
        ...

    def rename_list(
        self,
        principal_id: str,
        list_id: str,
        *,
        name: str,
        updated_at: datetime,
    ) -> TaskList:
        ...

    def create_task(self, principal_id: str, task: Task) -> Task:
        ...

    def get_task(self, principal_id: str, task_id: str) -> Task:
        ...

    def list_tasks(
        self,
        principal_id: str,
        *,
        list_id: str | None = None,
        status: TaskStatus | None = None,
    ) -> tuple[Task, ...]:
        ...

    def update_task(self, principal_id: str, task: Task) -> Task:
        ...

    def delete_task(self, principal_id: str, task_id: str) -> None:
        ...

    def move_task(
        self,
        principal_id: str,
        task_id: str,
        *,
        previous_task_id: str | None,
        updated_at: datetime,
    ) -> Task:
        ...
