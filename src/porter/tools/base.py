from __future__ import annotations

from abc import ABC, abstractmethod

from porter.core.models import RequestContext
from porter.tools.models import ToolResult


class Tool(ABC):
    name: str

    @abstractmethod
    def supports(self, request: RequestContext) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def execute(self, request: RequestContext) -> ToolResult:
        raise NotImplementedError
