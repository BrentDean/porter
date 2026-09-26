from __future__ import annotations

import os
import sqlite3
import tempfile
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from porter.storage.database import Database
from porter.storage.migrations import MigrationRunner, load_migrations

_BACKUP_PREFIX = "porter-"
_BACKUP_SUFFIX = ".db"


class BackupIntegrityError(RuntimeError):
    """Raised when a Porter backup fails SQLite or schema validation."""


@dataclass(frozen=True, slots=True)
class BackupRecord:
    path: Path
    size_bytes: int


class BackupService:
    """Create and inspect consistent local backups of Porter's SQLite state."""

    def __init__(
        self,
        database: Database,
        backup_dir: Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._database = database
        self._backup_dir = Path(backup_dir)
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def backup_dir(self) -> Path:
        return self._backup_dir

    def create(self, *, keep: int | None = None) -> BackupRecord:
        if keep is not None and keep < 1:
            raise ValueError("keep must be at least 1")

        if not self._database.path.is_file():
            raise FileNotFoundError(
                f"Porter database does not exist: {self._database.path}"
            )

        self._prepare_backup_dir()

        timestamp = self._clock().astimezone(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        final_path = self._backup_dir / f"{_BACKUP_PREFIX}{timestamp}{_BACKUP_SUFFIX}"
        temporary_path = final_path.with_suffix(f"{final_path.suffix}.tmp")

        if final_path.exists():
            raise FileExistsError(f"backup path already exists: {final_path}")

        # Create the temporary file privately before writing any personal state.
        # O_EXCL prevents following a pre-existing temporary-file symlink.
        fd = os.open(temporary_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)

        try:
            with self._database.connect() as source:
                with closing(sqlite3.connect(temporary_path)) as destination:
                    source.backup(destination)
                    # Publish a standalone snapshot without WAL sidecar files.
                    destination.execute("PRAGMA journal_mode=DELETE")

            self.verify(temporary_path)
            # Link publication is atomic and refuses to overwrite a backup
            # created concurrently with the same timestamp.
            os.link(temporary_path, final_path)
            temporary_path.unlink()
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise

        if keep is not None:
            self._prune(keep=keep, current=final_path)

        return BackupRecord(
            path=final_path,
            size_bytes=final_path.stat().st_size,
        )

    def restore(self, path: Path, *, destination: Path) -> BackupRecord:
        """Recover into a new database without replacing any existing state."""
        destination = Path(destination).absolute()
        if destination.resolve() == self._database.path.resolve():
            raise BackupIntegrityError("restore destination is the configured Porter database")

        def check_destination() -> None:
            for suffix in ("", "-wal", "-shm", "-journal"):
                candidate = Path(f"{destination}{suffix}")
                if candidate.exists() or candidate.is_symlink():
                    raise FileExistsError(f"restore destination already exists: {candidate}")

        check_destination()
        self.verify(path)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(prefix=".porter-restore-", suffix=".db", dir=destination.parent)
        os.close(fd)
        temporary = Path(name)
        try:
            uri = f"{Path(path).resolve().as_uri()}?mode=ro"
            with closing(sqlite3.connect(uri, uri=True)) as source:
                with closing(sqlite3.connect(temporary)) as target:
                    source.backup(target)
                    target.execute("PRAGMA journal_mode=DELETE")

            self.verify(temporary)
            database = Database(temporary)
            runner = MigrationRunner(database)
            if runner.current_version() > max(m.version for m in load_migrations()):
                raise BackupIntegrityError("backup requires a newer version of Porter")
            runner.apply_all()
            with closing(sqlite3.connect(temporary)) as target:
                target.execute("PRAGMA journal_mode=DELETE")
            self.verify(temporary)
            check_destination()
            # Publish only a complete, migrated copy; never replace an existing file.
            os.link(temporary, destination)
        finally:
            for suffix in ("", "-wal", "-shm", "-journal", ".migrations.lock"):
                Path(f"{temporary}{suffix}").unlink(missing_ok=True)

        return BackupRecord(path=destination, size_bytes=destination.stat().st_size)

    def _prune(self, *, keep: int, current: Path) -> None:
        candidates = []
        for record in self.list():
            path = record.path
            if path.is_symlink() or path.samefile(current):
                continue
            if path.samefile(self._database.path):
                continue
            try:
                timestamp = datetime.strptime(path.name, "porter-%Y%m%dT%H%M%S.%fZ.db")
            except ValueError:
                continue
            if timestamp.strftime("porter-%Y%m%dT%H%M%S.%fZ.db") != path.name:
                continue
            candidates.append(path)

        expired = candidates[keep - 1:]
        # Validate every expired snapshot before deleting any of them.
        for path in expired:
            self.verify(path)
        for path in expired:
            path.unlink()

    def list(self) -> tuple[BackupRecord, ...]:
        if not self._backup_dir.exists():
            return ()

        records = [
            BackupRecord(path=path, size_bytes=path.stat().st_size)
            for path in self._backup_dir.glob(
                f"{_BACKUP_PREFIX}*{_BACKUP_SUFFIX}"
            )
            if path.is_file()
        ]
        records.sort(key=lambda record: record.path.name, reverse=True)
        return tuple(records)

    @staticmethod
    def verify(path: Path) -> BackupRecord:
        backup_path = Path(path)
        if not backup_path.is_file():
            raise FileNotFoundError(f"backup does not exist: {backup_path}")

        try:
            uri = f"{backup_path.resolve().as_uri()}?mode=ro"
            with closing(sqlite3.connect(uri, uri=True)) as connection:
                rows = connection.execute("PRAGMA integrity_check").fetchall()
                if not rows or any(str(row[0]).casefold() != "ok" for row in rows):
                    raise BackupIntegrityError(
                        f"SQLite integrity check failed: {backup_path}"
                    )

                migration_table = connection.execute(
                    """
                    SELECT 1
                    FROM sqlite_master
                    WHERE type = 'table' AND name = 'schema_migrations'
                    """
                ).fetchone()
                if migration_table is None:
                    raise BackupIntegrityError(
                        f"backup is not a Porter database: {backup_path}"
                    )
        except BackupIntegrityError:
            raise
        except sqlite3.DatabaseError as exc:
            raise BackupIntegrityError(
                f"backup is not a valid SQLite database: {backup_path}"
            ) from exc

        return BackupRecord(
            path=backup_path,
            size_bytes=backup_path.stat().st_size,
        )

    def _prepare_backup_dir(self) -> None:
        created = not self._backup_dir.exists()
        self._backup_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        if created:
            os.chmod(self._backup_dir, 0o700)
