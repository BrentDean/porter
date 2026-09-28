from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from uuid import uuid4


class PrivacyClass(StrEnum):
    LOCAL_ONLY = "local_only"
    CLOUD_ALLOWED = "cloud_allowed"
    CLOUD_ALLOWED_REDACTED = "cloud_allowed_redacted"


class RequestSource(StrEnum):
    CLI = "cli"
    VOICE = "voice"
    AUTOMATION = "automation"
    HOME_ASSISTANT = "home_assistant"
    WEB = "web"


class Capability(StrEnum):
    TEXT = "text"
    VISION = "vision"
    TOOLS = "tools"


@dataclass(frozen=True, slots=True)
class Message:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class RequestContext:
    messages: tuple[Message, ...]
    principal_id: str
    source: RequestSource
    session_id: str | None = None
    task_type: str = "general"
    privacy_class: PrivacyClass = PrivacyClass.LOCAL_ONLY
    capabilities_required: frozenset[Capability] = field(
        default_factory=lambda: frozenset({Capability.TEXT})
    )
    allow_cloud: bool = False
    request_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        if not self.messages:
            raise ValueError("messages must not be empty")
        if not self.principal_id.strip():
            raise ValueError("principal_id must not be empty")
        if not isinstance(self.source, RequestSource):
            raise ValueError("source must be a RequestSource")
        if self.session_id is not None and not self.session_id.strip():
            raise ValueError("session_id must not be empty when provided")
        if not all(
            isinstance(capability, Capability)
            for capability in self.capabilities_required
        ):
            raise ValueError(
                "capabilities_required must contain Capability values"
            )
        if self.privacy_class is PrivacyClass.LOCAL_ONLY and self.allow_cloud:
            raise ValueError(
                "LOCAL_ONLY requests cannot allow cloud execution"
            )

    @property
    def latest_user_text(self) -> str | None:
        for message in reversed(self.messages):
            if message.role == "user":
                return message.content
        return None


@dataclass(frozen=True, slots=True)
class InferenceResult:
    text: str
    provider: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_microusd: int | None = None


class ExecutionPath(StrEnum):
    DETERMINISTIC = "deterministic"
    TOOL = "tool"
    INFERENCE = "inference"


@dataclass(frozen=True, slots=True)
class RequestResult:
    text: str
    path: ExecutionPath
    provider: str | None = None
    model: str | None = None
    tool: str | None = None
    data: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "data",
            MappingProxyType(dict(self.data)),
        )
