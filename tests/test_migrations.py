import sqlite3
from pathlib import Path

import pytest

from porter.storage.database import Database
from porter.storage.migrations import MigrationRunner, load_migrations


def test_packaged_migrations_are_ordered() -> None:
    migrations = load_migrations()

    assert tuple(migration.version for migration in migrations) == (
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
    )
    assert tuple(migration.name for migration in migrations) == (
        "initial",
        "telemetry",
        "execution_paths_and_tools",
        "tasks",
        "task_principals",
        "reminders",
        "reminder_delivery_retry",
        "reminder_delivery_claims",
        "training_corpus",
        "training_labels",
        "training_groups",
        "memory",
        "request_latency",
        "reminder_timers",
    )


def test_migrations_apply_once(tmp_path: Path) -> None:
    database = Database(tmp_path / "porter.db")
    runner = MigrationRunner(database)

    assert runner.current_version() == 0
    assert runner.apply_all() == (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14)
    assert runner.current_version() == 14
    assert runner.apply_all() == ()

    with database.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM schema_migrations"
        ).fetchone()

    assert count is not None
    assert count[0] == 14


def test_task_principal_migration_preserves_existing_data(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "porter.db")
    migrations = load_migrations()

    with database.connect() as connection:
        for migration in migrations[:4]:
            connection.executescript(migration.sql)

        connection.execute(
            """
            INSERT INTO task_lists (
                id,
                name,
                name_key,
                position,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-list",
                "Shopping",
                "shopping",
                0,
                "2026-08-15T12:00:00+00:00",
                "2026-08-15T12:00:00+00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO tasks (
                id,
                list_id,
                summary,
                status,
                priority,
                position,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-task",
                "legacy-list",
                "Buy milk",
                "needs_action",
                0,
                0,
                "2026-08-15T12:00:00+00:00",
                "2026-08-15T12:00:00+00:00",
            ),
        )
        connection.commit()

        connection.executescript(migrations[4].sql)

        task_list = connection.execute(
            """
            SELECT principal_id, name
            FROM task_lists
            WHERE id = ?
            """,
            ("legacy-list",),
        ).fetchone()
        task = connection.execute(
            "SELECT summary FROM tasks WHERE id = ?",
            ("legacy-task",),
        ).fetchone()

    assert task_list is not None
    assert tuple(task_list) == ("local-user", "Shopping")
    assert task is not None
    assert task["summary"] == "Buy milk"


def test_reminder_retry_migration_preserves_existing_data(tmp_path: Path) -> None:
    database = Database(tmp_path / "porter.db")
    migrations = load_migrations()

    with database.connect() as connection:
        for migration in migrations[:6]:
            connection.executescript(migration.sql)

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
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-reminder",
                "alice",
                "Existing reminder",
                "scheduled",
                "2026-08-15T12:00:00+00:00",
                "UTC",
                "2026-08-15T11:00:00+00:00",
                "2026-08-15T11:00:00+00:00",
            ),
        )
        connection.commit()

        connection.executescript(migrations[6].sql)

        row = connection.execute(
            """
            SELECT message, delivery_attempt_count, next_delivery_attempt_at_utc
            FROM reminders
            WHERE id = ?
            """,
            ("legacy-reminder",),
        ).fetchone()

    assert row is not None
    assert tuple(row) == ("Existing reminder", 0, None)


def test_reminder_claim_migration_preserves_existing_data(tmp_path: Path) -> None:
    database = Database(tmp_path / "porter.db")
    migrations = load_migrations()

    with database.connect() as connection:
        for migration in migrations[:7]:
            connection.executescript(migration.sql)

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
                delivery_attempt_count,
                next_delivery_attempt_at_utc
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-reminder",
                "alice",
                "Existing retry reminder",
                "scheduled",
                "2026-08-15T12:00:00+00:00",
                "UTC",
                "2026-08-15T11:00:00+00:00",
                "2026-08-15T11:30:00+00:00",
                2,
                "2026-08-15T12:05:00+00:00",
            ),
        )
        connection.commit()

        connection.executescript(migrations[7].sql)

        row = connection.execute(
            """
            SELECT
                message,
                status,
                delivery_attempt_count,
                next_delivery_attempt_at_utc,
                delivery_claimed_at_utc
            FROM reminders
            WHERE id = ?
            """,
            ("legacy-reminder",),
        ).fetchone()
        indexes = {
            item["name"]
            for item in connection.execute("PRAGMA index_list(reminders)")
        }

    assert row is not None
    assert tuple(row) == (
        "Existing retry reminder",
        "scheduled",
        2,
        "2026-08-15T12:05:00+00:00",
        None,
    )
    assert "idx_reminders_delivery_claim" in indexes


def test_timer_migration_preserves_existing_reminders(tmp_path: Path) -> None:
    database = Database(tmp_path / "porter.db")
    migrations = load_migrations()
    with database.connect() as connection:
        for migration in migrations[:13]:
            connection.executescript(migration.sql)

        connection.execute(
            """
            INSERT INTO reminders (
                id, principal_id, message, status, trigger_at_utc,
                trigger_timezone, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-reminder", "alice", "Keep me", "scheduled",
                "2026-08-15T12:00:00+00:00", "UTC",
                "2026-08-15T11:00:00+00:00",
                "2026-08-15T11:00:00+00:00",
            ),
        )
        connection.commit()
        connection.executescript(migrations[13].sql)
        row = connection.execute(
            "SELECT kind, duration_seconds FROM reminders WHERE id = ?",
            ("legacy-reminder",),
        ).fetchone()

    assert row is not None
    assert tuple(row) == ("reminder", None)


