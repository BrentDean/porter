from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Protocol

from porter.core.models import ExecutionPath, RequestContext


class ExecutionOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CacheLookupOutcome(StrEnum):
    HIT = "hit"
    MISS = "miss"
    ERROR = "error"


class RuntimeLifecycle(Protocol):
    """Observer contract for runtime lifecycle events."""

    def request_started(self, request: RequestContext) -> None:
        ...

    def route_selected(
        self,
        request_id: str,
        route_reason: str,
    ) -> None:
        ...

    def execution_path_selected(
        self,
        request_id: str,
        execution_path: ExecutionPath,
    ) -> None:
        ...

    def tool_attempt_started(
        self,
        *,
        request_id: str,
        attempt_index: int,
        tool: str,
    ) -> None:
        ...

    def tool_attempt_finished(
        self,
        *,
        request_id: str,
        attempt_index: int,
        outcome: ExecutionOutcome,
        latency_ms: int,
        error_classification: str | None = None,
    ) -> None:
        ...

    def provider_attempt_started(
        self,
        *,
        request_id: str,
        attempt_index: int,
        provider: str,
        model: str,
    ) -> None:
        ...

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
        ...

    def cache_lookup_finished(
        self,
        *,
        request_id: str,
        provider: str,
        outcome: CacheLookupOutcome,
    ) -> None:
        ...

    def request_finished(
        self,
        request_id: str,
        outcome: ExecutionOutcome,
        *,
        latency_ms: int | None = None,
    ) -> None:
        ...


class NullRuntimeLifecycle:
    """Explicit no-op lifecycle observer."""

    def request_started(self, request: RequestContext) -> None:
        return None

    def route_selected(
        self,
        request_id: str,
        route_reason: str,
    ) -> None:
        return None

    def execution_path_selected(
        self,
        request_id: str,
        execution_path: ExecutionPath,
    ) -> None:
        return None

    def tool_attempt_started(
        self,
        *,
        request_id: str,
        attempt_index: int,
        tool: str,
    ) -> None:
        return None

    def tool_attempt_finished(
        self,
        *,
        request_id: str,
        attempt_index: int,
        outcome: ExecutionOutcome,
        latency_ms: int,
        error_classification: str | None = None,
    ) -> None:
        return None

    def provider_attempt_started(
        self,
        *,
        request_id: str,
        attempt_index: int,
        provider: str,
        model: str,
    ) -> None:
        return None

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
        return None

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
        return None


class SafeRuntimeLifecycle:
    """Prevents observer failures from changing runtime behavior."""

    def __init__(self, lifecycle: RuntimeLifecycle) -> None:
        self._lifecycle = lifecycle

    def request_started(self, request: RequestContext) -> None:
        self._best_effort(lambda: self._lifecycle.request_started(request))

    def route_selected(
        self,
        request_id: str,
        route_reason: str,
    ) -> None:
        self._best_effort(
            lambda: self._lifecycle.route_selected(request_id, route_reason)
        )

    def execution_path_selected(
        self,
        request_id: str,
        execution_path: ExecutionPath,
    ) -> None:
        self._best_effort(
            lambda: self._lifecycle.execution_path_selected(
                request_id,
                execution_path,
            )
        )

    def tool_attempt_started(
        self,
        *,
        request_id: str,
        attempt_index: int,
        tool: str,
    ) -> None:
        self._best_effort(
            lambda: self._lifecycle.tool_attempt_started(
                request_id=request_id,
                attempt_index=attempt_index,
                tool=tool,
            )
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
        self._best_effort(
            lambda: self._lifecycle.tool_attempt_finished(
                request_id=request_id,
                attempt_index=attempt_index,
                outcome=outcome,
                latency_ms=latency_ms,
                error_classification=error_classification,
            )
        )

    def provider_attempt_started(
        self,
        *,
        request_id: str,
        attempt_index: int,
        provider: str,
        model: str,
    ) -> None:
        self._best_effort(
            lambda: self._lifecycle.provider_attempt_started(
                request_id=request_id,
                attempt_index=attempt_index,
                provider=provider,
                model=model,
            )
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
        self._best_effort(
            lambda: self._lifecycle.provider_attempt_finished(
                request_id=request_id,
                attempt_index=attempt_index,
                outcome=outcome,
                latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost_microusd=estimated_cost_microusd,
                error_classification=error_classification,
            )
        )

    def cache_lookup_finished(
        self,
        *,
        request_id: str,
        provider: str,
        outcome: CacheLookupOutcome,
    ) -> None:
        self._best_effort(
            lambda: self._lifecycle.cache_lookup_finished(
                request_id=request_id,
                provider=provider,
                outcome=outcome,
            )
        )

    def request_finished(
        self,
        request_id: str,
        outcome: ExecutionOutcome,
        *,
        latency_ms: int | None = None,
    ) -> None:
        self._best_effort(
            lambda: self._lifecycle.request_finished(
                request_id,
                outcome,
                latency_ms=latency_ms,
            )
        )

    @staticmethod
    def _best_effort(operation: Callable[[], None]) -> None:
        try:
            operation()
        except Exception:
            return


class CompositeRuntimeLifecycle:
    """Fan out lifecycle events while isolating each observer from the others."""

    def __init__(self, lifecycles: tuple[RuntimeLifecycle, ...]) -> None:
        self._lifecycles = tuple(SafeRuntimeLifecycle(item) for item in lifecycles)

    def request_started(self, request: RequestContext) -> None:
        for lifecycle in self._lifecycles:
            lifecycle.request_started(request)

    def route_selected(self, request_id: str, route_reason: str) -> None:
        for lifecycle in self._lifecycles:
            lifecycle.route_selected(request_id, route_reason)

    def execution_path_selected(
        self,
        request_id: str,
        execution_path: ExecutionPath,
    ) -> None:
        for lifecycle in self._lifecycles:
            lifecycle.execution_path_selected(request_id, execution_path)

    def tool_attempt_started(
        self,
        *,
        request_id: str,
        attempt_index: int,
        tool: str,
    ) -> None:
        for lifecycle in self._lifecycles:
            lifecycle.tool_attempt_started(
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
        for lifecycle in self._lifecycles:
            lifecycle.tool_attempt_finished(
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
        for lifecycle in self._lifecycles:
            lifecycle.provider_attempt_started(
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
        for lifecycle in self._lifecycles:
            lifecycle.provider_attempt_finished(
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
        for lifecycle in self._lifecycles:
            lifecycle.cache_lookup_finished(
                request_id=request_id,
                provider=provider,
                outcome=outcome,
            )

    def request_finished(
        self,
        request_id: str,
        outcome: ExecutionOutcome,
        *,
        latency_ms: int | None = None,
    ) -> None:
        for lifecycle in self._lifecycles:
            lifecycle.request_finished(
                request_id,
                outcome,
                latency_ms=latency_ms,
            )
