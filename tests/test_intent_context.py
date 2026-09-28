from pathlib import Path

from porter.core.models import Message, RequestContext, RequestSource
from porter.intents import (
    CompositeIntentRecognitionContextProvider,
    IntentRecognitionContext,
    IntentSlotValue,
    TaskIntentRecognitionContextProvider,
)
from porter.storage.database import Database
from porter.storage.migrations import MigrationRunner
from porter.tasks import SqliteTaskRepository, TaskService


class StaticContextProvider:
    def context_for(
        self,
        request: RequestContext,
    ) -> IntentRecognitionContext:
        return IntentRecognitionContext(
            slot_values={
                "name": (
                    IntentSlotValue(
                        text="Desk lamp",
                        value="Desk lamp",
                        context={"domain": "light"},
                    ),
                )
            }
        )


def _service(tmp_path: Path) -> TaskService:
    database = Database(tmp_path / "porter.db")
    MigrationRunner(database).apply_all()
    identifiers = iter(("alice-list", "bob-list"))
    return TaskService(
        SqliteTaskRepository(database),
        id_generator=lambda: next(identifiers),
    )


def _request(principal_id: str) -> RequestContext:
    return RequestContext(
        messages=(Message(role="user", content="test"),),
        principal_id=principal_id,
        source=RequestSource.CLI,
    )


def test_task_context_exposes_only_current_principal_lists(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    service.create_list("alice", "Shopping")
    service.create_list("bob", "Private")

    provider = TaskIntentRecognitionContextProvider(service)
    context = provider.context_for(_request("alice"))

    assert tuple(context.slot_values) == ("name",)
    assert len(context.slot_values["name"]) == 1
    slot = context.slot_values["name"][0]
    assert slot.text == "Shopping"
    assert slot.value == "Shopping"
    assert slot.context == {"domain": "todo"}


def test_composite_context_provider_merges_slot_values(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    service.create_list("alice", "Shopping")

    provider = CompositeIntentRecognitionContextProvider(
        (
            StaticContextProvider(),
            TaskIntentRecognitionContextProvider(service),
        )
    )
    context = provider.context_for(_request("alice"))

    assert [value.text for value in context.slot_values["name"]] == [
        "Desk lamp",
        "Shopping",
    ]
