from enum import StrEnum

from porter.providers.base import InferenceProvider


class ProviderHealth(StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class ProviderRegistry:
    def __init__(self, providers: tuple[InferenceProvider, ...] = ()) -> None:
        names = [provider.name for provider in providers]
        if len(names) != len(set(names)):
            raise ValueError("provider names must be unique")

        self._providers = {provider.name: provider for provider in providers}
        self._health = {
            provider.name: ProviderHealth.UNKNOWN
            for provider in providers
        }

    def all(self) -> tuple[InferenceProvider, ...]:
        return tuple(self._providers.values())

    def get(self, name: str) -> InferenceProvider:
        return self._providers[name]

    def health(self, name: str) -> ProviderHealth:
        self.get(name)
        return self._health[name]

    def set_health(self, name: str, health: ProviderHealth) -> None:
        self.get(name)
        if not isinstance(health, ProviderHealth):
            raise ValueError("health must be a ProviderHealth")
        self._health[name] = health
