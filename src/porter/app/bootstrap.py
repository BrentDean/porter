from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from prometheus_client import CollectorRegistry

from porter.actions.plex import (
    PlexRestartHandler,
    PlexServiceController,
    PlexStartHandler,
    PlexStopHandler,
)
from porter.actions.storage import (
    DiskPressureHandler,
    DiskUsageHandler,
    MountedStorageHandler,
    StorageInventory,
    StorageLayoutHandler,
    UnmountedStorageHandler,
)
from porter.app.dispatcher import RequestDispatcher
from porter.app.inference import InferenceGate
from porter.cache import InferenceCache
from porter.config.loader import ConfigLoader
from porter.config.models import PorterConfig
from porter.core.lifecycle import CompositeRuntimeLifecycle
from porter.intents import (
    CompositeIntentRecognitionContextProvider,
    CurrentDateHandler,
    CurrentTimeHandler,
    DeterministicIntentExecutor,
    IntentHandlerRegistry,
    IntentRecognitionContextProvider,
)
from porter.intents.planning import (
    PlannerOverdueHandler,
    PlannerTodayHandler,
    PlannerUnscheduledHandler,
    PlannerUpcomingHandler,
)
from porter.memory import (
    MemoryForgetHandler,
    MemoryListHandler,
    MemoryRememberHandler,
    MemoryRepository,
)
from porter.orchestration import Orchestrator
from porter.policy import PolicyEngine
from porter.providers.base import InferenceProvider
from porter.providers.executor import ProviderExecutor
from porter.providers.ollama import OllamaProvider
from porter.providers.openai import OpenAIProvider
from porter.providers.registry import ProviderRegistry
from porter.reminders import ReminderRepository, ReminderService, SqliteReminderRepository
from porter.reminders.intents import (
    ReminderCancelHandler,
    ReminderCreateHandler,
    ReminderListHandler,
    TimerCancelHandler,
    TimerCreateHandler,
    TimerListHandler,
)
from porter.routing import ModelRouter
from porter.storage.database import Database
from porter.storage.migrations import MigrationRunner
from porter.tasks import SqliteTaskRepository, TaskRepository, TaskService
from porter.tasks.context import TaskIntentRecognitionContextProvider
from porter.tasks.intents import (
    ListAddItemHandler,
    ListCompleteItemHandler,
    ListRemoveItemHandler,
)
from porter.tasks.planning import PlannerService
from porter.telemetry.lifecycle import TelemetryLifecycle
from porter.telemetry.metrics import MetricsLifecycle
from porter.telemetry.repository import TelemetryRepository
from porter.telemetry.structured_logging import LoggingLifecycle
from porter.tools import QalculateTool, ToolExecutor, ToolRegistry, WeatherTool
from porter.training import RecognitionGapRepository, TrainingCorpusRepository


@dataclass(frozen=True, slots=True)
class PorterApplication:
    config: PorterConfig
    database: Database
    migration_runner: MigrationRunner
    inference_cache: InferenceCache
    metrics_registry: CollectorRegistry
    provider_registry: ProviderRegistry
    telemetry_repository: TelemetryRepository
    memory_repository: MemoryRepository
    task_repository: TaskRepository
    task_service: TaskService
    planner_service: PlannerService
    reminder_repository: ReminderRepository
    reminder_service: ReminderService
    training_repository: TrainingCorpusRepository
    recognition_gap_repository: RecognitionGapRepository
    storage_inventory: StorageInventory
    orchestrator: Orchestrator
    intent_handler_registry: IntentHandlerRegistry
    intent_context_provider: IntentRecognitionContextProvider
    deterministic_executor: DeterministicIntentExecutor
    tool_registry: ToolRegistry
    tool_executor: ToolExecutor
    dispatcher: RequestDispatcher


