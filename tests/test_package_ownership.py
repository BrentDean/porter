from importlib.util import find_spec
from pathlib import Path

from porter.actions import plex as action_plex
from porter.actions import storage as action_storage
from porter.intents import planning as planner_intents
from porter.orchestration import Orchestrator
from porter.policy import PolicyEngine
from porter.providers import base as provider_base
from porter.providers import executor as provider_executor
from porter.providers import ollama as provider_ollama
from porter.providers import registry as provider_registry
from porter.reminders import ReminderService
from porter.reminders import intents as reminder_intents
from porter.routing import ModelRouter
from porter.service import PorterService, PorterServiceRuntime
from porter.tasks import TaskService
from porter.tasks import intents as task_intents
from porter.tasks import planning as task_planning
from porter.tray import TrayReminderSnapshot
from porter.web import create_web_app


def _source_root() -> Path:
    return Path(__file__).parents[1] / "src" / "porter"


def _source_files_containing(text: str) -> list[str]:
    source_root = _source_root()
    return [
        str(path.relative_to(source_root))
        for path in source_root.rglob("*.py")
        if text in path.read_text(encoding="utf-8")
    ]


def test_domain_implementations_use_simple_package_ownership() -> None:
    assert TaskService.__module__ == "porter.tasks.service"
    assert task_intents.ListAddItemHandler.__module__ == "porter.tasks.intents"
    assert task_planning.PlannerService.__module__ == "porter.tasks.planning"
    assert planner_intents.PlannerTodayHandler.__module__ == "porter.intents.planning"
    assert ReminderService.__module__ == "porter.reminders.service"
    assert reminder_intents.ReminderCreateHandler.__module__ == "porter.reminders.intents"


def test_removed_domain_namespaces_have_no_stale_imports() -> None:
    assert find_spec("porter.features") is None
    assert find_spec("porter.planner") is None
    assert _source_files_containing("porter.features") == []
    assert _source_files_containing("porter.planner") == []


def test_provider_implementations_use_simple_package_ownership() -> None:
    assert provider_base.InferenceProvider.__module__ == "porter.providers.base"
    assert provider_executor.ProviderExecutor.__module__ == "porter.providers.executor"
    assert provider_ollama.OllamaProvider.__module__ == "porter.providers.ollama"
    assert provider_registry.ProviderRegistry.__module__ == "porter.providers.registry"


def test_inference_namespace_is_removed() -> None:
    assert find_spec("porter.inference") is None
    assert _source_files_containing("porter.inference.providers") == []


def test_actions_use_simple_package_ownership() -> None:
    assert action_plex.PlexServiceController.__module__ == "porter.actions.plex"
    assert action_storage.StorageInventory.__module__ == "porter.actions.storage"


def test_capabilities_namespace_is_removed() -> None:
    assert find_spec("porter.capabilities") is None
    assert _source_files_containing("porter.capabilities") == []


def test_service_uses_simple_package_ownership() -> None:
    assert PorterService.__module__ == "porter.service.runtime"
    assert PorterServiceRuntime.__module__ == "porter.service.bootstrap"


def test_runtime_namespace_is_removed() -> None:
    assert find_spec("porter.runtime") is None
    assert _source_files_containing("porter.runtime") == []


def test_interfaces_use_simple_package_ownership() -> None:
    assert TrayReminderSnapshot.__module__ == "porter.tray.model"
    assert create_web_app.__module__ == "porter.web.app"


def test_interfaces_namespace_is_removed() -> None:
    assert find_spec("porter.interfaces") is None
    assert _source_files_containing("porter.interfaces") == []


def test_single_file_helpers_are_modules_not_packages() -> None:
    net_spec = find_spec("porter.net")
    notifications_spec = find_spec("porter.notifications")

    assert net_spec is not None
    assert net_spec.submodule_search_locations is None
    assert notifications_spec is not None
    assert notifications_spec.submodule_search_locations is None


def test_policy_routing_and_orchestration_are_flat_modules() -> None:
    policy_spec = find_spec("porter.policy")
    routing_spec = find_spec("porter.routing")
    orchestration_spec = find_spec("porter.orchestration")

    assert policy_spec is not None
    assert policy_spec.submodule_search_locations is None
    assert routing_spec is not None
    assert routing_spec.submodule_search_locations is None
    assert orchestration_spec is not None
    assert orchestration_spec.submodule_search_locations is None

    assert PolicyEngine.__module__ == "porter.policy"
    assert ModelRouter.__module__ == "porter.routing"
    assert Orchestrator.__module__ == "porter.orchestration"

    source_root = _source_root()
    assert not (source_root / "policy").exists()
    assert not (source_root / "routing").exists()
    assert not (source_root / "core" / "orchestrator.py").exists()
    assert _source_files_containing("porter.policy.engine") == []
    assert _source_files_containing("porter.policy.models") == []
    assert _source_files_containing("porter.routing.router") == []
    assert _source_files_containing("porter.routing.models") == []
    assert _source_files_containing("porter.core.orchestrator") == []
