from __future__ import annotations

from porter.tools.base import Tool


class ToolRegistry:
    def __init__(self, tools: tuple[Tool, ...] = ()) -> None:
        names = [tool.name for tool in tools]
        if len(names) != len(set(names)):
            raise ValueError("tool names must be unique")

        self._tools = {
            tool.name: tool
            for tool in tools
        }

    def all(self) -> tuple[Tool, ...]:
        return tuple(self._tools.values())

    def get(self, name: str) -> Tool:
        return self._tools[name]
