from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from porter.reminders.errors import (
    ReminderNotFoundError,
    ReminderStateError,
    ReminderValidationError,
)
from porter.reminders.models import Reminder, ReminderKind, ReminderStatus
from porter.storage.database import Database


def _to_utc_iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ReminderValidationError("datetime must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def _timezone_name(value: datetime) -> str:
    key = getattr(value.tzinfo, "key", None)
    if key:
        return str(key)
    if value.utcoffset() == timedelta(0):
        return "UTC"
    raise ReminderValidationError(
        "trigger_at must use an IANA timezone or UTC"
    )


def _decode_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    decoded = datetime.fromisoformat(value)
    if decoded.tzinfo is None or decoded.utcoffset() is None:
        raise ReminderValidationError("stored timestamp is not timezone-aware")
    return decoded.astimezone(UTC)


def _decode_trigger(row: sqlite3.Row) -> datetime:
    value = datetime.fromisoformat(row["trigger_at_utc"])
    if value.tzinfo is None or value.utcoffset() is None:
        raise ReminderValidationError(
            "stored reminder trigger is not timezone-aware"
        )

    zone_name = row["trigger_timezone"]
    zone = UTC if zone_name == "UTC" else ZoneInfo(zone_name)
    return value.astimezone(zone)


def _reminder_from_row(row: sqlite3.Row) -> Reminder:
    created_at = _decode_timestamp(row["created_at"])
    updated_at = _decode_timestamp(row["updated_at"])
    if created_at is None or updated_at is None:
        raise ReminderValidationError("stored reminder timestamps are missing")

    return Reminder(
        id=row["id"],
        principal_id=row["principal_id"],
        message=row["message"],
        trigger_at=_decode_trigger(row),
        status=ReminderStatus(row["status"]),
        created_at=created_at,
        updated_at=updated_at,
        delivered_at=_decode_timestamp(row["delivered_at"]),
        cancelled_at=_decode_timestamp(row["cancelled_at"]),
        delivery_attempt_count=int(row["delivery_attempt_count"]),
        next_delivery_attempt_at=_decode_timestamp(
            row["next_delivery_attempt_at_utc"]
        ),
        delivery_claimed_at=_decode_timestamp(row["delivery_claimed_at_utc"]),
        kind=ReminderKind(row["kind"]),
        duration_seconds=row["duration_seconds"],
    )


def _raise_write_conflict(
    connection: sqlite3.Connection,
    principal_id: str,
    reminder_id: str,
    expected_status: ReminderStatus | None,
    expected_claimed_at: datetime | None = None,
) -> None:
    row = connection.execute(
        """
        SELECT status, delivery_claimed_at_utc
        FROM reminders
        WHERE principal_id = ?
          AND id = ?
        """,
        (principal_id, reminder_id),
    ).fetchone()
    if row is None:
        raise ReminderNotFoundError(f"reminder not found: {reminder_id}")
    if expected_status is not None and row["status"] != expected_status.value:
        raise ReminderStateError(
            "reminder state changed concurrently: "
            f"expected {expected_status.value}, found {row['status']}"
        )
    if expected_claimed_at is not None:
        persisted_claim = _decode_timestamp(row["delivery_claimed_at_utc"])
        if persisted_claim != expected_claimed_at.astimezone(UTC):
            raise ReminderStateError("reminder delivery claim changed concurrently")
    raise ReminderStateError("reminder write did not update exactly one row")


class SqliteReminderRepository:
    """SQLite implementation of Porter's reminder persistence boundary."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def create_reminder(self, reminder: Reminder) -> Reminder:
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO reminders (
                    id,
                    principal_id,
                    message,
                    status,
                    trigger_at_utc,
                    trigger_timezone,
                    created_at,
                    updated_at,
                    delivered_at,
                    cancelled_at,
                    delivery_attempt_count,
                    next_delivery_attempt_at_utc,
                    delivery_claimed_at_utc,
                    kind,
                    duration_seconds
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reminder.id,
                    reminder.principal_id,
                    reminder.message,
                    reminder.status.value,
                    _to_utc_iso(reminder.trigger_at),
                    _timezone_name(reminder.trigger_at),
                    _to_utc_iso(reminder.created_at),
                    _to_utc_iso(reminder.updated_at),
                    (
                        _to_utc_iso(reminder.delivered_at)
                        if reminder.delivered_at is not None
                        else None
                    ),
                    (
                        _to_utc_iso(reminder.cancelled_at)
                        if reminder.cancelled_at is not None
                        else None
                    ),
                    reminder.delivery_attempt_count,
                    (
                        _to_utc_iso(reminder.next_delivery_attempt_at)
                        if reminder.next_delivery_attempt_at is not None
                        else None
                    ),
                    (
                        _to_utc_iso(reminder.delivery_claimed_at)
                        if reminder.delivery_claimed_at is not None
                        else None
                    ),
                    reminder.kind.value,
                    reminder.duration_seconds,
                ),
            )
            connection.commit()

        return reminder

    def get_reminder(self, principal_id: str, reminder_id: str) -> Reminder:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM reminders
                WHERE principal_id = ?
                  AND id = ?
                """,
                (principal_id, reminder_id),
            ).fetchone()

        if row is None:
            raise ReminderNotFoundError(
                f"reminder not found: {reminder_id}"
            )
        return _reminder_from_row(row)

    def list_reminders(
        self,
        principal_id: str,
        *,
        status: ReminderStatus | None = None,
    ) -> tuple[Reminder, ...]:
        with self._database.connect() as connection:
            if status is None:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM reminders
                    WHERE principal_id = ?
                    ORDER BY trigger_at_utc, created_at, id
                    """,
                    (principal_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM reminders
                    WHERE principal_id = ?
                      AND status = ?
                    ORDER BY trigger_at_utc, created_at, id
                    """,
                    (principal_id, status.value),
                ).fetchall()

        return tuple(_reminder_from_row(row) for row in rows)

    def list_due_reminders(
        self,
        principal_id: str,
        *,
        as_of: datetime,
    ) -> tuple[Reminder, ...]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM reminders
                WHERE principal_id = ?
                  AND status = 'scheduled'
                  AND trigger_at_utc <= ?
                ORDER BY trigger_at_utc, created_at, id
                """,
                (principal_id, _to_utc_iso(as_of)),
            ).fetchall()

        return tuple(_reminder_from_row(row) for row in rows)

    def list_all_due_reminders(
        self,
        *,
        as_of: datetime,
    ) -> tuple[Reminder, ...]:
        as_of_utc = _to_utc_iso(as_of)
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM reminders
                WHERE status = 'scheduled'
                  AND trigger_at_utc <= ?
                  AND (
                      next_delivery_attempt_at_utc IS NULL
                      OR next_delivery_attempt_at_utc <= ?
                  )
                ORDER BY trigger_at_utc, created_at, id
                """,
                (as_of_utc, as_of_utc),
            ).fetchall()

        return tuple(_reminder_from_row(row) for row in rows)

    def claim_due_reminder(
        self,
        principal_id: str,
        reminder_id: str,
        *,
        claimed_at: datetime,
    ) -> Reminder | None:
        claimed_at_utc = _to_utc_iso(claimed_at)
        with self._database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE reminders
                SET status = 'delivering',
                    updated_at = ?,
                    delivery_claimed_at_utc = ?,
                    next_delivery_attempt_at_utc = NULL
                WHERE principal_id = ?
                  AND id = ?
                  AND status = 'scheduled'
                  AND trigger_at_utc <= ?
                  AND (
                      next_delivery_attempt_at_utc IS NULL
                      OR next_delivery_attempt_at_utc <= ?
                  )
                """,
                (
                    claimed_at_utc,
                    claimed_at_utc,
                    principal_id,
                    reminder_id,
                    claimed_at_utc,
                    claimed_at_utc,
                ),
            )
            if cursor.rowcount != 1:
                connection.commit()
                return None

            row = connection.execute(
                """
                SELECT *
                FROM reminders
                WHERE principal_id = ?
                  AND id = ?
                """,
                (principal_id, reminder_id),
            ).fetchone()
            connection.commit()

        if row is None:
            raise ReminderNotFoundError(f"reminder not found: {reminder_id}")
        return _reminder_from_row(row)

    def recover_stale_delivery_claims(
        self,
        *,
        stale_before: datetime,
        retry_at: datetime,
    ) -> int:
        stale_before_utc = _to_utc_iso(stale_before)
        retry_at_utc = _to_utc_iso(retry_at)
        with self._database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE reminders
                SET status = 'scheduled',
                    updated_at = ?,
                    delivery_claimed_at_utc = NULL,
                    next_delivery_attempt_at_utc = CASE
                        WHEN delivery_attempt_count > 0 THEN ?
                        ELSE NULL
                    END
                WHERE status = 'delivering'
                  AND delivery_claimed_at_utc <= ?
                """,
                (retry_at_utc, retry_at_utc, stale_before_utc),
            )
            recovered = cursor.rowcount
            connection.commit()

        return recovered

    def update_reminder(
        self,
        principal_id: str,
        reminder: Reminder,
        *,
        expected_status: ReminderStatus | None = None,
        expected_claimed_at: datetime | None = None,
    ) -> Reminder:
        if reminder.principal_id != principal_id:
            raise ReminderNotFoundError(
                f"reminder not found: {reminder.id}"
            )

        where = "WHERE principal_id = ? AND id = ?"
        where_values: list[object] = [principal_id, reminder.id]
        if expected_status is not None:
            where += " AND status = ?"
            where_values.append(expected_status.value)
        if expected_claimed_at is not None:
            where += " AND delivery_claimed_at_utc = ?"
            where_values.append(_to_utc_iso(expected_claimed_at))

        with self._database.connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE reminders
                SET message = ?,
                    status = ?,
                    trigger_at_utc = ?,
                    trigger_timezone = ?,
                    updated_at = ?,
                    delivered_at = ?,
                    cancelled_at = ?,
                    delivery_attempt_count = ?,
                    next_delivery_attempt_at_utc = ?,
                    delivery_claimed_at_utc = ?,
                    kind = ?,
                    duration_seconds = ?
                {where}
                """,
                (
                    reminder.message,
                    reminder.status.value,
                    _to_utc_iso(reminder.trigger_at),
                    _timezone_name(reminder.trigger_at),
                    _to_utc_iso(reminder.updated_at),
                    (
                        _to_utc_iso(reminder.delivered_at)
                        if reminder.delivered_at is not None
                        else None
                    ),
                    (
                        _to_utc_iso(reminder.cancelled_at)
                        if reminder.cancelled_at is not None
                        else None
                    ),
                    reminder.delivery_attempt_count,
                    (
                        _to_utc_iso(reminder.next_delivery_attempt_at)
                        if reminder.next_delivery_attempt_at is not None
                        else None
                    ),
                    (
                        _to_utc_iso(reminder.delivery_claimed_at)
                        if reminder.delivery_claimed_at is not None
                        else None
                    ),
                    reminder.kind.value,
                    reminder.duration_seconds,
                    *where_values,
                ),
            )
            if cursor.rowcount != 1:
                _raise_write_conflict(
                    connection,
                    principal_id,
                    reminder.id,
                    expected_status,
                    expected_claimed_at,
                )
            connection.commit()

        return reminder

    def delete_reminder(
        self,
        principal_id: str,
        reminder_id: str,
        *,
        expected_status: ReminderStatus | None = None,
    ) -> None:
        where = "WHERE principal_id = ? AND id = ?"
        values: list[object] = [principal_id, reminder_id]
        if expected_status is not None:
            where += " AND status = ?"
            values.append(expected_status.value)

        with self._database.connect() as connection:
            cursor = connection.execute(
                f"DELETE FROM reminders {where}",
                tuple(values),
            )
            if cursor.rowcount != 1:
                _raise_write_conflict(
                    connection,
                    principal_id,
                    reminder_id,
                    expected_status,
                )
            connection.commit()

    def delete_terminal_reminders(self, principal_id: str) -> int:
        with self._database.connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM reminders
                WHERE principal_id = ?
                  AND status IN ('delivered', 'cancelled')
                """,
                (principal_id,),
            )
            deleted = cursor.rowcount
            connection.commit()

        return deleted
