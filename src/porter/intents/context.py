from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol

from porter.core.models import RequestContext


@dataclass(frozen=True, slots=True)
class IntentSlotValue:
    text: str
    value: object
    context: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("intent slot text must not be empty")
        object.__setattr__(
            self,
            "context",
            MappingProxyType(dict(self.context)),
        )


@dataclass(frozen=True, slots=True)
class IntentRecognitionContext:
    slot_values: Mapping[str, tuple[IntentSlotValue, ...]] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        normalized: dict[str, tuple[IntentSlotValue, ...]] = {}
        for name, values in self.slot_values.items():
            if not name.strip():
                raise ValueError("intent slot name must not be empty")
            normalized[name] = tuple(values)

        object.__setattr__(
            self,
            "slot_values",
            MappingProxyType(normalized),
        )

    @classmethod
    def merge(
        cls,
        contexts: tuple[IntentRecognitionContext, ...],
    ) -> IntentRecognitionContext:
        merged: dict[str, list[IntentSlotValue]] = {}
        for context in contexts:
            for name, values in context.slot_values.items():
                merged.setdefault(name, []).extend(values)

        return cls(
            slot_values={
                name: tuple(values)
                for name, values in merged.items()
            }
        )


class IntentRecognitionContextProvider(Protocol):
    def context_for(
        self,
        request: RequestContext,
    ) -> IntentRecognitionContext:
        ...


class NullIntentRecognitionContextProvider:
    def context_for(
        self,
        request: RequestContext,
    ) -> IntentRecognitionContext:
        return IntentRecognitionContext()


class CompositeIntentRecognitionContextProvider:
    def __init__(
        self,
        providers: tuple[IntentRecognitionContextProvider, ...] = (),
    ) -> None:
        self._providers = providers

    def context_for(
        self,
        request: RequestContext,
    ) -> IntentRecognitionContext:
        return IntentRecognitionContext.merge(
            tuple(
                provider.context_for(request)
                for provider in self._providers
            )
        )
