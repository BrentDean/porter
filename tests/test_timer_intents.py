from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from porter.app import build_application
from porter.core.models import Message, RequestContext, RequestSource
from porter.intents import PorterIntentRecognizer, RecognizedIntent
from porter.reminders import (
    ReminderKind,
    ReminderRunner,
    ReminderService,
    ReminderStatus,
    ReminderValidationError,
    SqliteReminderRepository,
)
from porter.reminders.intents import (
    ReminderCancelHandler,
    ReminderCreateHandler,
    ReminderListHandler,
    TimerCancelHandler,
    TimerCreateHandler,
    TimerListHandler,
)
from porter.storage.database import Database
from porter.storage.migrations import MigrationRunner

NOW = datetime(2026, 8, 15, 16, tzinfo=UTC)
NEW_YORK = ZoneInfo("America/New_York")


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class RecordingDelivery:
    def __init__(self) -> None:
        self.delivered = []

    async def deliver(self, reminder) -> None:
        self.delivered.append(reminder)


def _request(text: str = "unused", principal_id: str = "alice") -> RequestContext:
    return RequestContext(
        messages=(Message(role="user", content=text),),
        principal_id=principal_id,
        source=RequestSource.CLI,
    )


def _runtime(tmp_path: Path, clock: MutableClock):
    database = Database(tmp_path / "porter.db")
    MigrationRunner(database).apply_all()
    repository = SqliteReminderRepository(database)
    service = ReminderService(repository, clock=clock)
    return database, repository, service


@pytest.mark.parametrize(
    ("phrase", "name", "slots"),
    [
        (
            "remind me in 10 seconds to test the popup",
            "PorterReminderCreate",
            {"amount": 10, "unit": "seconds", "message": "test the popup"},
        ),
        (
            "set a timer for 30 seconds",
            "PorterTimerCreate",
            {"amount": 30, "unit": "seconds"},
        ),
        (
            "start a 5 minute timer",
            "PorterTimerCreate",
            {"amount": 5, "unit": "minutes"},
        ),
        (
            "set a timer for 30 seconds called tea",
            "PorterTimerCreate",
            {"amount": 30, "unit": "seconds", "message": "tea"},
        ),
        (
            "set a timer for 1 hour",
            "PorterTimerCreate",
            {"amount": 1, "unit": "hours"},
        ),
        ("show my timers", "PorterTimerList", {}),
        ("cancel my timer", "PorterTimerCancel", {}),
        ("stop my timer", "PorterTimerCancel", {}),
        (
            "cancel my timer called tea",
            "PorterTimerCancel",
            {"message": "tea"},
        ),
    ],
)
def test_timer_phrases_are_deterministic(
    phrase: str,
    name: str,
    slots: dict[str, object],
) -> None:
    recognizer = PorterIntentRecognizer(
        supported_intents=frozenset(
            {
                "PorterReminderCreate",
                "PorterTimerCreate",
                "PorterTimerList",
                "PorterTimerCancel",
            }
        ),
    )

    result = recognizer.recognize(phrase)

    assert result is not None
    assert result.name == name
    for key, value in slots.items():
        assert result.slots[key] == value


@pytest.mark.asyncio
async def test_second_reminder_is_precise_and_stays_reminder(tmp_path: Path) -> None:
    clock = MutableClock(NOW)
    _, _, service = _runtime(tmp_path, clock)
    handler = ReminderCreateHandler(
        service,
        clock=clock,
        timezone_provider=lambda: NEW_YORK,
    )

    result = await handler.handle(
        _request(),
        RecognizedIntent(
            name="PorterReminderCreate",
            slots={
                "message": "test the popup",
                "schedule_kind": "relative",
                "amount": 10,
                "unit": "seconds",
            },
        ),
    )

    reminder = service.list_reminders("alice")[0]
    assert reminder.trigger_at.astimezone(UTC) == NOW + timedelta(seconds=10)
    assert reminder.kind is ReminderKind.REMINDER
    assert reminder.duration_seconds is None
    assert result.data["outcome"] == "succeeded"
    assert "12:00:10 PM" in result.text


