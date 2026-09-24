from __future__ import annotations

from abc import ABC, abstractmethod

from porter.core.models import Capability, InferenceResult, RequestContext


class InferenceProvider(ABC):
    name: str
    model: str
    is_cloud: bool = False
    capabilities: frozenset[Capability] = frozenset({Capability.TEXT})

    def supports(self, request: RequestContext) -> bool:
        return request.capabilities_required.issubset(self.capabilities)

    @abstractmethod
    async def generate(self, request: RequestContext) -> InferenceResult:
        raise NotImplementedError
