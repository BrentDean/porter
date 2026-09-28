from __future__ import annotations

from dataclasses import dataclass

from porter.core.models import RequestContext
from porter.policy import PolicyDecision
from porter.providers.registry import ProviderHealth, ProviderRegistry


@dataclass(frozen=True, slots=True)
class RouteDecision:
    provider_names: tuple[str, ...]
    reason: str


class ModelRouter:
    def __init__(self, registry: ProviderRegistry) -> None:
        self._registry = registry

    def route(self, request: RequestContext, policy: PolicyDecision) -> RouteDecision:
        eligible = [
            provider
            for provider in self._registry.all()
            if provider.supports(request)
            and self._registry.health(provider.name) is not ProviderHealth.UNAVAILABLE
        ]

        locals_ = sorted(
            provider.name
            for provider in eligible
            if not provider.is_cloud and policy.local_allowed
        )
        clouds = sorted(
            provider.name
            for provider in eligible
            if provider.is_cloud and policy.cloud_allowed
        )

        provider_names = tuple(locals_ + clouds)
        if locals_ and clouds:
            reason = "local_preferred_cloud_fallback_allowed"
        elif locals_:
            reason = "local_only_route"
        elif clouds:
            reason = "cloud_only_route"
        else:
            reason = "no_eligible_provider"

        return RouteDecision(provider_names=provider_names, reason=reason)


__all__ = ["ModelRouter", "RouteDecision"]