def build_application(
    *,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
    providers: tuple[InferenceProvider, ...] = (),
) -> PorterApplication:
    config = ConfigLoader(env=env, home=home).load()

    database = Database(config.storage.database_path)
    migration_runner = MigrationRunner(database)
    migration_runner.apply_all()
    inference_cache = InferenceCache(database)

    telemetry_repository = TelemetryRepository(database)
    telemetry_lifecycle = TelemetryLifecycle(telemetry_repository)
    metrics_registry = CollectorRegistry()
    metrics_lifecycle = MetricsLifecycle(metrics_registry)
    logging_lifecycle = LoggingLifecycle()
    runtime_lifecycle = CompositeRuntimeLifecycle(
        (telemetry_lifecycle, metrics_lifecycle, logging_lifecycle)
    )
    memory_repository = MemoryRepository(database)

    task_repository = SqliteTaskRepository(database)
    task_service = TaskService(task_repository)
    planner_service = PlannerService(task_service)

    reminder_repository = SqliteReminderRepository(database)
    reminder_service = ReminderService(reminder_repository)
    training_repository = TrainingCorpusRepository(database)
    recognition_gap_repository = RecognitionGapRepository(database)
    inference_gate = InferenceGate(recognition_gap_repository)

    configured_providers = list(providers)
    if config.ollama.model is not None:
        configured_providers.append(OllamaProvider(config.ollama))
    if config.openai.configured:
        configured_providers.append(OpenAIProvider(config.openai))

    provider_registry = ProviderRegistry(tuple(configured_providers))
    policy = PolicyEngine()
    router = ModelRouter(provider_registry)
    executor = ProviderExecutor(
        provider_registry,
        lifecycle=runtime_lifecycle,
        cache=inference_cache,
    )
    orchestrator = Orchestrator(
        policy,
        router,
        executor,
        lifecycle=runtime_lifecycle,
    )

    plex_controller = PlexServiceController()
    storage_inventory = StorageInventory()
    intent_handler_registry = IntentHandlerRegistry(
        (
            CurrentTimeHandler(),
            CurrentDateHandler(),
            ListAddItemHandler(task_service),
            ListCompleteItemHandler(task_service),
            ListRemoveItemHandler(task_service),
            PlannerTodayHandler(planner_service),
            PlannerOverdueHandler(planner_service),
            PlannerUpcomingHandler(planner_service),
            PlannerUnscheduledHandler(planner_service),
            ReminderCreateHandler(reminder_service),
            ReminderListHandler(reminder_service),
            ReminderCancelHandler(reminder_service),
            TimerCreateHandler(reminder_service),
            TimerListHandler(reminder_service),
            TimerCancelHandler(reminder_service),
            MemoryRememberHandler(memory_repository),
            MemoryListHandler(memory_repository),
            MemoryForgetHandler(memory_repository),
            PlexStartHandler(plex_controller),
            PlexStopHandler(plex_controller),
            PlexRestartHandler(plex_controller),
            MountedStorageHandler(storage_inventory),
            UnmountedStorageHandler(storage_inventory),
            StorageLayoutHandler(storage_inventory),
            DiskUsageHandler(storage_inventory),
            DiskPressureHandler(storage_inventory),
        )
    )
    intent_context_provider = CompositeIntentRecognitionContextProvider(
        (TaskIntentRecognitionContextProvider(task_service),)
    )
    deterministic_executor = DeterministicIntentExecutor(
        intent_handler_registry,
        context_provider=intent_context_provider,
    )

    tool_registry = ToolRegistry(
        (
            QalculateTool(),
            WeatherTool(
                synoptic_token=config.weather.synoptic_token,
                synoptic_radius_miles=config.weather.synoptic_radius_miles,
                synoptic_station_limit=config.weather.synoptic_station_limit,
                synoptic_within_minutes=config.weather.synoptic_within_minutes,
            ),
        )
    )
    tool_executor = ToolExecutor(tool_registry, lifecycle=runtime_lifecycle)

    dispatcher = RequestDispatcher(
        deterministic_executor,
        tool_executor,
        orchestrator,
        lifecycle=runtime_lifecycle,
        inference_gate=inference_gate,
        memory_repository=memory_repository,
    )

    return PorterApplication(
        config=config,
        database=database,
        migration_runner=migration_runner,
        inference_cache=inference_cache,
        metrics_registry=metrics_registry,
        provider_registry=provider_registry,
        telemetry_repository=telemetry_repository,
        memory_repository=memory_repository,
        task_repository=task_repository,
        task_service=task_service,
        planner_service=planner_service,
        reminder_repository=reminder_repository,
        reminder_service=reminder_service,
        training_repository=training_repository,
        recognition_gap_repository=recognition_gap_repository,
        storage_inventory=storage_inventory,
        orchestrator=orchestrator,
        intent_handler_registry=intent_handler_registry,
        intent_context_provider=intent_context_provider,
        deterministic_executor=deterministic_executor,
        tool_registry=tool_registry,
        tool_executor=tool_executor,
        dispatcher=dispatcher,
    )
