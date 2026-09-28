from __future__ import annotations

from hassil import Intents, TextSlotList, filter_intents, recognize_best
from home_assistant_intents import get_intents

from porter.intents.context import IntentRecognitionContext
from porter.intents.local_actions import apply_local_action_intents
from porter.intents.memory_intents import apply_memory_intents
from porter.intents.models import RecognizedIntent
from porter.intents.supplemental import apply_supplemental_intents


class PorterIntentRecognizer:
    def __init__(
        self,
        *,
        language: str = "en",
        supported_intents: frozenset[str],
    ) -> None:
        intent_data = get_intents(language)
        if intent_data is None:
            raise ValueError(f"unsupported intent language: {language}")

        all_intents = Intents.from_dict(
            apply_memory_intents(
                apply_local_action_intents(
                    apply_supplemental_intents(intent_data)
                )
            )
        )
        self._intents = filter_intents(
            all_intents,
            intent_names=supported_intents,
        )

    def recognize(
        self,
        text: str,
        *,
        context: IntentRecognitionContext | None = None,
    ) -> RecognizedIntent | None:
        slot_lists = None
        if context is not None and context.slot_values:
            slot_lists = {
                name: TextSlotList.from_tuples(
                    (
                        (
                            value.text,
                            value.value,
                            dict(value.context),
                        )
                        for value in values
                    ),
                    allow_template=False,
                    name=name,
                )
                for name, values in context.slot_values.items()
            }

        result = recognize_best(
            text,
            self._intents,
            slot_lists=slot_lists,
        )

        if result is None:
            return None

        slots = {
            name: entity.value
            for name, entity in result.entities.items()
        }

        return RecognizedIntent(
            name=result.intent.name,
            slots=slots,
        )
