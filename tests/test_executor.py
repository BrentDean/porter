import pytest

from porter.core.exceptions import NoProviderAvailable
from porter.providers.executor import ProviderExecutor
from porter.providers.registry import ProviderRegistry
from porter.routing import RouteDecision
from tests.fakes import FakeProvider, make_request


@pytest.mark.resilience
@pytest.mark.asyncio
async def test_executor_falls_back_to_next_provider() -> None:
    first = FakeProvider(name="first", model="a", fail=True)
    second = FakeProvider(name="second", model="b", response="success")
    registry = ProviderRegistry((first, second))

    result = await ProviderExecutor(registry).execute(
        make_request(),
        RouteDecision(("first", "second"), "test"),
    )

    assert result.text == "success"
    assert first.calls == 1
    assert second.calls == 1


@pytest.mark.resilience
@pytest.mark.asyncio
async def test_executor_exhausts_route_when_all_providers_fail() -> None:
    first = FakeProvider(name="first", model="a", fail=True)
    second = FakeProvider(name="second", model="b", fail=True)
    registry = ProviderRegistry((first, second))

    with pytest.raises(NoProviderAvailable) as exc_info:
        await ProviderExecutor(registry).execute(
            make_request(),
            RouteDecision(("first", "second"), "test"),
        )

    assert first.calls == 1
    assert second.calls == 1
    assert "first" in str(exc_info.value)
    assert "second" in str(exc_info.value)
