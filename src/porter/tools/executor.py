from __future__ import annotations

import asyncio
from time import perf_counter_ns

from porter.core.lifecycle import (
    ExecutionOutcome,
    NullRuntimeLifecycle,
    RuntimeLifecycle,
    SafeRuntimeLifecycle,
)
from porter.core.models import ExecutionPath, RequestContext
from porter.tools.base import Tool
from porter.tools.models import ToolResult
from porter.tools.registry import ToolRegistry


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        lifecycle: RuntimeLifecycle | None = None,
    ) -> None:
        self._registry = registry
        self._lifecycle = SafeRuntimeLifecycle(
            lifecycle or NullRuntimeLifecycle()
        )

    async def execute(
        self,
        request: RequestContext,
        tool_name: str,
    ) -> ToolResult:
        tool = self._registry.get(tool_name)

        if not tool.supports(request):
            raise ValueError(
                f"tool does not support request: {tool_name}"
            )

        return await self._execute_tool(
            request,
            tool,
            attempt_index=1,
        )

    async def execute_supported(
        self,
        request: RequestContext,
    ) -> tuple[str, ToolResult] | None:
        for tool in self._registry.all():
            if tool.supports(request):
                result = await self._execute_tool(
                    request,
                    tool,
                    attempt_index=1,
                )
                return tool.name, result

        return None

    async def _execute_tool(
        self,
        request: RequestContext,
        tool: Tool,
        *,
        attempt_index: int,
    ) -> ToolResult:
        self._lifecycle.execution_path_selected(
            request.request_id,
            ExecutionPath.TOOL,
        )
        self._lifecycle.tool_attempt_started(
            request_id=request.request_id,
            attempt_index=attempt_index,
            tool=tool.name,
        )

        started_ns = perf_counter_ns()

        try:
            result = await tool.execute(request)
        except asyncio.CancelledError:
            self._lifecycle.tool_attempt_finished(
                request_id=request.request_id,
                attempt_index=attempt_index,
                outcome=ExecutionOutcome.CANCELLED,
                latency_ms=self._elapsed_ms(started_ns),
            )
            raise
        except Exception as exc:
            self._lifecycle.tool_attempt_finished(
                request_id=request.request_id,
                attempt_index=attempt_index,
                outcome=ExecutionOutcome.FAILED,
                latency_ms=self._elapsed_ms(started_ns),
                error_classification=type(exc).__name__,
            )
            raise

        self._lifecycle.tool_attempt_finished(
            request_id=request.request_id,
            attempt_index=attempt_index,
            outcome=ExecutionOutcome.SUCCEEDED,
            latency_ms=self._elapsed_ms(started_ns),
        )
        return result

    @staticmethod
    def _elapsed_ms(started_ns: int) -> int:
        return max(
            0,
            (perf_counter_ns() - started_ns) // 1_000_000,
        )
