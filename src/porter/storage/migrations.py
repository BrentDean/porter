from __future__ import annotations

import fcntl
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import resources

from porter.storage.database import Database

_MIGRATION_PATTERN = re.compile(r"^(?P<version>\d{3})_(?P<name>[a-z0-9_]+)\.sql$")


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str


def load_migrations() -> tuple[Migration, ...]:
    package = resources.files("porter.storage.sql")
    migrations: list[Migration] = []

    for entry in package.iterdir():
        match = _MIGRATION_PATTERN.match(entry.name)
        if match is None:
            continue

        migrations.append(
            Migration(
                version=int(match.group("version")),
                name=match.group("name"),
                sql=entry.read_text(encoding="utf-8"),
            )
        )

    migrations.sort(key=lambda migration: migration.version)
    versions = [migration.version for migration in migrations]
    if len(versions) != len(set(versions)):
        raise ValueError("migration versions must be unique")

    return tuple(migrations)


class MigrationRunner:
    """Owns schema-version tracking and ordered migration application."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def current_version(self) -> int:
        with self._database.connect() as connection:
            self._ensure_migration_table(connection)
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()

        return int(row[0]) if row is not None else 0

    def apply_all(self) -> tuple[int, ...]:
        migrations = load_migrations()
        applied_now: list[int] = []

        with self._migration_lock():
            with self._database.connect() as connection:
                self._ensure_migration_table(connection)
                applied = {
                    int(row[0])
                    for row in connection.execute(
                        "SELECT version FROM schema_migrations"
                    )
                }

                for migration in migrations:
                    if migration.version in applied:
                        continue

                    name = migration.name.replace("'", "''")
                    script = (
                        "BEGIN IMMEDIATE;\n"
                        f"{migration.sql}\n"
                        "INSERT INTO schema_migrations(version, name) "
                        f"VALUES ({migration.version}, '{name}');\n"
                        "COMMIT;\n"
                    )

                    try:
                        connection.executescript(script)
                    except Exception:
                        connection.rollback()
                        raise

                    applied_now.append(migration.version)

        return tuple(applied_now)

    @contextmanager
    def _migration_lock(self) -> Iterator[None]:
        lock_path = self._database.path.with_name(
            f"{self._database.path.name}.migrations.lock"
        )
        lock_path.parent.mkdir(parents=True, exist_ok=True)

        with lock_path.open("a", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _ensure_migration_table(connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.commit()
