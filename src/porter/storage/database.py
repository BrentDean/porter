from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_BUSY_TIMEOUT_MILLISECONDS = 5_000


class Database:
    """Owns SQLite connection setup and filesystem preparation."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        connection = sqlite3.connect(
            self.path,
            timeout=_BUSY_TIMEOUT_MILLISECONDS / 1_000,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        journal_mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()
        if journal_mode is None or str(journal_mode[0]).casefold() != "wal":
            connection.close()
            raise RuntimeError("Porter requires SQLite WAL journal mode")

        try:
            yield connection
        finally:
            connection.close()

    def healthcheck(self) -> bool:
        with self.connect() as connection:
            row = connection.execute("SELECT 1").fetchone()

        return row is not None and row[0] == 1
