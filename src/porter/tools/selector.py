from __future__ import annotations

import re

_ARITHMETIC = re.compile(
    r"^\s*(?:what\s+is\s+)?"
    r"(?P<expression>"
    r"[-+*/().\d\s]+"
    r")\??\s*$",
    re.IGNORECASE,
)

_CONVERSION = re.compile(
    r"^\s*(?P<expression>"
    r"\d+(?:\.\d+)?\s+"
    r"[A-Za-z°]+\s+"
    r"(?:to|in)\s+"
    r"[A-Za-z°]+"
    r")\??\s*$",
    re.IGNORECASE,
)


def select_qalculate_expression(text: str) -> str | None:
    for pattern in (_ARITHMETIC, _CONVERSION):
        match = pattern.fullmatch(text)
        if match is not None:
            return match.group("expression").strip()

    return None
