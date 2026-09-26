# Local data protection

Porter's authoritative personal state is the host-native SQLite database selected by `ConfigLoader.load_storage()`. Local backups protect that state without introducing a VPS, remote database, or second authoritative Porter instance.

## Backup command

Create a consistent backup while Porter is running:

```bash
porter backup create
```

By default backups are written under:

```text
$PORTER_DATA_DIR/backups
```

or the default Porter data directory when `PORTER_DATA_DIR` is not set.

An alternate local destination may be selected explicitly:

```bash
porter backup create --directory /mnt/porter-backups
```

The destination should ideally be on a different physical disk from the active Porter database.

List known backups:

```bash
porter backup list
porter backup list --directory /mnt/porter-backups
```

Verify an individual backup:

```bash
porter backup verify /mnt/porter-backups/porter-YYYYMMDDTHHMMSS.ffffffZ.db
```

## Consistency model

`BackupService` uses SQLite's online backup API. It copies a consistent database snapshot even when the source database is using WAL mode and Porter has other readers or writers.

The implementation does not copy `porter.db`, `porter.db-wal`, and `porter.db-shm` as independent filesystem files.

A backup is not finalized until:

1. SQLite completes the online backup into a temporary file.
2. `PRAGMA integrity_check` reports `ok`.
3. the `schema_migrations` table confirms that the file is a Porter database.
4. the temporary file is atomically published under its timestamped final name without overwriting any existing backup.

New backup directories are created with mode `0700` and backup files use mode `0600` from creation, including while the snapshot is being written.

## Retention and scheduled backups

Retention is opt-in. To keep the newly created snapshot and the 13 newest
previous snapshots in the selected directory:

```bash
porter backup create --directory /mnt/porter-backups --keep 14
```

Without `--keep`, nothing is deleted. The count must be at least one. Cleanup
runs only after the new backup has passed verification and been published. It
considers only regular files with the exact timestamped names produced by Porter,
excluding symlinks and links to the active database. Every expired snapshot is
verified before any are deleted. A corrupt expired snapshot stops cleanup and
makes the command fail; the newly created backup remains available. Inspect the
reported file before moving it out of the backup directory. Filesystem errors can
leave cleanup partially complete and are reported as command failures.

Use a systemd user timer for daily backups. Create the following two files under
`~/.config/systemd/user/` (or `$XDG_CONFIG_HOME/systemd/user/`). Replace the
executable, database, and destination paths with absolute paths for your host.
`command -v porter` identifies the installed executable. Set `PORTER_DB_PATH`
explicitly to the same database used by your personal Porter instance: the user
service manager does not automatically inherit your shell's environment.

`porter-backup.service`:

```ini
[Unit]
Description=Porter daily local SQLite backup

[Service]
Type=oneshot
Environment="PORTER_DB_PATH=/absolute/path/to/porter.db"
ExecStart="/absolute/path/to/venv/bin/porter" backup create --directory /mnt/porter-backups --keep 14
UMask=0077
```

`porter-backup.timer`:

```ini
[Unit]
Description=Schedule Porter local backups

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

After confirming the destination drive is mounted and writable, test the service
before enabling the timer:

```bash
systemctl --user daemon-reload
systemctl --user start porter-backup.service
journalctl --user -u porter-backup.service -n 30 --no-pager
systemctl --user enable --now porter-backup.timer
systemctl --user list-timers porter-backup.timer
```

`Persistent=true` catches up a missed daily run when the timer becomes active
again. The timer runs while the user's systemd manager is running; running before
login or after logout requires that user's lingering configuration. This is a
user-session schedule by default. Fourteen snapshots means fourteen successful
runs, not necessarily fourteen days. Manual runs with `--keep` share the same
retention pool. Use one scheduled writer per backup directory; retention is not
coordinated across concurrent backup commands.

If using a removable or separately mounted backup disk, add an appropriate mount
check to the service so a missing disk cannot silently redirect backups onto the
root filesystem. These units are examples to install deliberately; updating
Porter does not install or enable a timer automatically.

To stop scheduling without deleting backups:

```bash
systemctl --user disable --now porter-backup.timer
```

## Restore into a new database

Restore a snapshot to a new, explicitly chosen path:

```bash
porter backup restore /mnt/porter-backups/porter-YYYYMMDDTHHMMSS.ffffffZ.db \
  --destination /mnt/porter-recovery/porter.db
porter backup verify /mnt/porter-recovery/porter.db
```

The command verifies the source, copies it using SQLite's backup API into a
private temporary file, applies the installed Porter's migrations to that copy,
and verifies it again before publishing it. Backups from a newer schema version
are rejected. The restored file has mode `0600`; publication refuses to overwrite
an existing destination. A failed migration leaves no published destination.

The destination must differ from the configured `PORTER_DB_PATH`. Existing files,
symlinks (including dangling ones), and destination SQLite sidecars are refused.
Use a fresh recovery directory that no Porter process is configured to use. The
command does not stop services, change configuration, deliver reminders, or
replace the current database. Do not run a reminder worker against the recovered
copy alongside the personal instance: it contains the same pending reminders.

The automated recovery test creates a reminder, backs up the database, removes
the reminder from the source, restores to a separate database, and reads the
original reminder through Porter's repository. It also checks that the source
state and backup contents remain unchanged. This demonstrates data recovery;
it is not a live service cutover test.

## Live restore boundary

Replacing the active database remains deferred. The reminder user service does
not supervise every web, tray, and CLI database writer. Before any future live
cutover, all writers must be stopped, the current state preserved, and the
recovered database selected consistently across those processes. An automated
cutover must enforce that boundary and handle restart and health verification.
The restore command deliberately provides no overwrite option.

## Scope

This feature is local-only. It does not upload backups to a VPS or cloud service and does not change Porter's Ollama, networking, web, inference, or authorization boundaries.
