import pytest

from porter.core.models import RequestContext
from porter.intents import (
    IntentHandler,
    IntentHandlerRegistry,
    IntentResult,
    RecognizedIntent,
)
from porter.policy import ActionEffect
from tests.fakes import make_request


class FakeIntentHandler(IntentHandler):
    action_effect = ActionEffect.READ

    def __init__(self, intent_name: str) -> None:
        self.intent_name = intent_name
        self.calls = 0

    async def handle(
        self,
        request: RequestContext,
        intent: RecognizedIntent,
    ) -> IntentResult:
        self.calls += 1
        return IntentResult(
            text=f"handled {intent.name}",
            data={"intent": intent.name},
        )


class UnclassifiedIntentHandler(IntentHandler):
    intent_name = "PorterUnclassifiedIntent"

    async def handle(
        self,
        request: RequestContext,
        intent: RecognizedIntent,
    ) -> IntentResult:
        return IntentResult(text="unexpected")


def test_duplicate_intent_handler_names_are_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="intent handler names must be unique",
    ):
        IntentHandlerRegistry(
            (
                FakeIntentHandler("same"),
                FakeIntentHandler("same"),
            )
        )


def test_registry_rejects_unclassified_handler() -> None:
    with pytest.raises(ValueError, match="no action classification"):
        IntentHandlerRegistry((UnclassifiedIntentHandler(),))


def test_registry_returns_handler_by_intent_name() -> None:
    handler = FakeIntentHandler("HassGetCurrentTime")
    registry = IntentHandlerRegistry((handler,))

    assert registry.get("HassGetCurrentTime") is handler


def test_registry_rejects_unknown_intent_name() -> None:
    registry = IntentHandlerRegistry()

    with pytest.raises(KeyError):
        registry.get("missing")


def test_registry_returns_all_handlers() -> None:
    first = FakeIntentHandler("first")
    second = FakeIntentHandler("second")
    registry = IntentHandlerRegistry((first, second))

    assert registry.all() == (first, second)


def test_registry_exposes_supported_intents() -> None:
    registry = IntentHandlerRegistry(
        (
            FakeIntentHandler("HassGetCurrentTime"),
            FakeIntentHandler("HassGetCurrentDate"),
        )
    )

    assert registry.supported_intents() == frozenset(
        {
            "HassGetCurrentTime",
            "HassGetCurrentDate",
        }
    )


@pytest.mark.asyncio
async def test_handler_contract_returns_intent_result() -> None:
    handler = FakeIntentHandler("example")
    intent = RecognizedIntent(
        name="example",
        slots={"name": "lamp"},
    )

    result = await handler.handle(make_request(), intent)

    assert result == IntentResult(
        text="handled example",
        data={"intent": "example"},
    )
    assert handler.calls == 1


def test_intent_result_data_is_read_only() -> None:
    result = IntentResult(
        text="done",
        data={"value": 1},
    )

    with pytest.raises(TypeError):
        result.data["value"] = 2  # type: ignore[index]
