from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from porter.config.loader import ConfigLoader
from porter.config.models import StorageConfig
from porter.storage.database import Database
from porter.storage.migrations import MigrationRunner
from porter.telemetry.reliability import ReliabilityService
from porter.telemetry.repository import TelemetryRepository


@dataclass(frozen=True, slots=True)
class ReliabilityRuntime:
    storage_config: StorageConfig
    database: Database
    migration_runner: MigrationRunner
    telemetry_repository: TelemetryRepository
    reliability_service: ReliabilityService


def build_reliability_runtime(
    *,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> ReliabilityRuntime:
    """Compose reliability reporting from storage and telemetry only."""
    storage_config = ConfigLoader(env=env, home=home).load_storage()

    database = Database(storage_config.database_path)
    migration_runner = MigrationRunner(database)
    migration_runner.apply_all()

    telemetry_repository = TelemetryRepository(database)
    reliability_service = ReliabilityService(telemetry_repository)

    return ReliabilityRuntime(
        storage_config=storage_config,
        database=database,
        migration_runner=migration_runner,
        telemetry_repository=telemetry_repository,
        reliability_service=reliability_service,
    )
