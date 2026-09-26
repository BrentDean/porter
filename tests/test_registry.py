import pytest

from porter.providers.registry import ProviderHealth, ProviderRegistry
from tests.fakes import FakeProvider


def test_duplicate_provider_names_are_rejected() -> None:
    with pytest.raises(ValueError, match="provider names must be unique"):
        ProviderRegistry(
            (
                FakeProvider(name="same", model="a"),
                FakeProvider(name="same", model="b"),
            )
        )


def test_provider_health_defaults_to_unknown() -> None:
    registry = ProviderRegistry((FakeProvider(name="local", model="a"),))

    assert registry.health("local") is ProviderHealth.UNKNOWN


def test_provider_health_can_be_updated() -> None:
    registry = ProviderRegistry((FakeProvider(name="local", model="a"),))

    registry.set_health("local", ProviderHealth.HEALTHY)

    assert registry.health("local") is ProviderHealth.HEALTHY


def test_provider_health_rejects_unknown_provider() -> None:
    registry = ProviderRegistry()

    with pytest.raises(KeyError):
        registry.set_health("missing", ProviderHealth.UNAVAILABLE)


def test_provider_health_requires_typed_state() -> None:
    registry = ProviderRegistry((FakeProvider(name="local", model="a"),))

    with pytest.raises(ValueError, match="ProviderHealth"):
        registry.set_health("local", "healthy")  # type: ignore[arg-type]
