from __future__ import annotations

import asyncio
import io
import json
import logging
from dataclasses import replace
from pathlib import Path

import pytest

from porter.app import build_application
from porter.core.lifecycle import ExecutionOutcome
from porter.core.models import ExecutionPath
from porter.service import PorterService
from porter.telemetry.structured_logging import (
    JsonEventFormatter,
    LoggingLifecycle,
    _configured_level,
    emit_event,
)
from tests.fakes import make_request


def _json_logger(stream: io.StringIO) -> logging.Logger:
    logger = logging.Logger("porter.test.operations", level=logging.DEBUG)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonEventFormatter())
    logger.addHandler(handler)
    return logger


def _events(stream: io.StringIO) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in stream.getvalue().splitlines()
        if line.strip()
    ]


def test_request_logs_are_structured_and_exclude_sensitive_request_content() -> None:
    stream = io.StringIO()
    lifecycle = LoggingLifecycle(_json_logger(stream))
    request = replace(
        make_request(content="secret prompt that must not be logged"),
        principal_id="private-principal",
        session_id="private-session",
    )

    lifecycle.request_started(request)
    lifecycle.route_selected(request.request_id, "local_only_route")
    lifecycle.execution_path_selected(
        request.request_id,
        ExecutionPath.DETERMINISTIC,
    )
    lifecycle.request_finished(
        request.request_id,
        ExecutionOutcome.SUCCEEDED,
        latency_ms=17,
    )

    events = _events(stream)
    assert [event["event"] for event in events] == [
        "request.started",
        "route.selected",
        "request.path_selected",
        "request.finished",
    ]
    assert events[0]["request_id"] == request.request_id
    assert events[0]["source"] == "cli"
    assert events[0]["privacy_class"] == "local_only"
    assert events[-1]["execution_path"] == "deterministic"
    assert events[-1]["latency_ms"] == 17
    assert events[-1]["outcome"] == "succeeded"
    assert events[-1]["level"] == "info"

    payload = stream.getvalue()
    assert "secret prompt that must not be logged" not in payload
    assert "private-principal" not in payload
    assert "private-session" not in payload


def test_provider_failure_and_fallback_are_structured_without_error_messages() -> None:
    stream = io.StringIO()
    lifecycle = LoggingLifecycle(_json_logger(stream))
    request = make_request(content="inference request")

    lifecycle.request_started(request)
    lifecycle.provider_attempt_started(
        request_id=request.request_id,
        attempt_index=1,
        provider="local",
        model="local-model",
    )
    lifecycle.provider_attempt_finished(
        request_id=request.request_id,
        attempt_index=1,
        outcome=ExecutionOutcome.FAILED,
        latency_ms=25,
        error_classification="ProviderError",
    )
    lifecycle.provider_attempt_started(
        request_id=request.request_id,
        attempt_index=2,
        provider="cloud",
        model="cloud-model",
    )
    lifecycle.provider_attempt_finished(
        request_id=request.request_id,
        attempt_index=2,
        outcome=ExecutionOutcome.SUCCEEDED,
        latency_ms=40,
        input_tokens=10,
        output_tokens=5,
        estimated_cost_microusd=12,
    )
    lifecycle.request_finished(
        request.request_id,
        ExecutionOutcome.SUCCEEDED,
        latency_ms=70,
    )

    events = _events(stream)
    failed = next(
        event
        for event in events
        if event["event"] == "provider.attempt.finished"
        and event["attempt_index"] == 1
    )
    fallback = next(
        event
        for event in events
        if event["event"] == "provider.fallback.started"
    )
    succeeded = next(
        event
        for event in events
        if event["event"] == "provider.attempt.finished"
        and event["attempt_index"] == 2
    )

    assert failed["level"] == "error"
    assert failed["error_classification"] == "ProviderError"
    assert failed["provider"] == "local"
    assert fallback["from_provider"] == "local"
    assert fallback["to_provider"] == "cloud"
    assert fallback["attempt_index"] == 2
    assert succeeded["fallback"] is True
    assert succeeded["provider"] == "cloud"
    assert succeeded["input_tokens"] == 10
    assert succeeded["output_tokens"] == 5
    assert succeeded["estimated_cost_microusd"] == 12
    assert "synthetic provider failure" not in stream.getvalue()


