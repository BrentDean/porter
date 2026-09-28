from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TextIO

from porter.core.lifecycle import CacheLookupOutcome, ExecutionOutcome, RuntimeLifecycle
from porter.core.models import ExecutionPath, RequestContext

_LOGGER_NAME = "porter.operations"
_LOG_LEVEL_ENV = "PORTER_LOG_LEVEL"
_STRUCTURED_HANDLER_MARKER = "_porter_structured_handler"


class JsonEventFormatter(logging.Formatter):
    """Format Porter operational events as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": getattr(record, "porter_event", record.getMessage()),
        }
        fields = getattr(record, "porter_fields", {})
        if isinstance(fields, Mapping):
            payload.update(
                {
                    str(key): value
                    for key, value in fields.items()
                    if value is not None
                }
            )
        return json.dumps(
            payload,
            separators=(",", ":"),
            sort_keys=True,
        )


def _configured_level(
    env: Mapping[str, str],
    *,
    default_level: str,
) -> int:
    raw = env.get(_LOG_LEVEL_ENV, default_level).strip().upper()
    levels = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    try:
        return levels[raw]
    except KeyError as exc:
        choices = ", ".join(levels)
        raise ValueError(
            f"{_LOG_LEVEL_ENV} must be one of: {choices}"
        ) from exc


def operational_logger() -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    logger.propagate = False
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    return logger


def configure_structured_logging(
    *,
    env: Mapping[str, str] | None = None,
    stream: TextIO | None = None,
    default_level: str = "INFO",
) -> logging.Logger:
    """Configure Porter's dedicated operational logger exactly once."""

    environment = os.environ if env is None else env
    logger = operational_logger()
    logger.setLevel(
        _configured_level(
            environment,
            default_level=default_level,
        )
    )
    logger.propagate = False

    handler = next(
        (
            candidate
            for candidate in logger.handlers
            if getattr(candidate, _STRUCTURED_HANDLER_MARKER, False)
        ),
        None,
    )
    if handler is None:
        handler = logging.StreamHandler(stream)
        setattr(handler, _STRUCTURED_HANDLER_MARKER, True)
        handler.setFormatter(JsonEventFormatter())
        logger.addHandler(handler)

    return logger


def emit_event(
    event: str,
    *,
    level: int = logging.INFO,
    logger: logging.Logger | None = None,
    **fields: object,
) -> None:
    target = logger or operational_logger()
    try:
        target.log(
            level,
            event,
            extra={
                "porter_event": event,
                "porter_fields": fields,
            },
        )
    except Exception:
        return


@dataclass(slots=True)
class _RequestLogState:
    source: str
    path: str = "unselected"
    last_provider: str | None = None


@dataclass(frozen=True, slots=True)
class _ProviderLogState:
    provider: str
    model: str
    fallback: bool


