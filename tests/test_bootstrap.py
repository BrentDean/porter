from porter.actions.storage import StorageInventory
from porter.app.bootstrap import build_application
from porter.app.dispatcher import RequestDispatcher
from porter.intents import (
    CompositeIntentRecognitionContextProvider,
    DeterministicIntentExecutor,
    IntentHandlerRegistry,
)
from porter.memory import MemoryRepository
from porter.providers.ollama import OllamaProvider
from porter.reminders import ReminderService, SqliteReminderRepository
from porter.tasks import SqliteTaskRepository, TaskService
from porter.tasks.planning import PlannerService
from porter.telemetry.repository import TelemetryRepository
from porter.training import RecognitionGapRepository, TrainingCorpusRepository


def test_build_application_assembles_shared_application_graph(tmp_path) -> None:
    application = build_application(
        env={"PORTER_DATA_DIR": str(tmp_path)},
        home=tmp_path,
    )

    assert application.config.storage.data_dir == tmp_path
    assert application.config.storage.database_path == tmp_path / "porter.db"
    assert application.database.healthcheck()
    assert application.migration_runner.current_version() == 14
    assert application.provider_registry.all() == ()
    assert isinstance(application.telemetry_repository, TelemetryRepository)
    assert isinstance(application.memory_repository, MemoryRepository)
    assert isinstance(application.task_repository, SqliteTaskRepository)
    assert isinstance(application.task_service, TaskService)
    assert isinstance(application.planner_service, PlannerService)
    assert isinstance(
        application.reminder_repository,
        SqliteReminderRepository,
    )
    assert isinstance(application.reminder_service, ReminderService)
    assert isinstance(application.training_repository, TrainingCorpusRepository)
    assert isinstance(application.recognition_gap_repository, RecognitionGapRepository)
    assert isinstance(application.storage_inventory, StorageInventory)
    assert isinstance(
        application.intent_context_provider,
        CompositeIntentRecognitionContextProvider,
    )


def test_build_application_registers_configured_ollama(tmp_path) -> None:
    application = build_application(
        env={
            "PORTER_DATA_DIR": str(tmp_path),
            "PORTER_OLLAMA_MODEL": "qwen3:8b",
        },
        home=tmp_path,
    )

    provider = application.provider_registry.get("ollama")

    assert isinstance(provider, OllamaProvider)
    assert provider.model == "qwen3:8b"


def test_build_application_assembles_deterministic_request_path(
    tmp_path,
) -> None:
    application = build_application(
        env={"PORTER_DATA_DIR": str(tmp_path)},
        home=tmp_path,
    )

    assert isinstance(
        application.intent_handler_registry,
        IntentHandlerRegistry,
    )
    assert (
        application.intent_handler_registry.supported_intents()
        == frozenset(
            {
                "HassGetCurrentTime",
                "HassGetCurrentDate",
                "HassListAddItem",
                "HassListCompleteItem",
                "HassListRemoveItem",
                "PorterPlannerToday",
                "PorterPlannerOverdue",
                "PorterPlannerUpcoming",
                "PorterPlannerUnscheduled",
                "PorterReminderCreate",
                "PorterReminderList",
                "PorterReminderCancel",
                "PorterTimerCreate",
                "PorterTimerList",
                "PorterTimerCancel",
                "PorterMemoryRemember",
                "PorterMemoryList",
                "PorterMemoryForget",
                "PorterPlexStart",
                "PorterPlexStop",
                "PorterPlexRestart",
                "PorterStorageMounted",
                "PorterStorageUnmounted",
                "PorterStorageLayout",
                "PorterDiskUsage",
                "PorterDiskPressure",
            }
        )
    )
    assert isinstance(
        application.deterministic_executor,
        DeterministicIntentExecutor,
    )
    assert isinstance(
        application.dispatcher,
        RequestDispatcher,
    )
