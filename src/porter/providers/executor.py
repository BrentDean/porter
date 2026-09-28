import asyncio
from time import perf_counter_ns

from porter.cache import InferenceCache
from porter.core.exceptions import NoProviderAvailable, ProviderError
from porter.core.lifecycle import (
    CacheLookupOutcome,
    ExecutionOutcome,
    NullRuntimeLifecycle,
    RuntimeLifecycle,
    SafeRuntimeLifecycle,
)
from porter.core.models import InferenceResult, RequestContext
from porter.providers.registry import ProviderRegistry
from porter.routing import RouteDecision


class ProviderExecutor:
    def __init__(
        self,
        registry: ProviderRegistry,
        lifecycle: RuntimeLifecycle | None = None,
        cache: InferenceCache | None = None,
    ) -> None:
        self._registry = registry
        self._lifecycle = SafeRuntimeLifecycle(
            lifecycle or NullRuntimeLifecycle()
        )
        self._cache = cache

    async def execute(
        self,
        request: RequestContext,
        route: RouteDecision,
    ) -> InferenceResult:
        if not route.provider_names:
            raise NoProviderAvailable("route contains no eligible providers")

        failures: list[str] = []

        for attempt_index, provider_name in enumerate(
            route.provider_names,
            start=1,
        ):
            provider = self._registry.get(provider_name)

            cached = self._cached_result(
                request,
                provider=provider.name,
                model=provider.model,
            )
            if cached is not None:
                self._lifecycle.route_selected(
                    request.request_id,
                    f"{route.reason};cache_hit={provider.name}:{provider.model}",
                )
                return cached

            self._lifecycle.provider_attempt_started(
                request_id=request.request_id,
                attempt_index=attempt_index,
                provider=provider.name,
                model=provider.model,
            )

            started_ns = perf_counter_ns()

            try:
                result = await provider.generate(request)
            except asyncio.CancelledError:
                self._lifecycle.provider_attempt_finished(
                    request_id=request.request_id,
                    attempt_index=attempt_index,
                    outcome=ExecutionOutcome.CANCELLED,
                    latency_ms=self._elapsed_ms(started_ns),
                )
                raise
            except ProviderError as exc:
                self._lifecycle.provider_attempt_finished(
                    request_id=request.request_id,
                    attempt_index=attempt_index,
                    outcome=ExecutionOutcome.FAILED,
                    latency_ms=self._elapsed_ms(started_ns),
                    error_classification=type(exc).__name__,
                )
                failures.append(f"{provider_name}: {exc}")
            except Exception as exc:
                self._lifecycle.provider_attempt_finished(
                    request_id=request.request_id,
                    attempt_index=attempt_index,
                    outcome=ExecutionOutcome.FAILED,
                    latency_ms=self._elapsed_ms(started_ns),
                    error_classification=type(exc).__name__,
                )
                raise
            else:
                self._lifecycle.provider_attempt_finished(
                    request_id=request.request_id,
                    attempt_index=attempt_index,
                    outcome=ExecutionOutcome.SUCCEEDED,
                    latency_ms=self._elapsed_ms(started_ns),
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    estimated_cost_microusd=result.estimated_cost_microusd,
                )
                self._cache_result(
                    request,
                    result,
                    provider=provider.name,
                    model=provider.model,
                )
                return result

        detail = (
            "; ".join(failures)
            if failures
            else "no provider attempts succeeded"
        )
        raise NoProviderAvailable(detail)

    def _cached_result(
        self,
        request: RequestContext,
        *,
        provider: str,
        model: str,
    ) -> InferenceResult | None:
        if self._cache is None:
            return None
        try:
            result = self._cache.get(
                request,
                provider=provider,
                model=model,
            )
        except Exception:
            self._lifecycle.cache_lookup_finished(
                request_id=request.request_id,
                provider=provider,
                outcome=CacheLookupOutcome.ERROR,
            )
            return None

        self._lifecycle.cache_lookup_finished(
            request_id=request.request_id,
            provider=provider,
            outcome=(
                CacheLookupOutcome.HIT
                if result is not None
                else CacheLookupOutcome.MISS
            ),
        )
        return result

    def _cache_result(
        self,
        request: RequestContext,
        result: InferenceResult,
        *,
        provider: str,
        model: str,
    ) -> None:
        if self._cache is None:
            return
        try:
            self._cache.put(
                request,
                result,
                provider=provider,
                model=model,
            )
        except Exception:
            return

    @staticmethod
    def _elapsed_ms(started_ns: int) -> int:
        return max(
            0,
            (perf_counter_ns() - started_ns) // 1_000_000,
        )
