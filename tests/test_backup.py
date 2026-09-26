from __future__ import annotations

import sqlite3
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from porter.cli.commands.backup import run
from porter.cli.main import _main
from porter.config.loader import ConfigLoader
from porter.storage import BackupIntegrityError, BackupService, Database, MigrationRunner


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "porter.db")
    MigrationRunner(database).apply_all()
    return database


def test_backup_create_copies_committed_wal_state_and_sets_private_permissions(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    with database.connect() as connection:
        connection.execute(
            "CREATE TABLE backup_probe (value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO backup_probe(value) VALUES ('committed')"
        )
        connection.commit()

    service = BackupService(
        database,
        tmp_path / "backups",
        clock=lambda: datetime(2026, 9, 22, 13, 0, tzinfo=UTC),
    )

    record = service.create()

    assert record.path.name == "porter-20260922T130000.000000Z.db"
    assert stat.S_IMODE(record.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(record.path.parent.stat().st_mode) == 0o700

    uri = f"{record.path.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        row = connection.execute("SELECT value FROM backup_probe").fetchone()

    assert row == ("committed",)
    assert BackupService.verify(record.path) == record


def test_backup_create_does_not_overwrite_same_timestamp(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    service = BackupService(
        database,
        tmp_path / "backups",
        clock=lambda: datetime(2026, 9, 22, 13, 0, tzinfo=UTC),
    )

    original = service.create()
    before = original.path.read_bytes()

    with pytest.raises(FileExistsError, match="backup path already exists"):
        service.create()

    assert original.path.read_bytes() == before
    assert not original.path.with_suffix(".db.tmp").exists()


def test_backup_create_refuses_missing_database(tmp_path: Path) -> None:
    service = BackupService(
        Database(tmp_path / "missing.db"),
        tmp_path / "backups",
    )

    with pytest.raises(FileNotFoundError, match="database does not exist"):
        service.create()

    assert not (tmp_path / "missing.db").exists()


def test_backup_verify_rejects_corrupt_file(tmp_path: Path) -> None:
    backup = tmp_path / "porter-corrupt.db"
    backup.write_bytes(b"not sqlite")

    with pytest.raises(BackupIntegrityError, match="valid SQLite"):
        BackupService.verify(backup)


def test_backup_verify_rejects_non_porter_database(tmp_path: Path) -> None:
    backup = tmp_path / "porter-other.db"
    with sqlite3.connect(backup) as connection:
        connection.execute("CREATE TABLE unrelated (value TEXT)")
        connection.commit()

    with pytest.raises(BackupIntegrityError, match="not a Porter database"):
        BackupService.verify(backup)


def test_backup_list_is_newest_first_and_ignores_temporary_files(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    backup_dir = tmp_path / "backups"
    older = backup_dir / "porter-20260921T120000.000000Z.db"
    newer = backup_dir / "porter-20260922T120000.000000Z.db"
    temporary = backup_dir / "porter-20260923T120000.000000Z.db.tmp"
    backup_dir.mkdir()
    older.write_bytes(b"a")
    newer.write_bytes(b"bb")
    temporary.write_bytes(b"ccc")

    records = BackupService(database, backup_dir).list()

    assert [record.path for record in records] == [newer, older]
    assert [record.size_bytes for record in records] == [2, 1]


def test_backup_cli_create_list_and_verify(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = _database(tmp_path)
    loader = ConfigLoader(
        env={"PORTER_DB_PATH": str(database.path)},
        home=tmp_path,
    )
    backup_dir = tmp_path / "copies"

    assert run(
        ["create", "--directory", str(backup_dir)],
        loader=loader,
    ) == 0
    created_output = capsys.readouterr().out
    assert "Porter backup" in created_output
    assert "integrity: ok" in created_output

    backups = tuple(backup_dir.glob("porter-*.db"))
    assert len(backups) == 1

    assert run(
        ["list", "--directory", str(backup_dir)],
        loader=loader,
    ) == 0
    list_output = capsys.readouterr().out
    assert "count: 1" in list_output
    assert backups[0].name in list_output

    assert run(["verify", str(backups[0])], loader=loader) == 0
    verify_output = capsys.readouterr().out
    assert "Porter backup verify" in verify_output
    assert "integrity: ok" in verify_output


def test_backup_cli_reports_integrity_failure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    corrupt = tmp_path / "corrupt.db"
    corrupt.write_bytes(b"broken")

    result = run(["verify", str(corrupt)])

    captured = capsys.readouterr()
    assert result == 1
    assert "valid SQLite database" in captured.err


def test_backup_subcommand_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    monkeypatch.setattr(
        "porter.cli.commands.backup.run",
        lambda args: calls.append(args) or 0,
    )

    result = _main(["backup", "list", "--directory", "/tmp/porter-backups"])

    assert result == 0
    assert calls == [["list", "--directory", "/tmp/porter-backups"]]


def test_retention_preserves_new_snapshot_and_newest_previous_backup(tmp_path: Path) -> None:
    database = _database(tmp_path)
    backup_dir = tmp_path / "backups"
    snapshots = [
        BackupService(
            database, backup_dir,
            clock=lambda day=day: datetime(2026, 9, day, tzinfo=UTC),
        ).create().path
        for day in (20, 21, 22)
    ]
    # Protect the new snapshot even if the system clock moves backwards.
    current = BackupService(
        database, backup_dir, clock=lambda: datetime(2026, 9, 19, tzinfo=UTC),
    ).create(keep=2)
    assert sorted(backup_dir.iterdir()) == sorted([current.path, snapshots[-1]])
    BackupService.verify(current.path)


def test_retention_ignores_unrelated_files_symlinks_and_source(tmp_path: Path) -> None:
    database = _database(tmp_path)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    unrelated = backup_dir / "porter-not-a-snapshot.db"
    unrelated.write_bytes(b"unrelated")
    temporary = backup_dir / "porter-20260101T000000.000000Z.db.tmp"
    temporary.write_bytes(b"unfinished")
    symlink = backup_dir / "porter-20260102T000000.000000Z.db"
    symlink.symlink_to(database.path)
    source_link = backup_dir / "porter-20260103T000000.000000Z.db"
    source_link.hardlink_to(database.path)

    BackupService(database, backup_dir).create(keep=1)

    assert unrelated.read_bytes() == b"unrelated"
    assert temporary.read_bytes() == b"unfinished"
    assert symlink.is_symlink()
    assert source_link.samefile(database.path)
    BackupService.verify(database.path)


def test_failed_backup_does_not_prune(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = BackupService(_database(tmp_path), tmp_path / "backups")
    original = service.create().path

    def fail_verify(path: Path) -> None:
        raise BackupIntegrityError("injected failure")

    monkeypatch.setattr(BackupService, "verify", staticmethod(fail_verify))
    with pytest.raises(BackupIntegrityError, match="injected failure"):
        service.create(keep=1)
    assert list(service.backup_dir.iterdir()) == [original]


def test_retention_checks_all_expired_files_before_deleting(tmp_path: Path) -> None:
    service = BackupService(_database(tmp_path), tmp_path / "backups")
    original = service.create().path
    corrupt = service.backup_dir / "porter-20260101T000000.000000Z.db"
    corrupt.write_bytes(b"broken")
    with pytest.raises(BackupIntegrityError):
        service.create(keep=1)
    assert original.exists()
    assert corrupt.exists()
    assert len(service.list()) == 3  # The newly verified backup is also preserved.


@pytest.mark.parametrize("keep", ["0", "-1"])
def test_backup_cli_rejects_invalid_retention_before_creating(
    tmp_path: Path, keep: str,
) -> None:
    backup_dir = tmp_path / "backups"
    with pytest.raises(SystemExit) as exc:
        run(["create", "--directory", str(backup_dir), "--keep", keep])
    assert exc.value.code == 2
    assert not backup_dir.exists()


def test_backup_cli_retention(tmp_path: Path) -> None:
    database = _database(tmp_path)
    loader = ConfigLoader(env={"PORTER_DB_PATH": str(database.path)}, home=tmp_path)
    backup_dir = tmp_path / "backups"
    args = ["create", "--directory", str(backup_dir)]
    assert run(args, loader=loader) == 0
    assert run(args, loader=loader) == 0
    assert len(list(backup_dir.iterdir())) == 2
    assert run([*args, "--keep", "1"], loader=loader) == 0
    assert len(list(backup_dir.iterdir())) == 1


def test_restore_recovers_reminder_without_changing_source(tmp_path: Path) -> None:
    from porter.reminders import ReminderService, SqliteReminderRepository

    database = _database(tmp_path)
    reminders = ReminderService(SqliteReminderRepository(database))
    reminder = reminders.create_reminder(
        "alice", "Recovery drill", datetime(2030, 1, 1, tzinfo=UTC),
    )
    service = BackupService(database, tmp_path / "backups")
    snapshot = service.create().path
    snapshot_bytes = snapshot.read_bytes()
    with database.connect() as connection:
        connection.execute("DELETE FROM reminders")
        connection.commit()

    recovered = service.restore(snapshot, destination=tmp_path / "recovered" / "porter.db")

    repository = SqliteReminderRepository(Database(recovered.path))
    assert repository.get_reminder("alice", reminder.id) == reminder
    assert reminders.list_reminders("alice") == ()
    assert snapshot.read_bytes() == snapshot_bytes
    assert stat.S_IMODE(recovered.path.stat().st_mode) == 0o600
    assert not list(recovered.path.parent.glob(".porter-restore-*"))


@pytest.mark.parametrize("suffix", ["", "-wal", "-shm", "-journal"])
def test_restore_refuses_existing_destination_or_sidecars(tmp_path: Path, suffix: str) -> None:
    service = BackupService(_database(tmp_path), tmp_path / "backups")
    snapshot = service.create().path
    destination = tmp_path / "recovered.db"
    existing = Path(f"{destination}{suffix}")
    existing.write_bytes(b"preserve me")
    with pytest.raises(FileExistsError):
        service.restore(snapshot, destination=destination)
    assert existing.read_bytes() == b"preserve me"


def test_restore_refuses_configured_path_even_when_missing(tmp_path: Path) -> None:
    service = BackupService(Database(tmp_path / "missing.db"), tmp_path / "backups")
    with pytest.raises(BackupIntegrityError, match="configured Porter database"):
        service.restore(tmp_path / "snapshot.db", destination=service._database.path)
    assert not (tmp_path / "missing.db").exists()


def test_restore_refuses_dangling_symlink(tmp_path: Path) -> None:
    service = BackupService(_database(tmp_path), tmp_path / "backups")
    snapshot = service.create().path
    destination = tmp_path / "recovered.db"
    destination.symlink_to(tmp_path / "absent.db")
    with pytest.raises(FileExistsError):
        service.restore(snapshot, destination=destination)
    assert destination.is_symlink()
    assert not (tmp_path / "absent.db").exists()


def test_restore_corrupt_backup_leaves_no_destination(tmp_path: Path) -> None:
    service = BackupService(_database(tmp_path), tmp_path / "backups")
    corrupt = tmp_path / "corrupt.db"
    corrupt.write_bytes(b"invalid")
    with pytest.raises(BackupIntegrityError):
        service.restore(corrupt, destination=tmp_path / "recovered.db")
    assert not (tmp_path / "recovered.db").exists()
    assert not list(tmp_path.glob(".porter-restore-*"))


def test_restore_upgrades_older_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from porter.storage.migrations import load_migrations

    migrations = load_migrations()
    with monkeypatch.context() as patch:
        patch.setattr("porter.storage.migrations.load_migrations", lambda: migrations[:-1])
        database = _database(tmp_path)
    service = BackupService(database, tmp_path / "backups")
    snapshot = service.create().path
    result = service.restore(snapshot, destination=tmp_path / "recovered.db")
    assert MigrationRunner(Database(result.path)).current_version() == migrations[-1].version
    assert MigrationRunner(database).current_version() == migrations[-2].version
    with sqlite3.connect(result.path) as connection:
        assert "kind" in {row[1] for row in connection.execute("PRAGMA table_info(reminders)")}


def test_restore_rejects_newer_schema(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with database.connect() as connection:
        connection.execute("INSERT INTO schema_migrations(version, name) VALUES (999, 'future')")
        connection.commit()
    service = BackupService(database, tmp_path / "backups")
    snapshot = service.create().path
    with pytest.raises(BackupIntegrityError, match="newer version"):
        service.restore(snapshot, destination=tmp_path / "recovered.db")
    assert not (tmp_path / "recovered.db").exists()
    assert not list(tmp_path.glob(".porter-restore-*"))


def test_restore_migration_failure_cleans_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = BackupService(_database(tmp_path), tmp_path / "backups")
    snapshot = service.create().path

    def fail_migration(self: MigrationRunner) -> tuple[int, ...]:
        raise sqlite3.OperationalError("injected failure")

    monkeypatch.setattr(MigrationRunner, "apply_all", fail_migration)
    with pytest.raises(sqlite3.OperationalError, match="injected failure"):
        service.restore(snapshot, destination=tmp_path / "recovered.db")
    assert not (tmp_path / "recovered.db").exists()
    assert not list(tmp_path.glob(".porter-restore-*"))
    BackupService.verify(snapshot)


def test_backup_cli_restore(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    database = _database(tmp_path)
    snapshot = BackupService(database, tmp_path / "backups").create().path
    loader = ConfigLoader(env={"PORTER_DB_PATH": str(database.path)}, home=tmp_path)
    destination = tmp_path / "recovered.db"
    args = ["restore", str(snapshot), "--destination", str(destination)]
    assert run(args, loader=loader) == 0
    assert "active database: unchanged" in capsys.readouterr().out
    assert Database(destination).healthcheck()
    assert run(args, loader=loader) == 1
    assert "already exists" in capsys.readouterr().err


def test_restore_does_not_overwrite_destination_created_during_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os

    service = BackupService(_database(tmp_path), tmp_path / "backups")
    snapshot = service.create().path
    destination = tmp_path / "recovered.db"
    original_link = os.link

    def race_link(source: Path, target: Path) -> None:
        target.write_bytes(b"concurrent file")
        original_link(source, target)

    monkeypatch.setattr("porter.storage.backup.os.link", race_link)
    with pytest.raises(FileExistsError):
        service.restore(snapshot, destination=destination)
    assert destination.read_bytes() == b"concurrent file"
    assert not list(tmp_path.glob(".porter-restore-*"))
