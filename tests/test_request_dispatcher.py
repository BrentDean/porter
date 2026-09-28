from datetime import datetime

import pytest

from porter.app.dispatcher import RequestDispatcher
from porter.app.inference import InferenceDecision
from porter.core.models import (
    Capability,
    ExecutionPath,
    RequestContext,
    RequestResult,
)
from porter.intents import (
    CurrentDateHandler,
    CurrentTimeHandler,
    DeterministicIntentExecutor,
    IntentHandlerRegistry,
)
from porter.orchestration import Orchestrator
from porter.policy import PolicyEngine
from porter.providers.executor import ProviderExecutor
from porter.providers.registry import ProviderRegistry
from porter.routing import ModelRouter
from porter.tools import Tool, ToolExecutor, ToolRegistry, ToolResult
from tests.fakes import FakeProvider, make_request


def fixed_now() -> datetime:
    return datetime(2026, 8, 13, 16, 57, 30)


class StructuredTool(Tool):
    name = "structured"

    def supports(self, request: RequestContext) -> bool:
        return any(
            message.role == "user" and message.content == "use structured tool"
            for message in request.messages
        )

    async def execute(self, request: RequestContext) -> ToolResult:
        return ToolResult(
            text="structured result",
            data={"answer": 42},
        )


def build_dispatcher(
    provider: FakeProvider,
    *,
    tools: tuple[Tool, ...] = (),
) -> RequestDispatcher:
    provider_registry = ProviderRegistry((provider,))

    orchestrator = Orchestrator(
        PolicyEngine(),
        ModelRouter(provider_registry),
        ProviderExecutor(provider_registry),
    )

    handler_registry = IntentHandlerRegistry(
        (
            CurrentTimeHandler(now=fixed_now),
            CurrentDateHandler(now=fixed_now),
        )
    )

    tool_registry = ToolRegistry(tools)

    return RequestDispatcher(
        DeterministicIntentExecutor(handler_registry),
        ToolExecutor(tool_registry),
        orchestrator,
    )


@pytest.mark.asyncio
async def test_time_request_uses_deterministic_path() -> None:
    provider = FakeProvider(
        name="local",
        model="test",
        response="should not be used",
    )

    result = await build_dispatcher(provider).execute(
        make_request(content="what time is it")
    )

    assert result == RequestResult(
        text="4:57 PM",
        path=ExecutionPath.DETERMINISTIC,
        data={"time": fixed_now().time()},
    )
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_date_request_uses_deterministic_path() -> None:
    provider = FakeProvider(
        name="local",
        model="test",
        response="should not be used",
    )

    result = await build_dispatcher(provider).execute(
        make_request(content="what is the date today")
    )

    assert result == RequestResult(
        text="Thursday, August 13, 2026",
        path=ExecutionPath.DETERMINISTIC,
        data={"date": fixed_now().date()},
    )
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_tool_path_preserves_structured_data() -> None:
    provider = FakeProvider(
        name="local",
        model="test",
        response="should not be used",
    )

    result = await build_dispatcher(
        provider,
        tools=(StructuredTool(),),
    ).execute(make_request(content="use structured tool"))

    assert result == RequestResult(
        text="structured result",
        path=ExecutionPath.TOOL,
        tool="structured",
        data={"answer": 42},
    )
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_unmatched_request_falls_back_to_inference_when_approved() -> None:
    provider = FakeProvider(
        name="local",
        model="test",
        response="DNS explanation",
    )

    result = await build_dispatcher(provider).execute(
        make_request(
            content="explain why dns uses both udp and tcp"
        ),
        inference_decider=lambda _request: InferenceDecision.APPROVED,
    )

    assert result == RequestResult(
        text="DNS explanation",
        path=ExecutionPath.INFERENCE,
        provider="local",
        model="test",
    )
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_non_text_only_request_skips_deterministic_path() -> None:
    provider = FakeProvider(
        name="vision",
        model="vision-test",
        capabilities=frozenset(
            {
                Capability.TEXT,
                Capability.VISION,
            }
        ),
        response="vision result",
    )

    result = await build_dispatcher(provider).execute(
        make_request(
            content="what time is it",
            capabilities_required=frozenset(
                {
                    Capability.TEXT,
                    Capability.VISION,
                }
            ),
        ),
        inference_decider=lambda _request: InferenceDecision.APPROVED,
    )

    assert result.path is ExecutionPath.INFERENCE
    assert result.provider == "vision"
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_request_result_data_is_read_only() -> None:
    provider = FakeProvider(
        name="local",
        model="test",
        response="should not be used",
    )

    result = await build_dispatcher(provider).execute(
        make_request(content="what time is it")
    )

    with pytest.raises(TypeError):
        result.data["time"] = "changed"  # type: ignore[index]
