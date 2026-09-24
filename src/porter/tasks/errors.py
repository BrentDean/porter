from __future__ import annotations


class TaskError(Exception):
    """Base error for Porter task operations."""


class TaskValidationError(TaskError, ValueError):
    """Raised when task data violates the Porter task contract."""


class TaskNotFoundError(TaskError):
    """Raised when a task ID does not exist."""


class TaskListNotFoundError(TaskError):
    """Raised when a task-list ID or name does not exist."""


class TaskListAlreadyExistsError(TaskError):
    """Raised when a task-list name already exists case-insensitively."""


class InvalidTaskMoveError(TaskError):
    """Raised when a task cannot be moved to the requested position."""
