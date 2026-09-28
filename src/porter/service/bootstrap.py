from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from porter.config.loader import ConfigLoader
from porter.config.models import StorageConfig
from porter.reminders import (
    ReminderDelivery,
    ReminderRepository,
    ReminderRunner,
    ReminderService,
    SqliteReminderRepository,
)
from porter.service.runtime import DEFAULT_POLL_INTERVAL_SECONDS, PorterService
from porter.storage.database import Database
from porter.storage.migrations import MigrationRunner


@dataclass(frozen=True, slots=True)
class PorterServiceRuntime:
    storage_config: StorageConfig
    database: Database
    migration_runner: MigrationRunner
    reminder_repository: ReminderRepository
    reminder_service: ReminderService
    reminder_runner: ReminderRunner
    service: PorterService


def build_service_runtime(
    delivery: ReminderDelivery,
    *,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
) -> PorterServiceRuntime:
    """Compose the lightweight background runtime without unrelated config."""
    storage_config = ConfigLoader(env=env, home=home).load_storage()

    database = Database(storage_config.database_path)
    migration_runner = MigrationRunner(database)
    migration_runner.apply_all()

    reminder_repository = SqliteReminderRepository(database)
    reminder_service = ReminderService(reminder_repository)
    reminder_runner = ReminderRunner(
        reminder_repository,
        reminder_service,
        delivery,
    )
    service = PorterService(
        reminder_runner,
        poll_interval_seconds=poll_interval_seconds,
    )

    return PorterServiceRuntime(
        storage_config=storage_config,
        database=database,
        migration_runner=migration_runner,
        reminder_repository=reminder_repository,
        reminder_service=reminder_service,
        reminder_runner=reminder_runner,
        service=service,
    )
