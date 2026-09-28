from __future__ import annotations

from abc import ABC, abstractmethod

from porter.core.models import RequestContext
from porter.intents.models import IntentResult, RecognizedIntent
from porter.policy import ActionEffect, action_effect_for_intent


class IntentHandler(ABC):
    intent_name: str

    @property
    def action_effect(self) -> ActionEffect:
        """Return the explicit authorization classification for this intent."""
        return action_effect_for_intent(self.intent_name)

    @abstractmethod
    async def handle(
        self,
        request: RequestContext,
        intent: RecognizedIntent,
    ) -> IntentResult:
        raise NotImplementedError
