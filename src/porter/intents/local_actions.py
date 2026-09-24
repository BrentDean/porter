from __future__ import annotations

from copy import deepcopy
from typing import Any

_PORTER_LOCAL_ACTION_INTENTS: dict[str, dict[str, Any]] = {
    "PorterPlexStart": {
        "data": [
            {
                "sentences": [
                    "start plex",
                    "start plex media server",
                    "start the plex server",
                ],
                "metadata": {"slot_combination": "default"},
                "response": "default",
            }
        ]
    },
    "PorterPlexStop": {
        "data": [
            {
                "sentences": [
                    "stop plex",
                    "stop plex media server",
                    "stop the plex server",
                ],
                "metadata": {"slot_combination": "default"},
                "response": "default",
            }
        ]
    },
    "PorterPlexRestart": {
        "data": [
            {
                "sentences": [
                    "restart plex",
                    "restart plex media server",
                    "restart the plex server",
                ],
                "metadata": {"slot_combination": "default"},
                "response": "default",
            }
        ]
    },
    "PorterStorageMounted": {
        "data": [
            {
                "sentences": [
                    "which drives are mounted",
                    "what drives are mounted",
                    "show mounted drives",
                    "show me the mounted drives",
                ],
                "metadata": {"slot_combination": "default"},
                "response": "default",
            }
        ]
    },
    "PorterStorageUnmounted": {
        "data": [
            {
                "sentences": [
                    "which drives are unmounted",
                    "what drives are unmounted",
                    "what drives are not mounted",
                    "show unmounted drives",
                    "show me the unmounted drives",
                ],
                "metadata": {"slot_combination": "default"},
                "response": "default",
            }
        ]
    },
    "PorterStorageLayout": {
        "data": [
            {
                "sentences": [
                    "show my drives",
                    "show me my drives",
                    "show storage layout",
                    "show my storage layout",
                    "show my storage",
                ],
                "metadata": {"slot_combination": "default"},
                "response": "default",
            }
        ]
    },
    "PorterDiskUsage": {
        "data": [
            {
                "sentences": [
                    "disk usage",
                    "show disk usage",
                    "show me disk usage",
                    "show free disk space",
                    "how much disk space do i have",
                ],
                "metadata": {"slot_combination": "default"},
                "response": "default",
            }
        ]
    },
    "PorterDiskPressure": {
        "data": [
            {
                "sentences": [
                    "which drives are almost full",
                    "which disks are almost full",
                    "show drives that are almost full",
                    "do i have any storage problems",
                ],
                "metadata": {"slot_combination": "default"},
                "response": "default",
            }
        ]
    },
}


def apply_local_action_intents(intent_data: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(intent_data)
    intents = merged.setdefault("intents", {})
    for intent_name, supplemental in _PORTER_LOCAL_ACTION_INTENTS.items():
        existing = intents.setdefault(intent_name, {"data": []})
        existing.setdefault("data", []).extend(deepcopy(supplemental["data"]))
    return merged
