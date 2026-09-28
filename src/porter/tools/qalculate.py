from __future__ import annotations

import asyncio
from asyncio.subprocess import PIPE

from porter.core.models import RequestContext
from porter.tools.base import Tool
from porter.tools.models import ToolResult
from porter.tools.selector import select_qalculate_expression


class QalculateTool(Tool):
    name = "qalculate"

    def __init__(
        self,
        *,
        executable: str = "qalc",
        timeout_seconds: float = 10.0,
    ) -> None:
        self._executable = executable
        self._timeout_seconds = timeout_seconds

    def supports(self, request: RequestContext) -> bool:
        return self._expression(request) is not None

    async def execute(self, request: RequestContext) -> ToolResult:
        expression = self._expression(request)
        if expression is None:
            raise ValueError("Qalculate does not support request")

        return await self.execute_expression(expression)

    async def execute_expression(
        self,
        expression: str,
    ) -> ToolResult:
        process = await asyncio.create_subprocess_exec(
            self._executable,
            "--terse",
            expression,
            stdout=PIPE,
            stderr=PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self._timeout_seconds,
            )
        except TimeoutError:
            process.kill()
            await process.communicate()
            raise RuntimeError("Qalculate timed out") from None

        output = stdout.decode().strip()
        error = stderr.decode().strip()

        if process.returncode != 0:
            detail = error or output or "unknown Qalculate error"
            raise RuntimeError(f"Qalculate failed: {detail}")

        if not output:
            raise RuntimeError("Qalculate returned no result")

        return ToolResult(
            text=output,
            data={
                "expression": expression,
            },
        )

    @staticmethod
    def _expression(request: RequestContext) -> str | None:
        text = request.latest_user_text
        if text is None:
            return None
        return select_qalculate_expression(text)
