from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter, Histogram

from porter.core.lifecycle import CacheLookupOutcome, ExecutionOutcome
from porter.core.models import ExecutionPath, RequestContext


@dataclass(slots=True)
class _RequestMetricState:
    source: str
    path: str = "unselected"


class MetricsLifecycle:
    """Translate lifecycle events into low-cardinality Prometheus metrics."""

    def __init__(self, registry: CollectorRegistry) -> None:
        self._requests: dict[str, _RequestMetricState] = {}
        self._provider_attempts: dict[tuple[str, int], str] = {}
        self._tool_attempts: dict[tuple[str, int], str] = {}

        self._requests_total = Counter(
            "porter_requests_total",
            "Completed Porter requests.",
            ("source", "path"),
            registry=registry,
        )
        self._request_failures_total = Counter(
            "porter_request_failures_total",
            "Porter requests that completed with a failed outcome.",
            ("source", "path"),
            registry=registry,
        )
        self._request_cancellations_total = Counter(
            "porter_request_cancellations_total",
            "Porter requests that completed with a cancelled outcome.",
            ("source", "path"),
            registry=registry,
        )
        self._request_duration = Histogram(
            "porter_request_duration_seconds",
            "End-to-end Porter request duration in seconds.",
            ("source", "path"),
            registry=registry,
        )
        self._provider_attempts_total = Counter(
            "porter_provider_attempts_total",
            "Inference provider attempts.",
            ("provider",),
            registry=registry,
        )
        self._provider_failures_total = Counter(
            "porter_provider_attempt_failures_total",
            "Failed inference provider attempts.",
            ("provider",),
            registry=registry,
        )
        self._provider_fallbacks_total = Counter(
            "porter_provider_fallbacks_total",
            "Inference attempts that used a fallback provider.",
            ("provider",),
            registry=registry,
        )
        self._provider_duration = Histogram(
            "porter_provider_attempt_duration_seconds",
            "Inference provider attempt duration in seconds.",
            ("provider",),
            registry=registry,
        )
        self._tool_attempts_total = Counter(
            "porter_tool_attempts_total",
            "Deterministic tool attempts.",
            ("tool",),
            registry=registry,
        )
        self._tool_failures_total = Counter(
            "porter_tool_attempt_failures_total",
            "Failed deterministic tool attempts.",
            ("tool",),
            registry=registry,
        )
        self._tool_duration = Histogram(
            "porter_tool_attempt_duration_seconds",
            "Deterministic tool attempt duration in seconds.",
            ("tool",),
            registry=registry,
        )
        self._cache_lookups_total = Counter(
            "porter_inference_cache_lookups_total",
            "Inference cache lookups by provider and outcome.",
            ("provider", "outcome"),
            registry=registry,
        )

    def request_started(self, request: RequestContext) -> None:
        self._requests[request.request_id] = _RequestMetricState(
            source=request.source.value
        )

    def route_selected(self, request_id: str, route_reason: str) -> None:
        return None

    def execution_path_selected(
        self,
        request_id: str,
        execution_path: ExecutionPath,
    ) -> None:
        state = self._requests.get(request_id)
        if state is not None:
            state.path = execution_path.value

    def tool_attempt_started(
        self,
        *,
        request_id: str,
        attempt_index: int,
        tool: str,
    ) -> None:
        self._tool_attempts[(request_id, attempt_index)] = tool
        self._tool_attempts_total.labels(tool=tool).inc()

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
        self._tool_duration.labels(tool=tool).observe(latency_ms / 1_000)
        if outcome is ExecutionOutcome.FAILED:
            self._tool_failures_total.labels(tool=tool).inc()

    def provider_attempt_started(
        self,
        *,
        request_id: str,
        attempt_index: int,
        provider: str,
        model: str,
    ) -> None:
        self._provider_attempts[(request_id, attempt_index)] = provider
        self._provider_attempts_total.labels(provider=provider).inc()
        if attempt_index > 1:
            self._provider_fallbacks_total.labels(provider=provider).inc()

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
        provider = self._provider_attempts.pop(
            (request_id, attempt_index),
            "unknown",
        )
        self._provider_duration.labels(provider=provider).observe(
            latency_ms / 1_000
        )
        if outcome is ExecutionOutcome.FAILED:
            self._provider_failures_total.labels(provider=provider).inc()

    def cache_lookup_finished(
        self,
        *,
        request_id: str,
        provider: str,
        outcome: CacheLookupOutcome,
    ) -> None:
        self._cache_lookups_total.labels(
            provider=provider,
            outcome=outcome.value,
        ).inc()

    def request_finished(
        self,
        request_id: str,
        outcome: ExecutionOutcome,
        *,
        latency_ms: int | None = None,
    ) -> None:
        state = self._requests.pop(
            request_id,
            _RequestMetricState(source="unknown"),
        )
        labels = {"source": state.source, "path": state.path}
        self._requests_total.labels(**labels).inc()
        if outcome is ExecutionOutcome.FAILED:
            self._request_failures_total.labels(**labels).inc()
        elif outcome is ExecutionOutcome.CANCELLED:
            self._request_cancellations_total.labels(**labels).inc()
        if latency_ms is not None:
            self._request_duration.labels(**labels).observe(latency_ms / 1_000)
