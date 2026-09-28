from datetime import datetime

import pytest

from porter.app.dispatcher import RequestDispatcher
from porter.app.inference import InferenceDecision, InferenceGate
from porter.cli import _build_request, _confirm_local_inference
from porter.core.exceptions import (
    InferenceConfirmationRequired,
    InferenceDeclined,
    NoProviderAvailable,
)
from porter.core.models import PrivacyClass, RequestContext
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
from porter.tools import ToolExecutor, ToolRegistry
from tests.fakes import FakeProvider, make_request


def fixed_now() -> datetime:
    return datetime(2026, 8, 13, 16, 57, 30)


class RecordingGapRepository:
    def __init__(self) -> None:
        self.records: list[tuple[str, bool]] = []

    def record(self, *, raw_text: str, ai_approved: bool) -> object:
        self.records.append((raw_text, ai_approved))
        return object()


class BrokenGapRepository:
    def record(self, *, raw_text: str, ai_approved: bool) -> object:
        raise RuntimeError("synthetic recognition-gap failure")


def build_dispatcher(
    provider: FakeProvider,
    *,
    additional_providers: tuple[FakeProvider, ...] = (),
    inference_gate: InferenceGate | None = None,
) -> RequestDispatcher:
    registry = ProviderRegistry((provider, *additional_providers))
    orchestrator = Orchestrator(
        PolicyEngine(),
        ModelRouter(registry),
        ProviderExecutor(registry),
    )
    handlers = IntentHandlerRegistry(
        (
            CurrentTimeHandler(now=fixed_now),
            CurrentDateHandler(now=fixed_now),
        )
    )
    return RequestDispatcher(
        DeterministicIntentExecutor(handlers),
        ToolExecutor(ToolRegistry(())),
        orchestrator,
        inference_gate=inference_gate,
    )


@pytest.mark.asyncio
async def test_unmatched_local_request_runs_without_explicit_decision() -> None:
    provider = FakeProvider(name="local", model="test", response="local answer")
    recorder = RecordingGapRepository()
    dispatcher = build_dispatcher(
        provider,
        inference_gate=InferenceGate(recorder),
    )

    result = await dispatcher.execute(
        make_request(content="population of new hampshire"),
    )

    assert result.text == "local answer"
    assert recorder.records == [("population of new hampshire", True)]
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_cloud_eligible_request_requires_explicit_decision() -> None:
    provider = FakeProvider(name="cloud", model="test", is_cloud=True)
    recorder = RecordingGapRepository()
    dispatcher = build_dispatcher(
        provider,
        inference_gate=InferenceGate(recorder),
    )

    with pytest.raises(
        InferenceConfirmationRequired,
        match="cloud inference requires explicit approval",
    ):
        await dispatcher.execute(
            make_request(
                content="explain DNS",
                privacy_class=PrivacyClass.CLOUD_ALLOWED,
                allow_cloud=True,
            ),
        )

    assert provider.calls == 0
    assert recorder.records == []


@pytest.mark.asyncio
async def test_local_request_never_falls_back_to_cloud_without_permission() -> None:
    local = FakeProvider(name="local", model="test", fail=True)
    cloud = FakeProvider(
        name="cloud",
        model="test",
        is_cloud=True,
        response="cloud answer",
    )
    recorder = RecordingGapRepository()
    dispatcher = build_dispatcher(
        local,
        additional_providers=(cloud,),
        inference_gate=InferenceGate(recorder),
    )

    with pytest.raises(NoProviderAvailable):
        await dispatcher.execute(make_request(content="hello"))

    assert local.calls == 1
    assert cloud.calls == 0
    assert recorder.records == [("hello", True)]


@pytest.mark.asyncio
async def test_explicit_cloud_approval_allows_fallback_after_local_failure() -> None:
    local = FakeProvider(name="local", model="test", fail=True)
    cloud = FakeProvider(
        name="cloud",
        model="test",
        is_cloud=True,
        response="cloud answer",
    )
    dispatcher = build_dispatcher(
        local,
        additional_providers=(cloud,),
    )
    request = make_request(
        content="hello",
        privacy_class=PrivacyClass.CLOUD_ALLOWED,
        allow_cloud=True,
    )

    result = await dispatcher.execute(
        request,
        inference_decider=lambda _request: InferenceDecision.APPROVED,
    )

    assert result.text == "cloud answer"
    assert result.provider == "cloud"
    assert local.calls == 1
    assert cloud.calls == 1


