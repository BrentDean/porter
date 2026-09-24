import pytest

from porter.core.models import PrivacyClass
from porter.orchestration import Orchestrator
from porter.policy import PolicyEngine
from porter.providers.executor import ProviderExecutor
from porter.providers.registry import ProviderRegistry
from porter.routing import ModelRouter
from tests.fakes import FakeProvider, make_request


@pytest.mark.asyncio
async def test_local_only_never_reaches_cloud() -> None:
    local = FakeProvider(name="local", model="l", response="local")
    cloud = FakeProvider(name="cloud", model="c", is_cloud=True, response="cloud")
    registry = ProviderRegistry((local, cloud))
    orchestrator = Orchestrator(
        PolicyEngine(),
        ModelRouter(registry),
        ProviderExecutor(registry),
    )

    result = await orchestrator.infer(
        make_request(
            privacy_class=PrivacyClass.LOCAL_ONLY,
        )
    )

    assert result.provider == "local"
    assert local.calls == 1
    assert cloud.calls == 0


@pytest.mark.asyncio
async def test_cloud_fallback_happens_only_when_explicitly_allowed() -> None:
    local = FakeProvider(name="local", model="l", fail=True)
    cloud = FakeProvider(name="cloud", model="c", is_cloud=True, response="cloud")
    registry = ProviderRegistry((local, cloud))
    orchestrator = Orchestrator(
        PolicyEngine(),
        ModelRouter(registry),
        ProviderExecutor(registry),
    )

    result = await orchestrator.infer(
        make_request(
            privacy_class=PrivacyClass.CLOUD_ALLOWED,
            allow_cloud=True,
        )
    )

    assert result.provider == "cloud"
    assert local.calls == 1
    assert cloud.calls == 1
