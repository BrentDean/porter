from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class ToolResult:
    text: str
    data: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "data",
            MappingProxyType(dict(self.data)),
        )
