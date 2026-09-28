from __future__ import annotations

import pytest

from porter.core.models import RequestContext
from porter.tools import Tool, ToolExecutor, ToolRegistry, ToolResult
from tests.fakes import make_request


class FakeTool(Tool):
    name = "fake"

    def __init__(self, *, supported: bool = True) -> None:
        self.supported = supported
        self.calls = 0

    def supports(self, request: RequestContext) -> bool:
        return self.supported

    async def execute(self, request: RequestContext) -> ToolResult:
        self.calls += 1
        return ToolResult(
            text="tool result",
            data={"source": self.name},
        )


def test_tool_registry_returns_registered_tool() -> None:
    tool = FakeTool()
    registry = ToolRegistry((tool,))

    assert registry.all() == (tool,)
    assert registry.get("fake") is tool


def test_tool_registry_rejects_duplicate_names() -> None:
    with pytest.raises(
        ValueError,
        match="tool names must be unique",
    ):
        ToolRegistry((FakeTool(), FakeTool()))


def test_tool_result_copies_and_freezes_data() -> None:
    data = {"value": 10}
    result = ToolResult(text="10", data=data)

    data["value"] = 20

    assert result.data["value"] == 10

    with pytest.raises(TypeError):
        result.data["value"] = 30  # type: ignore[index]


@pytest.mark.asyncio
async def test_tool_executor_executes_selected_tool() -> None:
    tool = FakeTool()
    executor = ToolExecutor(ToolRegistry((tool,)))

    result = await executor.execute(
        make_request(),
        "fake",
    )

    assert result == ToolResult(
        text="tool result",
        data={"source": "fake"},
    )
    assert tool.calls == 1


@pytest.mark.asyncio
async def test_tool_executor_rejects_unsupported_request() -> None:
    tool = FakeTool(supported=False)
    executor = ToolExecutor(ToolRegistry((tool,)))

    with pytest.raises(
        ValueError,
        match="tool does not support request: fake",
    ):
        await executor.execute(
            make_request(),
            "fake",
        )

    assert tool.calls == 0
