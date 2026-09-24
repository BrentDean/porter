from __future__ import annotations

from copy import deepcopy
from typing import Any

_PORTER_MEMORY_INTENTS: dict[str, dict[str, Any]] = {
    "PorterMemoryRemember": {
        "data": [
            {
                "sentences": [
                    "remember that {timer_command:memory}",
                ],
                "metadata": {"slot_combination": "memory"},
                "response": "default",
            }
        ]
    },
    "PorterMemoryList": {
        "data": [
            {
                "sentences": [
                    "what do you remember about me",
                    "what do you remember",
                    "show me what you remember about me",
                    "show my memories",
                ],
                "metadata": {"slot_combination": "default"},
                "response": "default",
            }
        ]
    },
    "PorterMemoryForget": {
        "data": [
            {
                "sentences": [
                    "forget that {timer_command:memory}",
                    "delete [the] memory [that] {timer_command:memory}",
                ],
                "metadata": {"slot_combination": "memory"},
                "response": "default",
            }
        ]
    },
}


def apply_memory_intents(intent_data: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(intent_data)
    intents = merged.setdefault("intents", {})
    for intent_name, supplemental in _PORTER_MEMORY_INTENTS.items():
        existing = intents.setdefault(intent_name, {"data": []})
        existing.setdefault("data", []).extend(deepcopy(supplemental["data"]))
    return merged
