from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from porter.core.exceptions import ActionNotAuthorized
from porter.core.models import PrivacyClass, RequestContext, RequestSource


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    local_allowed: bool
    cloud_allowed: bool
    redaction_required: bool
    reason: str


class PolicyEngine:
    def evaluate(self, request: RequestContext) -> PolicyDecision:
        if request.privacy_class is PrivacyClass.LOCAL_ONLY:
            return PolicyDecision(
                local_allowed=True,
                cloud_allowed=False,
                redaction_required=False,
                reason="local_only",
            )

        if request.privacy_class is PrivacyClass.CLOUD_ALLOWED:
            reason = (
                "cloud_explicitly_allowed"
                if request.allow_cloud
                else "cloud_not_authorized"
            )
            return PolicyDecision(
                local_allowed=True,
                cloud_allowed=request.allow_cloud,
                redaction_required=False,
                reason=reason,
            )

        if request.privacy_class is PrivacyClass.CLOUD_ALLOWED_REDACTED:
            return PolicyDecision(
                local_allowed=True,
                cloud_allowed=False,
                redaction_required=True,
                reason="redaction_not_implemented",
            )

        raise ValueError(f"Unsupported privacy class: {request.privacy_class}")


class ActionEffect(StrEnum):
    READ = "read"
    LOCAL_WRITE = "local_write"
    MEMORY_WRITE = "memory_write"
    SYSTEM_WRITE = "system_write"


_INTENT_EFFECTS = MappingProxyType(
    {
        "HassGetCurrentTime": ActionEffect.READ,
        "HassGetCurrentDate": ActionEffect.READ,
        "HassListAddItem": ActionEffect.LOCAL_WRITE,
        "HassListCompleteItem": ActionEffect.LOCAL_WRITE,
        "HassListRemoveItem": ActionEffect.LOCAL_WRITE,
        "PorterPlannerToday": ActionEffect.READ,
        "PorterPlannerOverdue": ActionEffect.READ,
        "PorterPlannerUpcoming": ActionEffect.READ,
        "PorterPlannerUnscheduled": ActionEffect.READ,
        "PorterReminderCreate": ActionEffect.LOCAL_WRITE,
        "PorterReminderList": ActionEffect.READ,
        "PorterReminderCancel": ActionEffect.LOCAL_WRITE,
        "PorterTimerCreate": ActionEffect.LOCAL_WRITE,
        "PorterTimerList": ActionEffect.READ,
        "PorterTimerCancel": ActionEffect.LOCAL_WRITE,
        "PorterMemoryRemember": ActionEffect.MEMORY_WRITE,
        "PorterMemoryList": ActionEffect.READ,
        "PorterMemoryForget": ActionEffect.MEMORY_WRITE,
        "PorterPlexStart": ActionEffect.SYSTEM_WRITE,
        "PorterPlexStop": ActionEffect.SYSTEM_WRITE,
        "PorterPlexRestart": ActionEffect.SYSTEM_WRITE,
        "PorterStorageMounted": ActionEffect.READ,
        "PorterStorageUnmounted": ActionEffect.READ,
        "PorterStorageLayout": ActionEffect.READ,
        "PorterDiskUsage": ActionEffect.READ,
        "PorterDiskPressure": ActionEffect.READ,
    }
)

_LOCAL_WRITE_SOURCES = frozenset({RequestSource.CLI})
_MEMORY_WRITE_SOURCES = frozenset({RequestSource.CLI, RequestSource.WEB})
_SYSTEM_WRITE_SOURCES = frozenset({RequestSource.CLI})


def action_effect_for_intent(intent_name: str) -> ActionEffect:
    try:
        return _INTENT_EFFECTS[intent_name]
    except KeyError as exc:
        raise ValueError(
            f"deterministic intent has no action classification: {intent_name}"
        ) from exc


class ActionPolicy:
    """Authorize deterministic intent effects without owning intent recognition."""

    def authorize(
        self,
        request: RequestContext,
        *,
        action_name: str,
        effect: ActionEffect,
    ) -> None:
        if effect is ActionEffect.READ:
            return

        if effect is ActionEffect.LOCAL_WRITE:
            allowed_sources = _LOCAL_WRITE_SOURCES
        elif effect is ActionEffect.MEMORY_WRITE:
            allowed_sources = _MEMORY_WRITE_SOURCES
        elif effect is ActionEffect.SYSTEM_WRITE:
            allowed_sources = _SYSTEM_WRITE_SOURCES
        else:
            raise ValueError(f"unsupported action effect: {effect!r}")

        if request.source in allowed_sources:
            return

        raise ActionNotAuthorized(
            f"{action_name} ({effect.value}) is not authorized from "
            f"{request.source.value}"
        )


__all__ = [
    "ActionEffect",
    "ActionPolicy",
    "PolicyDecision",
    "PolicyEngine",
    "action_effect_for_intent",
]
