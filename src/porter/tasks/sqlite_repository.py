from __future__ import annotations

import sqlite3
import unicodedata
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from porter.storage.database import Database
from porter.tasks.errors import (
    InvalidTaskMoveError,
    TaskListAlreadyExistsError,
    TaskListNotFoundError,
    TaskNotFoundError,
    TaskValidationError,
)
from porter.tasks.models import Due, Task, TaskList, TaskStatus


def _normalize_list_name(name: str) -> str:
    return unicodedata.normalize("NFKC", name.strip()).casefold()


def _to_utc_iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise TaskValidationError("datetime must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def _due_timezone_name(value: datetime) -> str:
    key = getattr(value.tzinfo, "key", None)
    if key:
        return str(key)
    if value.utcoffset() == timedelta(0):
        return "UTC"
    raise TaskValidationError(
        "due datetime must use an IANA timezone or UTC"
    )


def _encode_due(
    due: Due | None,
) -> tuple[str | None, str | None, str | None]:
    if due is None:
        return None, None, None
    if isinstance(due, datetime):
        return (
            None,
            _to_utc_iso(due),
            _due_timezone_name(due),
        )
    return due.isoformat(), None, None


def _decode_due(row: sqlite3.Row) -> Due | None:
    due_date = row["due_date"]
    if due_date is not None:
        return date.fromisoformat(due_date)

    due_at_utc = row["due_at_utc"]
    if due_at_utc is None:
        return None

    value = datetime.fromisoformat(due_at_utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise TaskValidationError("stored due datetime is not timezone-aware")

    zone_name = row["due_timezone"]
    zone = UTC if zone_name == "UTC" else ZoneInfo(zone_name)
    return value.astimezone(zone)


def _decode_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    decoded = datetime.fromisoformat(value)
    if decoded.tzinfo is None or decoded.utcoffset() is None:
        raise TaskValidationError("stored timestamp is not timezone-aware")
    return decoded.astimezone(UTC)


def _task_list_from_row(row: sqlite3.Row) -> TaskList:
    created_at = _decode_timestamp(row["created_at"])
    updated_at = _decode_timestamp(row["updated_at"])
    if created_at is None or updated_at is None:
        raise TaskValidationError("stored task-list timestamps are missing")

    return TaskList(
        id=row["id"],
        principal_id=row["principal_id"],
        name=row["name"],
        position=int(row["position"]),
        created_at=created_at,
        updated_at=updated_at,
    )


def _task_from_row(row: sqlite3.Row) -> Task:
    created_at = _decode_timestamp(row["created_at"])
    updated_at = _decode_timestamp(row["updated_at"])
    if created_at is None or updated_at is None:
        raise TaskValidationError("stored task timestamps are missing")

    return Task(
        id=row["id"],
        list_id=row["list_id"],
        summary=row["summary"],
        description=row["description"],
        status=TaskStatus(row["status"]),
        due=_decode_due(row),
        priority=int(row["priority"]),
        position=int(row["position"]),
        created_at=created_at,
        updated_at=updated_at,
        completed_at=_decode_timestamp(row["completed_at"]),
    )


class SqliteTaskRepository:
    """SQLite implementation of Porter's task persistence boundary."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def create_list(self, task_list: TaskList) -> TaskList:
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT COALESCE(MAX(position), -1) + 1
                FROM task_lists
                WHERE principal_id = ?
                """,
                (task_list.principal_id,),
            ).fetchone()
            position = int(row[0]) if row is not None else 0
            persisted = replace(task_list, position=position)

            try:
                connection.execute(
                    """
                    INSERT INTO task_lists (
                        id,
                        principal_id,
                        name,
                        name_key,
                        position,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        persisted.id,
                        persisted.principal_id,
                        persisted.name,
                        _normalize_list_name(persisted.name),
                        persisted.position,
                        _to_utc_iso(persisted.created_at),
                        _to_utc_iso(persisted.updated_at),
                    ),
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                if (
                    "task_lists.principal_id, task_lists.name_key" in str(exc)
                    or "task_lists.principal_id" in str(exc)
                    and "task_lists.name_key" in str(exc)
                ):
                    raise TaskListAlreadyExistsError(
                        f"task list already exists: {persisted.name}"
                    ) from exc
                raise

        return persisted

    def get_list(self, principal_id: str, list_id: str) -> TaskList:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM task_lists
                WHERE principal_id = ?
                  AND id = ?
                """,
                (principal_id, list_id),
            ).fetchone()

        if row is None:
            raise TaskListNotFoundError(f"task list not found: {list_id}")
        return _task_list_from_row(row)

    def get_list_by_name(self, principal_id: str, name: str) -> TaskList:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM task_lists
                WHERE principal_id = ?
                  AND name_key = ?
                """,
                (principal_id, _normalize_list_name(name)),
            ).fetchone()

        if row is None:
            raise TaskListNotFoundError(f"task list not found: {name}")
        return _task_list_from_row(row)

    def list_lists(self, principal_id: str) -> tuple[TaskList, ...]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM task_lists
                WHERE principal_id = ?
                ORDER BY position, created_at, id
                """,
                (principal_id,),
            ).fetchall()

        return tuple(_task_list_from_row(row) for row in rows)

    def rename_list(
        self,
        principal_id: str,
        list_id: str,
        *,
        name: str,
        updated_at: datetime,
    ) -> TaskList:
        with self._database.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    UPDATE task_lists
                    SET name = ?,
                        name_key = ?,
                        updated_at = ?
                    WHERE principal_id = ?
                      AND id = ?
                    """,
                    (
                        name,
                        _normalize_list_name(name),
                        _to_utc_iso(updated_at),
                        principal_id,
                        list_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise TaskListNotFoundError(
                        f"task list not found: {list_id}"
                    )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                if (
                    "task_lists.principal_id, task_lists.name_key" in str(exc)
                    or "task_lists.principal_id" in str(exc)
                    and "task_lists.name_key" in str(exc)
                ):
                    raise TaskListAlreadyExistsError(
                        f"task list already exists: {name}"
                    ) from exc
                raise

        return self.get_list(principal_id, list_id)

    def create_task(self, principal_id: str, task: Task) -> Task:
        due_date, due_at_utc, due_timezone = _encode_due(task.due)

        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            list_row = connection.execute(
                """
                SELECT 1
                FROM task_lists
                WHERE principal_id = ?
                  AND id = ?
                """,
                (principal_id, task.list_id),
            ).fetchone()
            if list_row is None:
                connection.rollback()
                raise TaskListNotFoundError(
                    f"task list not found: {task.list_id}"
                )

            row = connection.execute(
                """
                SELECT COALESCE(MAX(position), -1) + 1
                FROM tasks
                WHERE list_id = ?
                """,
                (task.list_id,),
            ).fetchone()
            position = int(row[0]) if row is not None else 0
            persisted = replace(task, position=position)

            connection.execute(
                """
                INSERT INTO tasks (
                    id,
                    list_id,
                    summary,
                    description,
                    status,
                    priority,
                    due_date,
                    due_at_utc,
                    due_timezone,
                    position,
                    created_at,
                    updated_at,
                    completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    persisted.id,
                    persisted.list_id,
                    persisted.summary,
                    persisted.description,
                    persisted.status.value,
                    persisted.priority,
                    due_date,
                    due_at_utc,
                    due_timezone,
                    persisted.position,
                    _to_utc_iso(persisted.created_at),
                    _to_utc_iso(persisted.updated_at),
                    (
                        _to_utc_iso(persisted.completed_at)
                        if persisted.completed_at is not None
                        else None
                    ),
                ),
            )
            connection.commit()

        return persisted

    def get_task(self, principal_id: str, task_id: str) -> Task:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT tasks.*
                FROM tasks
                JOIN task_lists
                  ON task_lists.id = tasks.list_id
                WHERE task_lists.principal_id = ?
                  AND tasks.id = ?
                """,
                (principal_id, task_id),
            ).fetchone()

        if row is None:
            raise TaskNotFoundError(f"task not found: {task_id}")
        return _task_from_row(row)

    def list_tasks(
        self,
        principal_id: str,
        *,
        list_id: str | None = None,
        status: TaskStatus | None = None,
    ) -> tuple[Task, ...]:
        clauses = ["task_lists.principal_id = ?"]
        parameters: list[str] = [principal_id]

        if list_id is not None:
            clauses.append("tasks.list_id = ?")
            parameters.append(list_id)
        if status is not None:
            clauses.append("tasks.status = ?")
            parameters.append(status.value)

        where = f"WHERE {' AND '.join(clauses)}"
        ordering = (
            "tasks.position, tasks.created_at, tasks.id"
            if list_id is not None
            else "task_lists.position, tasks.position, tasks.created_at, tasks.id"
        )

        with self._database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT tasks.*
                FROM tasks
                JOIN task_lists
                  ON task_lists.id = tasks.list_id
                {where}
                ORDER BY {ordering}
                """,
                parameters,
            ).fetchall()

        return tuple(_task_from_row(row) for row in rows)

    def update_task(self, principal_id: str, task: Task) -> Task:
        due_date, due_at_utc, due_timezone = _encode_due(task.due)

        with self._database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE tasks
                SET summary = ?,
                    description = ?,
                    status = ?,
                    priority = ?,
                    due_date = ?,
                    due_at_utc = ?,
                    due_timezone = ?,
                    updated_at = ?,
                    completed_at = ?
                WHERE id = ?
                  AND EXISTS (
                      SELECT 1
                      FROM task_lists
                      WHERE task_lists.id = tasks.list_id
                        AND task_lists.principal_id = ?
                  )
                """,
                (
                    task.summary,
                    task.description,
                    task.status.value,
                    task.priority,
                    due_date,
                    due_at_utc,
                    due_timezone,
                    _to_utc_iso(task.updated_at),
                    (
                        _to_utc_iso(task.completed_at)
                        if task.completed_at is not None
                        else None
                    ),
                    task.id,
                    principal_id,
                ),
            )
            if cursor.rowcount != 1:
                raise TaskNotFoundError(f"task not found: {task.id}")
            connection.commit()

        return self.get_task(principal_id, task.id)

    def delete_task(self, principal_id: str, task_id: str) -> None:
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT tasks.list_id, tasks.position
                FROM tasks
                JOIN task_lists
                  ON task_lists.id = tasks.list_id
                WHERE task_lists.principal_id = ?
                  AND tasks.id = ?
                """,
                (principal_id, task_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise TaskNotFoundError(f"task not found: {task_id}")

            connection.execute(
                "DELETE FROM tasks WHERE id = ?",
                (task_id,),
            )
            connection.execute(
                """
                UPDATE tasks
                SET position = position - 1
                WHERE list_id = ?
                  AND position > ?
                """,
                (row["list_id"], row["position"]),
            )
            connection.commit()

    def move_task(
        self,
        principal_id: str,
        task_id: str,
        *,
        previous_task_id: str | None,
        updated_at: datetime,
    ) -> Task:
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            source = connection.execute(
                """
                SELECT tasks.list_id, tasks.position
                FROM tasks
                JOIN task_lists
                  ON task_lists.id = tasks.list_id
                WHERE task_lists.principal_id = ?
                  AND tasks.id = ?
                """,
                (principal_id, task_id),
            ).fetchone()
            if source is None:
                connection.rollback()
                raise TaskNotFoundError(f"task not found: {task_id}")

            source_list_id = source["list_id"]
            source_position = int(source["position"])

            if previous_task_id == task_id:
                connection.rollback()
                return self.get_task(principal_id, task_id)

            if previous_task_id is None:
                destination = 0
            else:
                previous = connection.execute(
                    """
                    SELECT tasks.list_id, tasks.position
                    FROM tasks
                    JOIN task_lists
                      ON task_lists.id = tasks.list_id
                    WHERE task_lists.principal_id = ?
                      AND tasks.id = ?
                    """,
                    (principal_id, previous_task_id),
                ).fetchone()
                if previous is None:
                    connection.rollback()
                    raise TaskNotFoundError(
                        f"task not found: {previous_task_id}"
                    )
                if previous["list_id"] != source_list_id:
                    connection.rollback()
                    raise InvalidTaskMoveError(
                        "tasks must remain within the same task list"
                    )

                previous_position = int(previous["position"])
                destination = (
                    previous_position
                    if source_position < previous_position
                    else previous_position + 1
                )

            if destination == source_position:
                connection.rollback()
                return self.get_task(principal_id, task_id)

            if destination < source_position:
                connection.execute(
                    """
                    UPDATE tasks
                    SET position = position + 1
                    WHERE list_id = ?
                      AND position >= ?
                      AND position < ?
                    """,
                    (
                        source_list_id,
                        destination,
                        source_position,
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE tasks
                    SET position = position - 1
                    WHERE list_id = ?
                      AND position > ?
                      AND position <= ?
                    """,
                    (
                        source_list_id,
                        source_position,
                        destination,
                    ),
                )

            connection.execute(
                """
                UPDATE tasks
                SET position = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    destination,
                    _to_utc_iso(updated_at),
                    task_id,
                ),
            )
            connection.commit()

        return self.get_task(principal_id, task_id)
