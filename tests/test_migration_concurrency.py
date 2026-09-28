from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from porter.storage.database import Database
from porter.storage.migrations import MigrationRunner, load_migrations

_WORKER_COUNT = 8


def test_concurrent_migration_runners_apply_each_version_once(tmp_path: Path) -> None:
    database = Database(tmp_path / "porter.db")
    runner = MigrationRunner(database)
    expected_versions = tuple(migration.version for migration in load_migrations())

    assert runner.current_version() == 0

    barrier = Barrier(_WORKER_COUNT)

    def apply_migrations(_worker: int) -> tuple[int, ...]:
        barrier.wait(timeout=5)
        return MigrationRunner(database).apply_all()

    with ThreadPoolExecutor(max_workers=_WORKER_COUNT) as executor:
        results = tuple(executor.map(apply_migrations, range(_WORKER_COUNT)))

    applied_versions = sorted(
        version
        for result in results
        for version in result
    )

    assert applied_versions == list(expected_versions)
    assert results.count(expected_versions) == 1
    assert sum(bool(result) for result in results) == 1
    assert all(tuple(sorted(result)) == result for result in results)
    assert runner.current_version() == expected_versions[-1]

    with database.connect() as connection:
        row = connection.execute(
            "SELECT COUNT(*) FROM schema_migrations"
        ).fetchone()

    assert row is not None
    assert row[0] == len(expected_versions)
