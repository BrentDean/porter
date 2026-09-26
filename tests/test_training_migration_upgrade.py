from pathlib import Path

from porter.storage.database import Database
from porter.storage.migrations import MigrationRunner, load_migrations
from porter.training import TrainingCorpusRepository


def _build_version_nine_training_database(database: Database) -> None:
    migrations = load_migrations()

    with database.connect() as connection:
        connection.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        for migration in migrations[:9]:
            connection.executescript(migration.sql)
            connection.execute(
                "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
                (migration.version, migration.name),
            )

        connection.execute(
            """
            INSERT INTO training_examples (
                session_id,
                raw_text,
                normalized_text,
                label,
                review_status
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "legacy-session",
                "Show   DISK space",
                "show disk space",
                "legacy-label",
                "reviewed",
            ),
        )
        connection.commit()


def test_training_group_migrations_preserve_existing_examples(tmp_path: Path) -> None:
    database = Database(tmp_path / "porter.db")
    _build_version_nine_training_database(database)

    runner = MigrationRunner(database)
    assert runner.current_version() == 9
    assert runner.apply_all() == (10, 11, 12, 13, 14)
    assert runner.current_version() == 14

    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT
                session_id,
                raw_text,
                normalized_text,
                label,
                route_type,
                group_id,
                review_status,
                reviewed_at
            FROM training_examples
            """
        ).fetchone()

    assert row is not None
    assert tuple(row) == (
        "legacy-session",
        "Show   DISK space",
        "show disk space",
        "legacy-label",
        None,
        None,
        "reviewed",
        None,
    )

    examples = TrainingCorpusRepository(database).list_ungrouped()
    assert len(examples) == 1
    assert examples[0].raw_text == "Show   DISK space"
    assert examples[0].label == "legacy-label"
