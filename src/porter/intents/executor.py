from __future__ import annotations

from porter.core.models import RequestContext
from porter.intents.context import (
    IntentRecognitionContextProvider,
    NullIntentRecognitionContextProvider,
)
from porter.intents.models import IntentResult
from porter.intents.recognizer import PorterIntentRecognizer
from porter.intents.registry import IntentHandlerRegistry
from porter.policy import ActionPolicy


class DeterministicIntentExecutor:
    def __init__(
        self,
        registry: IntentHandlerRegistry,
        *,
        language: str = "en",
        context_provider: IntentRecognitionContextProvider | None = None,
        action_policy: ActionPolicy | None = None,
    ) -> None:
        self._registry = registry
        self._recognizer = PorterIntentRecognizer(
            language=language,
            supported_intents=registry.supported_intents(),
        )
        self._context_provider = (
            context_provider
            or NullIntentRecognitionContextProvider()
        )
        self._action_policy = action_policy or ActionPolicy()

    async def execute(
        self,
        request: RequestContext,
    ) -> IntentResult | None:
        text = request.latest_user_text
        if text is None:
            return None

        context = self._context_provider.context_for(request)
        intent = self._recognizer.recognize(
            text,
            context=context,
        )
        if intent is None:
            return None

        handler = self._registry.get(intent.name)
        self._action_policy.authorize(
            request,
            action_name=intent.name,
            effect=handler.action_effect,
        )
        return await handler.handle(request, intent)