class LoggingLifecycle(RuntimeLifecycle):
    """Translate runtime lifecycle events into privacy-bounded JSON logs."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or operational_logger()
        self._requests: dict[str, _RequestLogState] = {}
        self._provider_attempts: dict[tuple[str, int], _ProviderLogState] = {}
        self._tool_attempts: dict[tuple[str, int], str] = {}

    def request_started(self, request: RequestContext) -> None:
        self._requests[request.request_id] = _RequestLogState(
            source=request.source.value
        )
        self._emit(
            "request.started",
            request_id=request.request_id,
            source=request.source.value,
            privacy_class=request.privacy_class.value,
            allow_cloud=request.allow_cloud,
        )

    def route_selected(
        self,
        request_id: str,
        route_reason: str,
    ) -> None:
        self._emit(
            "route.selected",
            request_id=request_id,
            route_reason=route_reason,
        )

    def execution_path_selected(
        self,
        request_id: str,
        execution_path: ExecutionPath,
    ) -> None:
        state = self._requests.get(request_id)
        if state is not None:
            state.path = execution_path.value
        self._emit(
            "request.path_selected",
            request_id=request_id,
            execution_path=execution_path.value,
        )

    def tool_attempt_started(
        self,
        *,
        request_id: str,
        attempt_index: int,
        tool: str,
    ) -> None:
        self._tool_attempts[(request_id, attempt_index)] = tool
        self._emit(
            "tool.attempt.started",
            request_id=request_id,
            attempt_index=attempt_index,
            tool=tool,
        )

    def tool_attempt_finished(
        self,
        *,
        request_id: str,
        attempt_index: int,
        outcome: ExecutionOutcome,
        latency_ms: int,
        error_classification: str | None = None,
    ) -> None:
        tool = self._tool_attempts.pop(
            (request_id, attempt_index),
            "unknown",
        )
        self._emit(
            "tool.attempt.finished",
            level=_outcome_level(outcome),
            request_id=request_id,
            attempt_index=attempt_index,
            tool=tool,
            outcome=outcome.value,
            latency_ms=latency_ms,
            error_classification=error_classification,
        )

    def provider_attempt_started(
        self,
        *,
        request_id: str,
        attempt_index: int,
        provider: str,
        model: str,
    ) -> None:
        request_state = self._requests.get(request_id)
        previous_provider = (
            request_state.last_provider
            if request_state is not None
            else None
        )
        fallback = attempt_index > 1
        self._provider_attempts[(request_id, attempt_index)] = _ProviderLogState(
            provider=provider,
            model=model,
            fallback=fallback,
        )
        if request_state is not None:
            request_state.last_provider = provider

        if fallback:
            self._emit(
                "provider.fallback.started",
                request_id=request_id,
                attempt_index=attempt_index,
                from_provider=previous_provider,
                to_provider=provider,
                model=model,
            )

        self._emit(
            "provider.attempt.started",
            request_id=request_id,
            attempt_index=attempt_index,
            provider=provider,
            model=model,
            fallback=fallback,
        )

    def provider_attempt_finished(
        self,
        *,
        request_id: str,
        attempt_index: int,
        outcome: ExecutionOutcome,
        latency_ms: int,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        estimated_cost_microusd: int | None = None,
        error_classification: str | None = None,
    ) -> None:
        state = self._provider_attempts.pop(
            (request_id, attempt_index),
            _ProviderLogState(
                provider="unknown",
                model="unknown",
                fallback=attempt_index > 1,
            ),
        )
        self._emit(
            "provider.attempt.finished",
            level=_outcome_level(outcome),
            request_id=request_id,
            attempt_index=attempt_index,
            provider=state.provider,
            model=state.model,
            fallback=state.fallback,
            outcome=outcome.value,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_microusd=estimated_cost_microusd,
            error_classification=error_classification,
        )

    def cache_lookup_finished(
        self,
        *,
        request_id: str,
        provider: str,
        outcome: CacheLookupOutcome,
    ) -> None:
        self._emit(
            "cache.lookup.finished",
            request_id=request_id,
            provider=provider,
            outcome=outcome.value,
        )

    def request_finished(
        self,
        request_id: str,
        outcome: ExecutionOutcome,
        *,
        latency_ms: int | None = None,
    ) -> None:
        state = self._requests.pop(
            request_id,
            _RequestLogState(source="unknown"),
        )
        self._emit(
            "request.finished",
            level=_outcome_level(outcome),
            request_id=request_id,
            source=state.source,
            execution_path=state.path,
            outcome=outcome.value,
            latency_ms=latency_ms,
        )

    def _emit(
        self,
        event: str,
        *,
        level: int = logging.INFO,
        **fields: object,
    ) -> None:
        emit_event(
            event,
            level=level,
            logger=self._logger,
            **fields,
        )


def _outcome_level(outcome: ExecutionOutcome) -> int:
    if outcome is ExecutionOutcome.FAILED:
        return logging.ERROR
    return logging.INFO
