from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from porter.core.clock import utc_now
from porter.tasks.models import Task, TaskList, TaskStatus
from porter.tasks.service import TaskService


@dataclass(frozen=True, slots=True)
class PlannerItem:
    """Task plus the list metadata needed by planner consumers."""

    task: Task
    task_list: TaskList

    def __post_init__(self) -> None:
        if self.task.list_id != self.task_list.id:
            raise ValueError("planner item task must belong to task_list")


@dataclass(frozen=True, slots=True)
class PlannerSnapshot:
    """Immutable, principal-scoped planner read model."""

    principal_id: str
    as_of: datetime
    timezone: str
    upcoming_days: int
    unscheduled: tuple[PlannerItem, ...]
    overdue: tuple[PlannerItem, ...]
    today: tuple[PlannerItem, ...]
    upcoming: tuple[PlannerItem, ...]
    completed: tuple[PlannerItem, ...]

    def __post_init__(self) -> None:
        if not self.principal_id.strip():
            raise ValueError("planner principal_id must not be empty")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("planner as_of must be timezone-aware")
        if not self.timezone.strip():
            raise ValueError("planner timezone must not be empty")
        if self.upcoming_days < 0:
            raise ValueError("planner upcoming_days must be non-negative")


def _priority_rank(priority: int) -> int:
    return 10 if priority == 0 else priority


def _effective_deadline(task: Task, timezone: ZoneInfo) -> datetime:
    due = task.due
    if due is None:
        raise ValueError("effective deadline requires a task due value")
    if isinstance(due, datetime):
        return due.astimezone(UTC)

    end_of_due_day = datetime.combine(
        due + timedelta(days=1),
        time.min,
        tzinfo=timezone,
    )
    return end_of_due_day.astimezone(UTC)


def _deadline_sort_key(
    item: PlannerItem,
    timezone: ZoneInfo,
) -> tuple[datetime, int, int, int, str]:
    return (
        _effective_deadline(item.task, timezone),
        _priority_rank(item.task.priority),
        item.task_list.position,
        item.task.position,
        item.task.id,
    )


def _unscheduled_sort_key(
    item: PlannerItem,
) -> tuple[int, int, int, str]:
    return (
        _priority_rank(item.task.priority),
        item.task_list.position,
        item.task.position,
        item.task.id,
    )


def _completed_sort_key(
    item: PlannerItem,
) -> tuple[int, float, float, str]:
    task = item.task
    completed_at = task.completed_at
    primary = completed_at if completed_at is not None else task.updated_at
    return (
        0 if completed_at is not None else 1,
        -primary.timestamp(),
        -task.updated_at.timestamp(),
        task.id,
    )


class PlannerService:
    """Build planner views from Porter's authoritative task service."""

    def __init__(
        self,
        task_service: TaskService,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._task_service = task_service
        self._clock = clock or utc_now

    def snapshot(
        self,
        principal_id: str,
        *,
        timezone: ZoneInfo,
        upcoming_days: int = 7,
    ) -> PlannerSnapshot:
        principal_id = principal_id.strip()
        if not principal_id:
            raise ValueError("planner principal_id must not be empty")
        if not isinstance(timezone, ZoneInfo):
            raise ValueError("planner timezone must be a ZoneInfo")
        if upcoming_days < 0:
            raise ValueError("planner upcoming_days must be non-negative")

        now = self._now()
        local_now = now.astimezone(timezone)
        today_date = local_now.date()
        upcoming_through = today_date + timedelta(days=upcoming_days)

        task_lists = self._task_service.list_lists(principal_id)
        lists_by_id = {task_list.id: task_list for task_list in task_lists}

        unscheduled: list[PlannerItem] = []
        overdue: list[PlannerItem] = []
        today: list[PlannerItem] = []
        upcoming: list[PlannerItem] = []
        completed: list[PlannerItem] = []

        for task in self._task_service.list_tasks(principal_id):
            task_list = self._task_list_for(task, lists_by_id)
            item = PlannerItem(task=task, task_list=task_list)

            if task.status is TaskStatus.COMPLETED:
                completed.append(item)
                continue

            due = task.due
            if due is None:
                unscheduled.append(item)
                continue

            if isinstance(due, datetime):
                due_utc = due.astimezone(UTC)
                local_due_date = due.astimezone(timezone).date()
                if due_utc < now:
                    overdue.append(item)
                elif local_due_date == today_date:
                    today.append(item)
                elif today_date < local_due_date <= upcoming_through:
                    upcoming.append(item)
                continue

            if due < today_date:
                overdue.append(item)
            elif due == today_date:
                today.append(item)
            elif today_date < due <= upcoming_through:
                upcoming.append(item)

        unscheduled.sort(key=_unscheduled_sort_key)
        overdue.sort(key=lambda item: _deadline_sort_key(item, timezone))
        today.sort(key=lambda item: _deadline_sort_key(item, timezone))
        upcoming.sort(key=lambda item: _deadline_sort_key(item, timezone))
        completed.sort(key=_completed_sort_key)

        return PlannerSnapshot(
            principal_id=principal_id,
            as_of=local_now,
            timezone=timezone.key,
            upcoming_days=upcoming_days,
            unscheduled=tuple(unscheduled),
            overdue=tuple(overdue),
            today=tuple(today),
            upcoming=tuple(upcoming),
            completed=tuple(completed),
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("planner clock must return a timezone-aware datetime")
        return value.astimezone(UTC)

    @staticmethod
    def _task_list_for(
        task: Task,
        lists_by_id: dict[str, TaskList],
    ) -> TaskList:
        task_list = lists_by_id.get(task.list_id)
        if task_list is None:
            raise RuntimeError(
                f"task references unavailable task list: {task.list_id}"
            )
        return task_list


__all__ = ["PlannerItem", "PlannerService", "PlannerSnapshot"]
