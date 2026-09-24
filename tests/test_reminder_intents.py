from __future__ import annotations

from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from porter.app import build_application
from porter.core.models import Message, RequestContext, RequestSource
from porter.intents import (
    IntentResult,
    PorterIntentRecognizer,
    RecognizedIntent,
    ReminderCancelHandler,
    ReminderCreateHandler,
    ReminderListHandler,
)
from porter.reminders import (
    ReminderService,
    ReminderStatus,
    SqliteReminderRepository,
)
from porter.storage.database import Database
from porter.storage.migrations import MigrationRunner

TORONTO = ZoneInfo("America/Toronto")
NOW = datetime(2026, 8, 15, 16, tzinfo=UTC)


def _request(
    text: str,
    *,
    principal_id: str = "alice",
) -> RequestContext:
    return RequestContext(
        messages=(Message(role="user", content=text),),
        principal_id=principal_id,
        source=RequestSource.CLI,
    )


def _service(
    tmp_path: Path,
    *,
    now: datetime = NOW,
) -> ReminderService:
    database = Database(tmp_path / "porter.db")
    MigrationRunner(database).apply_all()
    repository = SqliteReminderRepository(database)
    identifiers = count(1)
    return ReminderService(
        repository,
        clock=lambda: now,
        id_generator=lambda: f"reminder-{next(identifiers)}",
    )


@pytest.mark.parametrize(
    ("text", "intent_name", "expected_slots"),
    [
        (
            "remind me to stretch in 30 minutes",
            "PorterReminderCreate",
            {
                "message": "stretch",
                "amount": 30,
                "schedule_kind": "relative",
                "unit": "minutes",
            },
        ),
        (
            "remind me in 2 hours to call mom",
            "PorterReminderCreate",
            {
                "message": "call mom",
                "amount": 2,
                "schedule_kind": "relative",
                "unit": "hours",
            },
        ),
        (
            "remind me to take out the garbage at 7 pm",
            "PorterReminderCreate",
            {
                "message": "take out the garbage",
                "hour": 7,
                "meridiem": "pm",
                "schedule_kind": "clock",
            },
        ),
        (
            "remind me at 7:30 pm to take out the garbage",
            "PorterReminderCreate",
            {
                "message": "take out the garbage",
                "hour": 7,
                "minute": 30,
                "meridiem": "pm",
                "schedule_kind": "clock",
            },
        ),
        (
            "remind me to call mom tomorrow at 8 am",
            "PorterReminderCreate",
            {
                "message": "call mom",
                "day": "tomorrow",
                "hour": 8,
                "meridiem": "am",
                "schedule_kind": "clock",
            },
        ),
        (
            "show my reminders",
            "PorterReminderList",
            {},
        ),
        (
            "cancel my reminder to call mom",
            "PorterReminderCancel",
            {"message": "call mom"},
        ),
    ],
)
def test_recognizes_reminder_sentences(
    text: str,
    intent_name: str,
    expected_slots: dict[str, object],
) -> None:
    recognizer = PorterIntentRecognizer(
        supported_intents=frozenset(
            {
                "PorterReminderCreate",
                "PorterReminderList",
                "PorterReminderCancel",
            }
        )
    )

    result = recognizer.recognize(text)

    assert result is not None
    assert result.name == intent_name
    for name, value in expected_slots.items():
        assert result.slots[name] == value


def test_reminder_recognizer_rejects_invalid_clock_hour() -> None:
    recognizer = PorterIntentRecognizer(
        supported_intents=frozenset({"PorterReminderCreate"})
    )

    assert recognizer.recognize("remind me to stretch at 13 pm") is None


