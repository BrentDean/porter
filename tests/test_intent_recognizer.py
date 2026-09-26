import pytest

from porter.intents import (
    IntentRecognitionContext,
    IntentSlotValue,
    PorterIntentRecognizer,
    RecognizedIntent,
)

SUPPORTED_INTENTS = frozenset(
    {
        "HassGetCurrentTime",
        "HassGetCurrentDate",
    }
)


def build_recognizer() -> PorterIntentRecognizer:
    return PorterIntentRecognizer(
        supported_intents=SUPPORTED_INTENTS,
    )


@pytest.mark.parametrize(
    ("text", "intent_name"),
    [
        ("what time is it", "HassGetCurrentTime"),
        ("tell me the current time", "HassGetCurrentTime"),
        ("what is the date today", "HassGetCurrentDate"),
        ("what's today's date", "HassGetCurrentDate"),
    ],
)
def test_recognizes_supported_intents(
    text: str,
    intent_name: str,
) -> None:
    result = build_recognizer().recognize(text)

    assert result == RecognizedIntent(
        name=intent_name,
        slots={},
    )


def test_recognizes_upstream_todo_intent_with_runtime_list_name() -> None:
    recognizer = PorterIntentRecognizer(
        supported_intents=frozenset({"HassListAddItem"}),
    )
    context = IntentRecognitionContext(
        slot_values={
            "name": (
                IntentSlotValue(
                    text="Shopping",
                    value="Shopping",
                    context={"domain": "todo"},
                ),
            )
        }
    )

    result = recognizer.recognize(
        "add apples to my Shopping list",
        context=context,
    )

    assert result == RecognizedIntent(
        name="HassListAddItem",
        slots={
            "item": "apples",
            "name": "Shopping",
        },
    )


def test_runtime_list_name_does_not_match_wrong_domain() -> None:
    recognizer = PorterIntentRecognizer(
        supported_intents=frozenset({"HassListAddItem"}),
    )
    context = IntentRecognitionContext(
        slot_values={
            "name": (
                IntentSlotValue(
                    text="Shopping",
                    value="Shopping",
                    context={"domain": "light"},
                ),
            )
        }
    )

    assert (
        recognizer.recognize(
            "add apples to my Shopping list",
            context=context,
        )
        is None
    )


def test_unmatched_text_returns_none() -> None:
    result = build_recognizer().recognize(
        "explain why dns uses both udp and tcp"
    )

    assert result is None


def test_unsupported_language_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported intent language"):
        PorterIntentRecognizer(
            language="not-a-language",
            supported_intents=SUPPORTED_INTENTS,
        )


def test_slots_are_read_only() -> None:
    result = RecognizedIntent(
        name="example",
        slots={"name": "lamp"},
    )

    with pytest.raises(TypeError):
        result.slots["name"] = "fan"  # type: ignore[index]


@pytest.mark.parametrize(
    "text",
    [
        "what day is it",
        "what day is it today",
        "what is the day today",
    ],
)
def test_recognizes_porter_supplemental_date_sentences(
    text: str,
) -> None:
    result = build_recognizer().recognize(text)

    assert result == RecognizedIntent(
        name="HassGetCurrentDate",
        slots={},
    )