def test_tool_failure_logs_tool_error_classification() -> None:
    stream = io.StringIO()
    lifecycle = LoggingLifecycle(_json_logger(stream))
    request = make_request()

    lifecycle.request_started(request)
    lifecycle.tool_attempt_started(
        request_id=request.request_id,
        attempt_index=1,
        tool="qalculate",
    )
    lifecycle.tool_attempt_finished(
        request_id=request.request_id,
        attempt_index=1,
        outcome=ExecutionOutcome.FAILED,
        latency_ms=9,
        error_classification="RuntimeError",
    )

    event = _events(stream)[-1]
    assert event["event"] == "tool.attempt.finished"
    assert event["level"] == "error"
    assert event["tool"] == "qalculate"
    assert event["error_classification"] == "RuntimeError"
    assert event["latency_ms"] == 9


@pytest.mark.asyncio
async def test_logging_observer_failure_cannot_change_request_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_emit(*args, **kwargs) -> None:
        raise RuntimeError("synthetic logging failure")

    monkeypatch.setattr(
        "porter.telemetry.structured_logging.emit_event",
        fail_emit,
    )
    application = build_application(
        env={"PORTER_DATA_DIR": str(tmp_path)},
        home=tmp_path,
    )

    result = await application.dispatcher.execute(
        make_request(content="what time is it")
    )

    assert result.path is ExecutionPath.DETERMINISTIC


@pytest.mark.asyncio
async def test_service_emits_start_and_stop_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop_event = asyncio.Event()
    events: list[tuple[str, dict[str, object]]] = []

    class OnePassRunner:
        async def run_once(self) -> None:
            stop_event.set()

    def capture(event: str, **fields: object) -> None:
        fields.pop("level", None)
        events.append((event, fields))

    monkeypatch.setattr(
        "porter.service.runtime.emit_event",
        capture,
    )

    service = PorterService(
        OnePassRunner(),  # type: ignore[arg-type]
        poll_interval_seconds=2.0,
    )
    await service.run(stop_event)

    assert events == [
        ("service.started", {"poll_interval_seconds": 2.0}),
        ("service.stopped", {}),
    ]


def test_emit_event_is_best_effort_when_logger_raises() -> None:
    class BrokenLogger:
        def log(self, *args, **kwargs) -> None:
            raise RuntimeError("synthetic handler failure")

    emit_event(
        "synthetic.event",
        logger=BrokenLogger(),  # type: ignore[arg-type]
        request_id="request-1",
    )


@pytest.mark.asyncio
async def test_service_failure_logs_error_class_without_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, dict[str, object]]] = []

    class FailingRunner:
        async def run_once(self) -> None:
            raise RuntimeError("sensitive failure detail")

    def capture(event: str, **fields: object) -> None:
        events.append((event, fields))

    monkeypatch.setattr(
        "porter.service.runtime.emit_event",
        capture,
    )

    service = PorterService(FailingRunner())  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="sensitive failure detail"):
        await service.run(asyncio.Event())

    assert events == [
        ("service.started", {"poll_interval_seconds": 1.0}),
        (
            "service.failed",
            {
                "level": logging.ERROR,
                "error_classification": "RuntimeError",
            },
        ),
        ("service.stopped", {}),
    ]
    assert "sensitive failure detail" not in repr(events)


def test_structured_log_level_uses_caller_default() -> None:
    assert _configured_level({}, default_level="WARNING") == logging.WARNING


def test_environment_log_level_overrides_caller_default() -> None:
    assert (
        _configured_level(
            {"PORTER_LOG_LEVEL": "INFO"},
            default_level="WARNING",
        )
        == logging.INFO
    )