@pytest.mark.asyncio
async def test_relative_reminder_uses_elapsed_time_and_local_timezone(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    handler = ReminderCreateHandler(
        service,
        clock=lambda: NOW,
        timezone_provider=lambda: TORONTO,
    )

    result = await handler.handle(
        _request("ignored"),
        RecognizedIntent(
            name="PorterReminderCreate",
            slots={
                "message": "stretch",
                "schedule_kind": "relative",
                "amount": 30,
                "unit": "minutes",
            },
        ),
    )

    reminders = service.list_reminders(
        "alice",
        status=ReminderStatus.SCHEDULED,
    )
    assert len(reminders) == 1
    assert reminders[0].message == "stretch"
    assert reminders[0].trigger_at == datetime(
        2026,
        8,
        15,
        12,
        30,
        tzinfo=TORONTO,
    )
    assert result.data["outcome"] == "succeeded"
    assert result.data["schedule_kind"] == "relative"
    assert result.data["timezone"] == "America/Toronto"


@pytest.mark.asyncio
async def test_clock_reminder_uses_today_when_time_is_still_ahead(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    handler = ReminderCreateHandler(
        service,
        clock=lambda: NOW,
        timezone_provider=lambda: TORONTO,
    )

    result = await handler.handle(
        _request("ignored"),
        RecognizedIntent(
            name="PorterReminderCreate",
            slots={
                "message": "take out the garbage",
                "schedule_kind": "clock",
                "hour": 7,
                "meridiem": "pm",
            },
        ),
    )

    reminder = service.list_reminders("alice")[0]
    assert reminder.trigger_at == datetime(
        2026,
        8,
        15,
        19,
        0,
        tzinfo=TORONTO,
    )
    assert result.data["reminder_id"] == reminder.id


@pytest.mark.asyncio
async def test_clock_reminder_rolls_to_tomorrow_after_time_has_passed(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    handler = ReminderCreateHandler(
        service,
        clock=lambda: NOW,
        timezone_provider=lambda: TORONTO,
    )

    await handler.handle(
        _request("ignored"),
        RecognizedIntent(
            name="PorterReminderCreate",
            slots={
                "message": "morning thing",
                "schedule_kind": "clock",
                "hour": 11,
                "meridiem": "am",
            },
        ),
    )

    reminder = service.list_reminders("alice")[0]
    assert reminder.trigger_at == datetime(
        2026,
        8,
        16,
        11,
        0,
        tzinfo=TORONTO,
    )


@pytest.mark.asyncio
async def test_explicit_today_rejects_time_that_has_passed(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    handler = ReminderCreateHandler(
        service,
        clock=lambda: NOW,
        timezone_provider=lambda: TORONTO,
    )

    result = await handler.handle(
        _request("ignored"),
        RecognizedIntent(
            name="PorterReminderCreate",
            slots={
                "message": "morning thing",
                "schedule_kind": "clock",
                "day": "today",
                "hour": 11,
                "meridiem": "am",
            },
        ),
    )

    assert result.data["outcome"] == "invalid_time"
    assert service.list_reminders("alice") == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("hour", "meridiem", "expected_hour"),
    [
        (12, "am", 0),
        (12, "pm", 12),
        (1, "pm", 13),
    ],
)
async def test_clock_reminder_converts_twelve_hour_clock(
    tmp_path: Path,
    hour: int,
    meridiem: str,
    expected_hour: int,
) -> None:
    now = datetime(2026, 8, 15, 2, tzinfo=UTC)
    service = _service(tmp_path, now=now)
    handler = ReminderCreateHandler(
        service,
        clock=lambda: now,
        timezone_provider=lambda: TORONTO,
    )

    await handler.handle(
        _request("ignored"),
        RecognizedIntent(
            name="PorterReminderCreate",
            slots={
                "message": "clock test",
                "schedule_kind": "clock",
                "day": "tomorrow",
                "hour": hour,
                "meridiem": meridiem,
            },
        ),
    )

    reminder = service.list_reminders("alice")[0]
    assert reminder.trigger_at.hour == expected_hour


@pytest.mark.asyncio
async def test_clock_reminder_rejects_nonexistent_dst_wall_time(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 3, 8, 6, 0, tzinfo=UTC)
    service = _service(tmp_path, now=now)
    handler = ReminderCreateHandler(
        service,
        clock=lambda: now,
        timezone_provider=lambda: TORONTO,
    )

    result = await handler.handle(
        _request("ignored"),
        RecognizedIntent(
            name="PorterReminderCreate",
            slots={
                "message": "dst test",
                "schedule_kind": "clock",
                "day": "today",
                "hour": 2,
                "minute": 30,
                "meridiem": "am",
            },
        ),
    )

    assert result.data["outcome"] == "invalid_time"
    assert "does not exist" in result.text
    assert service.list_reminders("alice") == ()


@pytest.mark.asyncio
async def test_clock_reminder_rejects_ambiguous_dst_wall_time(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 11, 1, 4, 30, tzinfo=UTC)
    service = _service(tmp_path, now=now)
    handler = ReminderCreateHandler(
        service,
        clock=lambda: now,
        timezone_provider=lambda: TORONTO,
    )

    result = await handler.handle(
        _request("ignored"),
        RecognizedIntent(
            name="PorterReminderCreate",
            slots={
                "message": "dst test",
                "schedule_kind": "clock",
                "day": "today",
                "hour": 1,
                "minute": 30,
                "meridiem": "am",
            },
        ),
    )

    assert result.data["outcome"] == "invalid_time"
    assert "ambiguous" in result.text
    assert service.list_reminders("alice") == ()


@pytest.mark.asyncio
async def test_reminder_list_is_principal_scoped_and_text_is_bounded(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    for index in range(7):
        service.create_reminder(
            "alice",
            f"Task {index + 1}",
            datetime(2026, 8, 16, 9 + index, tzinfo=TORONTO),
        )
    service.create_reminder(
        "bob",
        "Bob reminder",
        datetime(2026, 8, 16, 9, tzinfo=TORONTO),
    )
    handler = ReminderListHandler(
        service,
        timezone_provider=lambda: TORONTO,
    )

    result = await handler.handle(
        _request("ignored"),
        RecognizedIntent(name="PorterReminderList", slots={}),
    )

    assert result.data["count"] == 7
    assert len(result.data["reminder_ids"]) == 7
    assert len(result.data["messages"]) == 7
    assert "and 2 more" in result.text
    assert "Bob reminder" not in result.text


@pytest.mark.asyncio
async def test_cancel_reminder_matches_exact_message(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    reminder = service.create_reminder(
        "alice",
        "Take Out Garbage",
        datetime(2026, 8, 15, 19, tzinfo=TORONTO),
    )
    handler = ReminderCancelHandler(service)

    result = await handler.handle(
        _request("ignored"),
        RecognizedIntent(
            name="PorterReminderCancel",
            slots={"message": "take out garbage"},
        ),
    )

    cancelled = service.get_reminder("alice", reminder.id)
    assert cancelled.status is ReminderStatus.CANCELLED
    assert result.data["outcome"] == "succeeded"
    assert result.data["reminder_id"] == reminder.id


@pytest.mark.asyncio
async def test_cancel_reminder_refuses_ambiguous_message_but_accepts_id(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    first = service.create_reminder(
        "alice",
        "Call mom",
        datetime(2026, 8, 15, 19, tzinfo=TORONTO),
    )
    second = service.create_reminder(
        "alice",
        "Call mom",
        datetime(2026, 8, 16, 19, tzinfo=TORONTO),
    )
    handler = ReminderCancelHandler(service)

    ambiguous = await handler.handle(
        _request("ignored"),
        RecognizedIntent(
            name="PorterReminderCancel",
            slots={"message": "call mom"},
        ),
    )
    assert ambiguous.data["outcome"] == "ambiguous"
    assert set(ambiguous.data["candidate_reminder_ids"]) == {
        first.id,
        second.id,
    }

    cancelled = await handler.handle(
        _request("ignored"),
        RecognizedIntent(
            name="PorterReminderCancel",
            slots={"message": first.id},
        ),
    )
    assert cancelled.data["outcome"] == "succeeded"
    assert cancelled.data["reminder_id"] == first.id


@pytest.mark.asyncio
async def test_cancel_reminder_does_not_cross_principal_scope(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    service.create_reminder(
        "bob",
        "Call mom",
        datetime(2026, 8, 15, 19, tzinfo=TORONTO),
    )
    handler = ReminderCancelHandler(service)

    result = await handler.handle(
        _request("ignored"),
        RecognizedIntent(
            name="PorterReminderCancel",
            slots={"message": "call mom"},
        ),
    )

    assert result.data["outcome"] == "not_found"
    assert service.list_reminders("alice") == ()
    assert len(service.list_reminders("bob")) == 1


@pytest.mark.asyncio
async def test_bootstrapped_reminder_intents_route_deterministically(
    tmp_path: Path,
) -> None:
    application = build_application(
        env={"PORTER_DATA_DIR": str(tmp_path)},
        home=tmp_path,
    )

    created = await application.deterministic_executor.execute(
        _request("remind me to stretch in 10 minutes")
    )

    assert isinstance(created, IntentResult)
    assert created.data["intent"] == "PorterReminderCreate"
    assert created.data["outcome"] == "succeeded"

    reminders = application.reminder_service.list_reminders(
        "alice",
        status=ReminderStatus.SCHEDULED,
    )
    assert len(reminders) == 1
    assert reminders[0].message == "stretch"

    listed = await application.deterministic_executor.execute(
        _request("show my reminders")
    )
    assert isinstance(listed, IntentResult)
    assert listed.data["intent"] == "PorterReminderList"
    assert listed.data["count"] == 1
