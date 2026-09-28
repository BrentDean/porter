from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import TypeAlias

from porter.tasks.errors import TaskValidationError

Due: TypeAlias = date | datetime


class TaskStatus(StrEnum):
    """Porter's todo status values, aligned with Home Assistant semantics."""

    NEEDS_ACTION = "needs_action"
    COMPLETED = "completed"


def _require_text(value: str, field: str) -> None:
    if not value.strip():
        raise TaskValidationError(f"{field} must not be empty")


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise TaskValidationError(f"{field} must be timezone-aware")


def _require_due_timezone(value: datetime) -> None:
    _require_aware(value, "due")
    zone_key = getattr(value.tzinfo, "key", None)
    if zone_key:
        return
    if value.utcoffset() == timedelta(0):
        return
    raise TaskValidationError(
        "due datetime must use an IANA timezone or UTC"
    )


@dataclass(frozen=True, slots=True)
class TaskList:
    id: str
    principal_id: str
    name: str
    position: int
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _require_text(self.id, "task list id")
        _require_text(self.principal_id, "principal id")
        _require_text(self.name, "task list name")
        if self.position < 0:
            raise TaskValidationError("task list position must be non-negative")
        _require_aware(self.created_at, "created_at")
        _require_aware(self.updated_at, "updated_at")


@dataclass(frozen=True, slots=True)
class Task:
    id: str
    list_id: str
    summary: str
    description: str | None
    status: TaskStatus
    due: Due | None
    priority: int
    position: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_text(self.id, "task id")
        _require_text(self.list_id, "task list id")
        _require_text(self.summary, "task summary")

        if not isinstance(self.status, TaskStatus):
            raise TaskValidationError("task status must be a TaskStatus value")
        if not 0 <= self.priority <= 9:
            raise TaskValidationError("task priority must be between 0 and 9")
        if self.position < 0:
            raise TaskValidationError("task position must be non-negative")

        if isinstance(self.due, datetime):
            _require_due_timezone(self.due)
        elif self.due is not None and not isinstance(self.due, date):
            raise TaskValidationError("due must be a date, datetime, or None")

        _require_aware(self.created_at, "created_at")
        _require_aware(self.updated_at, "updated_at")

        if self.completed_at is not None:
            _require_aware(self.completed_at, "completed_at")
            if self.status is not TaskStatus.COMPLETED:
                raise TaskValidationError(
                    "completed_at requires completed status"
                )
