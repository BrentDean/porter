import sqlite3
from pathlib import Path

from porter.storage.database import Database


def test_database_creates_parent_directory_and_connects(tmp_path: Path) -> None:
    database_path = tmp_path / "nested" / "porter.db"
    database = Database(database_path)

    assert database.healthcheck() is True
    assert database_path.exists()


def test_database_enables_foreign_keys(tmp_path: Path) -> None:
    database = Database(tmp_path / "porter.db")

    with database.connect() as connection:
        enabled = connection.execute("PRAGMA foreign_keys").fetchone()

    assert enabled is not None
    assert enabled[0] == 1


def test_database_configures_wal_and_busy_timeout(tmp_path: Path) -> None:
    database_path = tmp_path / "porter.db"
    database = Database(database_path)

    with database.connect() as connection:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()

    assert journal_mode is not None
    assert journal_mode[0] == "wal"
    assert busy_timeout is not None
    assert busy_timeout[0] == 5_000

    with sqlite3.connect(database_path) as connection:
        persisted_journal_mode = connection.execute("PRAGMA journal_mode").fetchone()

    assert persisted_journal_mode is not None
    assert persisted_journal_mode[0] == "wal"
