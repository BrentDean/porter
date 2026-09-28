from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from porter.config.loader import ConfigLoader
from porter.storage import BackupIntegrityError, BackupService, Database


def _format_bytes(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"

    value = float(size_bytes)
    for unit in ("KiB", "MiB", "GiB", "TiB"):
        value /= 1024
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}"

    raise AssertionError("unreachable size unit")


def _service(
    loader: ConfigLoader,
    backup_dir: Path | None,
) -> BackupService:
    storage = loader.load_storage()
    return BackupService(
        Database(storage.database_path),
        backup_dir or storage.data_dir / "backups",
    )


def run(
    args: list[str],
    *,
    loader: ConfigLoader | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="porter backup",
        description="Create and verify local backups of Porter's SQLite state",
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    create_parser = subparsers.add_parser(
        "create",
        help="create a consistent online SQLite backup",
    )
    create_parser.add_argument(
        "--directory",
        type=Path,
        help="backup directory (default: PORTER_DATA_DIR/backups)",
    )

    create_parser.add_argument(
        "--keep",
        type=int,
        help="retain this many snapshots after a successful backup (minimum: 1)",
    )

    list_parser = subparsers.add_parser(
        "list",
        help="list local Porter backups",
    )
    list_parser.add_argument(
        "--directory",
        type=Path,
        help="backup directory (default: PORTER_DATA_DIR/backups)",
    )

    verify_parser = subparsers.add_parser(
        "verify",
        help="run SQLite integrity and Porter-schema checks on a backup",
    )
    verify_parser.add_argument("path", type=Path)

    restore_parser = subparsers.add_parser(
        "restore",
        help="restore a backup into a new database path without overwriting existing state",
    )
    restore_parser.add_argument("path", type=Path)
    restore_parser.add_argument("--destination", type=Path, required=True)

    parsed = parser.parse_args(args)
    if parsed.action == "create" and parsed.keep is not None and parsed.keep < 1:
        parser.error("--keep must be at least 1")
    config_loader = loader or ConfigLoader()

    try:
        if parsed.action == "create":
            service = _service(config_loader, parsed.directory)
            record = service.create(keep=parsed.keep)
            print("Porter backup")
            print(f"  source: {config_loader.load_storage().database_path}")
            print(f"  backup: {record.path}")
            print(f"  size: {_format_bytes(record.size_bytes)}")
            print("  integrity: ok")
            return 0

        if parsed.action == "list":
            service = _service(config_loader, parsed.directory)
            records = service.list()
            print("Porter backups")
            print(f"  directory: {service.backup_dir}")
            print(f"  count: {len(records)}")
            for record in records:
                print(f"  {record.path.name}  {_format_bytes(record.size_bytes)}")
            return 0

        if parsed.action == "restore":
            record = _service(config_loader, None).restore(
                parsed.path, destination=parsed.destination,
            )
            print("Porter backup restore")
            print(f"  restored: {record.path}")
            print(f"  size: {_format_bytes(record.size_bytes)}")
            print("  integrity: ok")
            print("  active database: unchanged")
            return 0

        if parsed.action == "verify":
            record = BackupService.verify(parsed.path)
            print("Porter backup verify")
            print(f"  backup: {record.path}")
            print(f"  size: {_format_bytes(record.size_bytes)}")
            print("  integrity: ok")
            return 0
    except (BackupIntegrityError, OSError, sqlite3.DatabaseError) as exc:
        print(f"porter backup: {exc}", file=sys.stderr)
        return 1

    raise AssertionError(f"unhandled backup action: {parsed.action}")


def main() -> None:
    try:
        exit_code = run(sys.argv[1:])
    except KeyboardInterrupt:
        exit_code = 130
    raise SystemExit(exit_code)
