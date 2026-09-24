import pytest

from porter.tools import QalculateTool


@pytest.mark.asyncio
async def test_qalculate_executes_arithmetic() -> None:
    result = await QalculateTool().execute_expression("5+6")

    assert result.text == "11"
    assert result.data["expression"] == "5+6"


@pytest.mark.asyncio
async def test_qalculate_executes_unit_conversion() -> None:
    result = await QalculateTool().execute_expression(
        "1 gallon to cups"
    )

    assert "16" in result.text
    assert "cup" in result.text.lower()
