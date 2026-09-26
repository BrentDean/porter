from datetime import datetime

import pytest

from porter.core.exceptions import ActionNotAuthorized
from porter.core.models import Message, RequestContext, RequestSource
from porter.intents import (
    CurrentDateHandler,
    CurrentTimeHandler,
    DeterministicIntentExecutor,
    IntentHandler,
    IntentHandlerRegistry,
    IntentResult,
    RecognizedIntent,
)
from porter.policy import ActionEffect
from tests.fakes import make_request


def fixed_now() -> datetime:
    return datetime(2026, 8, 13, 16, 57, 30)


def build_executor() -> DeterministicIntentExecutor:
    registry = IntentHandlerRegistry(
        (
            CurrentTimeHandler(now=fixed_now),
            CurrentDateHandler(now=fixed_now),
        )
    )
    return DeterministicIntentExecutor(registry)


class RecordingSystemWriteHandler(IntentHandler):
    intent_name = "HassGetCurrentTime"
    action_effect = ActionEffect.SYSTEM_WRITE

    def __init__(self) -> None:
        self.calls = 0

    async def handle(
        self,
        request: RequestContext,
        intent: RecognizedIntent,
    ) -> IntentResult:
        self.calls += 1
        return IntentResult(text="executed", data={})


@pytest.mark.asyncio
async def test_executes_current_time_intent() -> None:
    result = await build_executor().execute(
        make_request(content="what time is it")
    )

    assert result == IntentResult(
        text="4:57 PM",
        data={"time": fixed_now().time()},
    )


@pytest.mark.asyncio
async def test_executes_current_date_intent() -> None:
    result = await build_executor().execute(
        make_request(content="what is the date today")
    )

    assert result == IntentResult(
        text="Thursday, August 13, 2026",
        data={"date": fixed_now().date()},
    )


@pytest.mark.asyncio
async def test_unmatched_request_returns_none() -> None:
    result = await build_executor().execute(
        make_request(
            content="explain why dns uses both udp and tcp"
        )
    )

    assert result is None


@pytest.mark.asyncio
async def test_uses_latest_user_message() -> None:
    request = RequestContext(
        messages=(
            Message(role="user", content="what is the date today"),
            Message(role="assistant", content="previous response"),
            Message(role="user", content="what time is it"),
        ),
        principal_id="test-user",
        source=RequestSource.CLI,
    )

    result = await build_executor().execute(request)

    assert result == IntentResult(
        text="4:57 PM",
        data={"time": fixed_now().time()},
    )


@pytest.mark.asyncio
async def test_request_without_user_message_is_unmatched() -> None:
    request = RequestContext(
        messages=(
            Message(role="assistant", content="previous response"),
        ),
        principal_id="test-user",
        source=RequestSource.CLI,
    )

    result = await build_executor().execute(request)

    assert result is None


@pytest.mark.asyncio
async def test_system_write_is_denied_before_handler_execution() -> None:
    handler = RecordingSystemWriteHandler()
    executor = DeterministicIntentExecutor(IntentHandlerRegistry((handler,)))
    request = RequestContext(
        messages=(Message(role="user", content="what time is it"),),
        principal_id="test-user",
        source=RequestSource.AUTOMATION,
    )

    with pytest.raises(ActionNotAuthorized, match="not authorized from automation"):
        await executor.execute(request)

    assert handler.calls == 0


@pytest.mark.asyncio
async def test_system_write_from_cli_reaches_handler() -> None:
    handler = RecordingSystemWriteHandler()
    executor = DeterministicIntentExecutor(IntentHandlerRegistry((handler,)))

    result = await executor.execute(make_request(content="what time is it"))

    assert result == IntentResult(text="executed", data={})
    assert handler.calls == 1