@pytest.mark.asyncio
async def test_cloud_eligible_privacy_without_permission_stays_local() -> None:
    local = FakeProvider(name="local", model="test", response="local answer")
    cloud = FakeProvider(
        name="cloud",
        model="test",
        is_cloud=True,
        response="cloud answer",
    )
    dispatcher = build_dispatcher(
        local,
        additional_providers=(cloud,),
    )

    result = await dispatcher.execute(
        make_request(
            content="hello",
            privacy_class=PrivacyClass.CLOUD_ALLOWED,
            allow_cloud=False,
        ),
    )

    assert result.text == "local answer"
    assert local.calls == 1
    assert cloud.calls == 0


@pytest.mark.asyncio
async def test_declined_unmatched_request_is_recorded_before_inference() -> None:
    provider = FakeProvider(name="local", model="test", response="unused")
    recorder = RecordingGapRepository()
    dispatcher = build_dispatcher(
        provider,
        inference_gate=InferenceGate(recorder),
    )

    with pytest.raises(InferenceDeclined):
        await dispatcher.execute(
            make_request(content="population of new hampshire"),
            inference_decider=lambda _request: InferenceDecision.DECLINED,
        )

    assert recorder.records == [("population of new hampshire", False)]
    assert provider.calls == 0


def test_cli_decline_for_cloud_request_returns_explicit_decision(monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _: "n")

    decision = _confirm_local_inference(
        _build_request("how much hard drive space is left", allow_cloud=True),
    )

    assert decision is InferenceDecision.DECLINED


def test_cli_local_request_does_not_prompt(monkeypatch) -> None:
    def fail_if_prompted(_prompt: str) -> str:
        raise AssertionError("local AI must not require confirmation")

    monkeypatch.setattr("builtins.input", fail_if_prompted)

    decision = _confirm_local_inference(_build_request("hello"))

    assert decision is InferenceDecision.APPROVED


def test_cli_cloud_request_requires_explicit_confirmation(monkeypatch) -> None:
    prompts: list[str] = []

    def approve(prompt: str) -> str:
        prompts.append(prompt)
        return ""

    monkeypatch.setattr("builtins.input", approve)

    decision = _confirm_local_inference(
        _build_request("hello", allow_cloud=True),
    )

    assert decision is InferenceDecision.APPROVED
    assert len(prompts) == 1
    assert "cloud fallback" in prompts[0]


@pytest.mark.asyncio
async def test_authorized_unmatched_request_reaches_inference() -> None:
    provider = FakeProvider(name="local", model="test", response="answer")
    recorder = RecordingGapRepository()
    dispatcher = build_dispatcher(
        provider,
        inference_gate=InferenceGate(recorder),
    )

    result = await dispatcher.execute(
        make_request(content="population of new hampshire"),
        inference_decider=lambda _request: InferenceDecision.APPROVED,
    )

    assert result.text == "answer"
    assert result.provider == "local"
    assert recorder.records == [("population of new hampshire", True)]
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_recognition_gap_failure_does_not_block_approved_inference() -> None:
    provider = FakeProvider(name="local", model="test", response="answer")
    dispatcher = build_dispatcher(
        provider,
        inference_gate=InferenceGate(BrokenGapRepository()),
    )

    result = await dispatcher.execute(
        make_request(content="population of new hampshire"),
        inference_decider=lambda _request: InferenceDecision.APPROVED,
    )

    assert result.text == "answer"
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_deterministic_request_does_not_request_inference_decision() -> None:
    provider = FakeProvider(name="local", model="test", response="unused")
    dispatcher = build_dispatcher(provider)

    def fail_if_called(request: RequestContext) -> InferenceDecision:
        raise AssertionError("deterministic execution must not ask for AI authorization")

    result = await dispatcher.execute(
        make_request(content="what time is it"),
        inference_decider=fail_if_called,
    )

    assert result.text == "4:57 PM"
    assert provider.calls == 0
