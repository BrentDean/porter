from datetime import datetime

import pytest

from porter.intents import (
    CurrentDateHandler,
    CurrentTimeHandler,
    IntentResult,
    RecognizedIntent,
)
from tests.fakes import make_request


def fixed_now() -> datetime:
    return datetime(2026, 8, 13, 16, 57, 30)


@pytest.mark.asyncio
async def test_current_time_handler_returns_local_time() -> None:
    handler = CurrentTimeHandler(now=fixed_now)

    result = await handler.handle(
        make_request(),
        RecognizedIntent(
            name="HassGetCurrentTime",
            slots={},
        )
    )

    assert result == IntentResult(
        text="4:57 PM",
        data={
            "time": fixed_now().time(),
        },
    )


@pytest.mark.asyncio
async def test_current_date_handler_returns_local_date() -> None:
    handler = CurrentDateHandler(now=fixed_now)

    result = await handler.handle(
        make_request(),
        RecognizedIntent(
            name="HassGetCurrentDate",
            slots={},
        )
    )

    assert result == IntentResult(
        text="Thursday, August 13, 2026",
        data={
            "date": fixed_now().date(),
        },
    )


def test_time_date_handlers_expose_expected_intent_names() -> None:
    assert CurrentTimeHandler.intent_name == "HassGetCurrentTime"
    assert CurrentDateHandler.intent_name == "HassGetCurrentDate"
