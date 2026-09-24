from __future__ import annotations

from porter.core.lifecycle import CacheLookupOutcome, ExecutionOutcome, RuntimeLifecycle
from porter.core.models import ExecutionPath, RequestContext
from porter.telemetry.repository import TelemetryRepository


class TelemetryLifecycle(RuntimeLifecycle):
    """Translates runtime lifecycle events into telemetry persistence."""

    def __init__(self, repository: TelemetryRepository) -> None:
        self._repository = repository

    def request_started(self, request: RequestContext) -> None:
        self._repository.start_request(request)

    def route_selected(
        self,
        request_id: str,
        route_reason: str,
    ) -> None:
        self._repository.set_route(
            request_id,
            route_reason,
        )

    def execution_path_selected(
        self,
        request_id: str,
        execution_path: ExecutionPath,
    ) -> None:
        self._repository.set_execution_path(
            request_id,
            execution_path,
        )

    def tool_attempt_started(
        self,
        *,
        request_id: str,
        attempt_index: int,
        tool: str,
    ) -> None:
        self._repository.start_tool_attempt(
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
        self._repository.finish_tool_attempt(
            request_id=request_id,
            attempt_index=attempt_index,
            outcome=outcome,
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
        self._repository.start_provider_attempt(
            request_id=request_id,
            attempt_index=attempt_index,
            provider=provider,
            model=model,
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
        self._repository.finish_provider_attempt(
            request_id=request_id,
            attempt_index=attempt_index,
            outcome=outcome,
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
        return None

    def request_finished(
        self,
        request_id: str,
        outcome: ExecutionOutcome,
        *,
        latency_ms: int | None = None,
    ) -> None:
        self._repository.finish_request(
            request_id,
            outcome,
            latency_ms=latency_ms,
        )
