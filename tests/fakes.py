from dataclasses import dataclass, field

from porter.core.exceptions import ProviderError
from porter.core.models import (
    Capability,
    InferenceResult,
    Message,
    PrivacyClass,
    RequestContext,
    RequestSource,
)
from porter.providers.base import InferenceProvider


def make_request(
    *,
    content: str = "test",
    privacy_class: PrivacyClass = PrivacyClass.LOCAL_ONLY,
    allow_cloud: bool = False,
    capabilities_required: frozenset[Capability] = frozenset({Capability.TEXT}),
) -> RequestContext:
    return RequestContext(
        messages=(Message(role="user", content=content),),
        principal_id="test-user",
        source=RequestSource.CLI,
        privacy_class=privacy_class,
        allow_cloud=allow_cloud,
        capabilities_required=capabilities_required,
    )


@dataclass
class FakeProvider(InferenceProvider):
    name: str
    model: str
    is_cloud: bool = False
    capabilities: frozenset[Capability] = frozenset({Capability.TEXT})
    response: str = "ok"
    fail: bool = False
    calls: int = 0
    requests: list[RequestContext] = field(default_factory=list)

    async def generate(self, request: RequestContext) -> InferenceResult:
        self.calls += 1
        self.requests.append(request)
        if self.fail:
            raise ProviderError("synthetic provider failure")
        return InferenceResult(text=self.response, provider=self.name, model=self.model)
