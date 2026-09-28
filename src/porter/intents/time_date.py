from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from porter.core.clock import local_now
from porter.core.models import RequestContext
from porter.intents.handlers import IntentHandler
from porter.intents.models import IntentResult, RecognizedIntent


def _format_time(value: datetime) -> str:
    hour = value.hour % 12 or 12
    period = "AM" if value.hour < 12 else "PM"
    return f"{hour}:{value.minute:02d} {period}"


def _format_date(value: datetime) -> str:
    return (
        f"{value.strftime('%A, %B')} "
        f"{value.day}, "
        f"{value.year}"
    )


class CurrentTimeHandler(IntentHandler):
    intent_name = "HassGetCurrentTime"

    def __init__(
        self,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._now = now or local_now

    async def handle(
        self,
        request: RequestContext,
        intent: RecognizedIntent,
    ) -> IntentResult:
        current = self._now()

        return IntentResult(
            text=_format_time(current),
            data={
                "time": current.time(),
            },
        )


class CurrentDateHandler(IntentHandler):
    intent_name = "HassGetCurrentDate"

    def __init__(
        self,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._now = now or local_now

    async def handle(
        self,
        request: RequestContext,
        intent: RecognizedIntent,
    ) -> IntentResult:
        current = self._now()

        return IntentResult(
            text=_format_date(current),
            data={
                "date": current.date(),
            },
        )
