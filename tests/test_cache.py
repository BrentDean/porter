from dataclasses import replace
from pathlib import Path

import pytest

from porter.cache import InferenceCache
from porter.core.exceptions import NoProviderAvailable
from porter.core.models import InferenceResult, PrivacyClass
from porter.providers.executor import ProviderExecutor
from porter.providers.registry import ProviderRegistry
from porter.routing import RouteDecision
from porter.storage.database import Database
from tests.fakes import FakeProvider, make_request


def _cache(tmp_path: Path, *, clock=lambda: 1_000.0) -> InferenceCache:
    return InferenceCache(
        Database(tmp_path / "porter.db"),
        ttl_seconds=60,
        clock=clock,
    )


def test_cache_round_trip_ignores_request_id(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    first = make_request(content="explain dns")
    second = make_request(content="explain dns")
    result = InferenceResult(
        text="answer",
        provider="local",
        model="model-a",
        input_tokens=12,
        output_tokens=4,
        estimated_cost_microusd=0,
    )

    cache.put(first, result, provider="local", model="model-a")

    assert first.request_id != second.request_id
    assert cache.get(second, provider="local", model="model-a") == result


def test_cache_is_principal_scoped(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    alice = replace(make_request(content="private question"), principal_id="alice")
    bob = replace(make_request(content="private question"), principal_id="bob")
    result = InferenceResult(text="alice answer", provider="local", model="model-a")

    cache.put(alice, result, provider="local", model="model-a")

    assert cache.get(bob, provider="local", model="model-a") is None


def test_cache_entry_expires(tmp_path: Path) -> None:
    now = [1_000.0]
    cache = _cache(tmp_path, clock=lambda: now[0])
    request = make_request(content="temporary answer")
    result = InferenceResult(text="answer", provider="local", model="model-a")

    cache.put(request, result, provider="local", model="model-a")
    assert cache.get(request, provider="local", model="model-a") == result

    now[0] = 1_060.0
    assert cache.get(request, provider="local", model="model-a") is None


def test_cache_stats_record_hits_and_misses(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    request = make_request(content="cache stats")
    result = InferenceResult(text="answer", provider="local", model="model-a")

    assert cache.stats().entries == 0
    assert cache.get(request, provider="local", model="model-a") is None

    cache.put(request, result, provider="local", model="model-a")
    assert cache.get(request, provider="local", model="model-a") == result

    stats = cache.stats()
    assert stats.entries == 1
    assert stats.hits == 1
    assert stats.misses == 1


@pytest.mark.asyncio
async def test_executor_reuses_cached_provider_result(tmp_path: Path) -> None:
    provider = FakeProvider(name="local", model="model-a", response="cached answer")
    registry = ProviderRegistry((provider,))
    executor = ProviderExecutor(registry, cache=_cache(tmp_path))
    route = RouteDecision(provider_names=("local",), reason="test")

    first = await executor.execute(make_request(content="same question"), route)
    second = await executor.execute(make_request(content="same question"), route)

    assert first == second
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_cached_cloud_result_cannot_bypass_empty_local_route(tmp_path: Path) -> None:
    provider = FakeProvider(
        name="cloud",
        model="cloud-a",
        is_cloud=True,
        response="cloud answer",
    )
    registry = ProviderRegistry((provider,))
    executor = ProviderExecutor(registry, cache=_cache(tmp_path))
    cloud_route = RouteDecision(provider_names=("cloud",), reason="cloud")
    prompt = "same question"

    await executor.execute(
        make_request(
            content=prompt,
            privacy_class=PrivacyClass.CLOUD_ALLOWED,
            allow_cloud=True,
        ),
        cloud_route,
    )

    with pytest.raises(NoProviderAvailable):
        await executor.execute(
            make_request(content=prompt),
            RouteDecision(provider_names=(), reason="local-only"),
        )

    assert provider.calls == 1


@pytest.mark.resilience
@pytest.mark.asyncio
async def test_cache_read_failure_degrades_to_live_provider() -> None:
    class FailingCache:
        def get(self, *args, **kwargs):
            raise RuntimeError("cache unavailable")

        def put(self, *args, **kwargs) -> None:
            return None

    provider = FakeProvider(name="local", model="model-a", response="live answer")
    registry = ProviderRegistry((provider,))
    executor = ProviderExecutor(
        registry,
        cache=FailingCache(),  # type: ignore[arg-type]
    )

    result = await executor.execute(
        make_request(content="cache outage"),
        RouteDecision(provider_names=("local",), reason="test"),
    )

    assert result.text == "live answer"
    assert provider.calls == 1
