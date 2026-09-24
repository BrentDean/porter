from __future__ import annotations

from porter.intents.handlers import IntentHandler
from porter.policy import ActionEffect


class IntentHandlerRegistry:
    def __init__(self, handlers: tuple[IntentHandler, ...] = ()) -> None:
        names = [handler.intent_name for handler in handlers]
        if len(names) != len(set(names)):
            raise ValueError("intent handler names must be unique")

        for handler in handlers:
            effect = handler.action_effect
            if not isinstance(effect, ActionEffect):
                raise ValueError(
                    f"intent handler has invalid action classification: {handler.intent_name}"
                )

        self._handlers = {
            handler.intent_name: handler
            for handler in handlers
        }

    def all(self) -> tuple[IntentHandler, ...]:
        return tuple(self._handlers.values())

    def get(self, intent_name: str) -> IntentHandler:
        return self._handlers[intent_name]

    def supported_intents(self) -> frozenset[str]:
        return frozenset(self._handlers)