@pytest.mark.asyncio
async def test_timer_round_trips_through_sqlite_and_delivers_once(tmp_path: Path) -> None:
    clock = MutableClock(NOW)
    database, repository, service = _runtime(tmp_path, clock)
    handler = TimerCreateHandler(
        service,
        timezone_provider=lambda: NEW_YORK,
    )

    result = await handler.handle(
        _request(),
        RecognizedIntent(
            name="PorterTimerCreate",
            slots={"amount": 30, "unit": "seconds"},
        ),
    )
    timer = service.get_reminder("alice", result.data["timer_id"])
    assert timer.kind is ReminderKind.TIMER
    assert timer.duration_seconds == 30
    assert timer.trigger_at == NOW + timedelta(seconds=30)
    assert "30 seconds" in result.text
    assert "12:00:30 PM" in result.text

    reopened = ReminderService(SqliteReminderRepository(Database(database.path)), clock=clock)
    assert reopened.get_reminder("alice", timer.id) == timer
    delivery = RecordingDelivery()
    runner = ReminderRunner(repository, service, delivery, clock=clock)
    assert (await runner.run_once()).delivered == 0

    clock.value = NOW + timedelta(seconds=30)
    assert (await runner.run_once()).delivered == 1
    assert (await runner.run_once()).delivered == 0
    assert delivery.delivered[0].kind is ReminderKind.TIMER
    assert service.get_reminder("alice", timer.id).status is ReminderStatus.DELIVERED

    clock.value += timedelta(seconds=5)
    restarted = service.restart_timer("alice", timer.id)
    assert restarted.trigger_at == NOW + timedelta(seconds=65)
    assert restarted.status is ReminderStatus.SCHEDULED
    assert restarted.duration_seconds == 30


@pytest.mark.asyncio
async def test_timer_list_and_cancel_respect_principals_and_ambiguity(
    tmp_path: Path,
) -> None:
    clock = MutableClock(NOW)
    _, _, service = _runtime(tmp_path, clock)
    tea = service.create_timer("alice", timedelta(seconds=30), label="tea")
    second = service.create_timer("alice", timedelta(minutes=2), label="laundry")
    service.create_timer("bob", timedelta(minutes=2), label="secret")
    service.create_reminder("alice", "not a timer", NOW + timedelta(minutes=3))
    list_handler = TimerListHandler(service, clock=clock)
    cancel = TimerCancelHandler(service)

    reminder_listing = await ReminderListHandler(service).handle(
        _request(), RecognizedIntent(name="PorterReminderList", slots={})
    )
    assert reminder_listing.data["count"] == 1
    assert "not a timer" in reminder_listing.text
    assert "tea" not in reminder_listing.text

    wrong_kind = await ReminderCancelHandler(service).handle(
        _request(),
        RecognizedIntent(
            name="PorterReminderCancel",
            slots={"message": "tea"},
        ),
    )
    assert wrong_kind.data["outcome"] == "not_found"

    listing = await list_handler.handle(
        _request(), RecognizedIntent(name="PorterTimerList", slots={})
    )
    assert listing.data["count"] == 2
    assert "00:30 remaining" in listing.text
    assert "02:00 remaining" in listing.text
    assert "secret" not in listing.text
    assert "not a timer" not in listing.text

    ambiguous = await cancel.handle(
        _request(), RecognizedIntent(name="PorterTimerCancel", slots={})
    )
    assert ambiguous.data["outcome"] == "ambiguous"
    assert set(ambiguous.data["candidate_timer_ids"]) == {tea.id, second.id}

    cancelled = await cancel.handle(
        _request(),
        RecognizedIntent(
            name="PorterTimerCancel",
            slots={"message": tea.id},
        ),
    )
    assert cancelled.data["outcome"] == "succeeded"
    assert service.get_reminder("alice", tea.id).status is ReminderStatus.CANCELLED
    assert service.get_reminder("alice", second.id).status is ReminderStatus.SCHEDULED


@pytest.mark.asyncio
async def test_bootstrapped_timer_routes_without_inference(tmp_path: Path) -> None:
    application = build_application(
        env={"PORTER_DATA_DIR": str(tmp_path)},
        home=tmp_path,
    )
    created = await application.deterministic_executor.execute(
        _request("set a timer for 30 seconds")
    )

    assert created is not None
    assert created.data["intent"] == "PorterTimerCreate"
    timers = application.reminder_service.list_reminders("alice")
    assert len(timers) == 1
    assert timers[0].kind is ReminderKind.TIMER


@pytest.mark.parametrize(
    "duration",
    [
        timedelta(0),
        timedelta(seconds=-1),
        timedelta(milliseconds=500),
        timedelta(hours=101),
    ],
)
def test_rejects_invalid_timer_durations(
    tmp_path: Path,
    duration: timedelta,
) -> None:
    _, _, service = _runtime(tmp_path, MutableClock(NOW))
    with pytest.raises(ReminderValidationError, match="timer duration"):
        service.create_timer("alice", duration)