def test_telemetry_tables_are_created(tmp_path: Path) -> None:
    database = Database(tmp_path / "porter.db")
    MigrationRunner(database).apply_all()

    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            ORDER BY name
            """
        ).fetchall()

    names = {row["name"] for row in rows}

    assert "requests" in names
    assert "provider_attempts" in names


def test_task_tables_are_created(tmp_path: Path) -> None:
    database = Database(tmp_path / "porter.db")
    MigrationRunner(database).apply_all()

    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            ORDER BY name
            """
        ).fetchall()
        columns = connection.execute(
            "PRAGMA table_info(task_lists)"
        ).fetchall()

    names = {row["name"] for row in rows}
    column_names = {row["name"] for row in columns}

    assert "task_lists" in names
    assert "tasks" in names
    assert "principal_id" in column_names


def test_memory_table_is_created(tmp_path: Path) -> None:
    database = Database(tmp_path / "porter.db")
    MigrationRunner(database).apply_all()

    with database.connect() as connection:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(memory_facts)")
        }
        indexes = {
            row["name"]
            for row in connection.execute("PRAGMA index_list(memory_facts)")
        }

    assert {
        "id",
        "principal_id",
        "content",
        "content_key",
        "provenance_source",
        "provenance_session_id",
        "provenance_request_id",
        "created_at",
        "updated_at",
    } <= columns
    assert "idx_memory_facts_principal_updated" in indexes


def test_provider_attempt_requires_existing_request(tmp_path: Path) -> None:
    database = Database(tmp_path / "porter.db")
    MigrationRunner(database).apply_all()

    with database.connect() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            connection.execute(
                """
                INSERT INTO provider_attempts (
                    request_id,
                    attempt_index,
                    provider,
                    model
                )
                VALUES (?, ?, ?, ?)
                """,
                ("missing-request", 1, "local", "test-model"),
            )


def test_provider_attempt_index_is_unique_per_request(tmp_path: Path) -> None:
    database = Database(tmp_path / "porter.db")
    MigrationRunner(database).apply_all()

    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO requests (
                request_id,
                principal_id,
                source,
                task_type,
                privacy_class,
                allow_cloud
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "request-1",
                "test-user",
                "cli",
                "general",
                "local_only",
                0,
            ),
        )

        connection.execute(
            """
            INSERT INTO provider_attempts (
                request_id,
                attempt_index,
                provider,
                model
            )
            VALUES (?, ?, ?, ?)
            """,
            ("request-1", 1, "local", "test-model"),
        )

        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            connection.execute(
                """
                INSERT INTO provider_attempts (
                    request_id,
                    attempt_index,
                    provider,
                    model
                )
                VALUES (?, ?, ?, ?)
                """,
                ("request-1", 1, "cloud", "other-model"),
            )


def test_cancelled_is_a_valid_terminal_outcome(tmp_path: Path) -> None:
    database = Database(tmp_path / "porter.db")
    MigrationRunner(database).apply_all()

    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO requests (
                request_id,
                principal_id,
                source,
                task_type,
                privacy_class,
                allow_cloud,
                outcome
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "request-cancelled",
                "test-user",
                "cli",
                "general",
                "local_only",
                0,
                "cancelled",
            ),
        )

        connection.execute(
            """
            INSERT INTO provider_attempts (
                request_id,
                attempt_index,
                provider,
                model,
                outcome
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "request-cancelled",
                1,
                "local",
                "test-model",
                "cancelled",
            ),
        )
