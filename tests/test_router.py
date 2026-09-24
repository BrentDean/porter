from porter.core.models import Capability, PrivacyClass
from porter.policy import PolicyDecision
from porter.providers.registry import ProviderHealth, ProviderRegistry
from porter.routing import ModelRouter
from tests.fakes import FakeProvider, make_request


def test_local_provider_is_ordered_before_cloud() -> None:
    registry = ProviderRegistry(
        (
            FakeProvider(name="cloud", model="c", is_cloud=True),
            FakeProvider(name="local", model="l"),
        )
    )
    route = ModelRouter(registry).route(
        make_request(
            privacy_class=PrivacyClass.CLOUD_ALLOWED,
            allow_cloud=True,
        ),
        PolicyDecision(True, True, False, "test"),
    )
    assert route.provider_names == ("local", "cloud")


def test_capability_filtering_removes_incompatible_provider() -> None:
    registry = ProviderRegistry(
        (
            FakeProvider(
                name="text",
                model="t",
                capabilities=frozenset({Capability.TEXT}),
            ),
            FakeProvider(
                name="vision",
                model="v",
                capabilities=frozenset({Capability.TEXT, Capability.VISION}),
            ),
        )
    )
    request = make_request(
        content="look",
        capabilities_required=frozenset({Capability.VISION}),
    )
    route = ModelRouter(registry).route(
        request,
        PolicyDecision(True, False, False, "test"),
    )
    assert route.provider_names == ("vision",)


def test_unavailable_provider_is_removed_from_route() -> None:
    registry = ProviderRegistry(
        (
            FakeProvider(name="primary", model="a"),
            FakeProvider(name="backup", model="b"),
        )
    )
    registry.set_health("primary", ProviderHealth.UNAVAILABLE)

    route = ModelRouter(registry).route(
        make_request(),
        PolicyDecision(True, False, False, "test"),
    )

    assert route.provider_names == ("backup",)


def test_degraded_provider_remains_routable() -> None:
    registry = ProviderRegistry((FakeProvider(name="local", model="a"),))
    registry.set_health("local", ProviderHealth.DEGRADED)

    route = ModelRouter(registry).route(
        make_request(),
        PolicyDecision(True, False, False, "test"),
    )

    assert route.provider_names == ("local",)


def test_provider_without_text_cannot_handle_default_request() -> None:
    registry = ProviderRegistry(
        (
            FakeProvider(
                name="no-text",
                model="a",
                capabilities=frozenset(),
            ),
            FakeProvider(
                name="text",
                model="b",
                capabilities=frozenset({Capability.TEXT}),
            ),
        )
    )

    route = ModelRouter(registry).route(
        make_request(),
        PolicyDecision(True, False, False, "test"),
    )

    assert route.provider_names == ("text",)


def test_vision_request_can_require_text_and_vision() -> None:
    registry = ProviderRegistry(
        (
            FakeProvider(
                name="text",
                model="a",
                capabilities=frozenset({Capability.TEXT}),
            ),
            FakeProvider(
                name="vision",
                model="b",
                capabilities=frozenset(
                    {Capability.TEXT, Capability.VISION}
                ),
            ),
        )
    )

    route = ModelRouter(registry).route(
        make_request(
            content="look",
            capabilities_required=frozenset(
                {Capability.TEXT, Capability.VISION}
            ),
        ),
        PolicyDecision(True, False, False, "test"),
    )

    assert route.provider_names == ("vision",)
