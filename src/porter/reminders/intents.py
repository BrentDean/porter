from __future__ import annotations

import unicodedata
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from math import ceil
from zoneinfo import ZoneInfo

from porter.core.clock import system_timezone, utc_now
from porter.core.models import RequestContext
from porter.intents.handlers import IntentHandler
from porter.intents.models import IntentResult, RecognizedIntent
from porter.reminders import ReminderKind, ReminderService, ReminderStatus

_TEXT_ITEM_LIMIT = 5


class _LocalWallTimeError(ValueError):
    pass


def _required_text_slot(intent: RecognizedIntent, name: str) -> str:
    value = intent.slots.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"intent slot must be non-empty text: {name}")
    return value.strip()


def _optional_text_slot(intent: RecognizedIntent, name: str) -> str | None:
    value = intent.slots.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"intent slot must be non-empty text: {name}")
    return value.strip()


def _required_int_slot(intent: RecognizedIntent, name: str) -> int:
    value = intent.slots.get(name)
    if isinstance(value, bool):
        raise ValueError(f"intent slot must be an integer: {name}")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise ValueError(f"intent slot must be an integer: {name}")


def _optional_int_slot(
    intent: RecognizedIntent,
    name: str,
    *,
    default: int,
) -> int:
    if name not in intent.slots:
        return default
    return _required_int_slot(intent, name)


def _match_key(value: str) -> str:
    return unicodedata.normalize("NFKC", value.strip()).casefold()


def _format_trigger(
    value: datetime,
    timezone: ZoneInfo,
    *,
    show_seconds: bool = False,
) -> str:
    local = value.astimezone(timezone)
    hour = local.strftime("%I").lstrip("0") or "0"
    seconds = f":{local.strftime('%S')}" if show_seconds else ""
    return (
        f"{local.strftime('%A, %B')} {local.day} at "
        f"{hour}:{local.strftime('%M')}{seconds} {local.strftime('%p')}"
    )


def _duration(amount: int, unit: str) -> timedelta:
    if not 1 <= amount <= 100:
        raise ValueError("duration amount must be between 1 and 100")
    if unit == "seconds":
        return timedelta(seconds=amount)
    if unit == "minutes":
        return timedelta(minutes=amount)
    if unit == "hours":
        return timedelta(hours=amount)
    raise ValueError(f"unsupported duration unit: {unit}")


def _remaining_text(value: datetime, now: datetime) -> str:
    remaining = max(0, ceil((value.astimezone(UTC) - now).total_seconds()))
    hours, remainder = divmod(remaining, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}"


def _resolve_local_wall_time(
    day: date,
    *,
    hour: int,
    minute: int,
    timezone: ZoneInfo,
) -> datetime:
    naive = datetime.combine(day, time(hour=hour, minute=minute))
    candidates: list[datetime] = []

    for fold in (0, 1):
        candidate = naive.replace(tzinfo=timezone, fold=fold)
        round_trip = candidate.astimezone(UTC).astimezone(timezone)
        if (
            round_trip.replace(tzinfo=None) == naive
            and round_trip.fold == fold
        ):
            candidates.append(candidate)

    if not candidates:
        raise _LocalWallTimeError(
            "That local time does not exist because of a daylight-saving transition."
        )

    if (
        len(candidates) > 1
        and candidates[0].utcoffset() != candidates[1].utcoffset()
    ):
        raise _LocalWallTimeError(
            "That local time is ambiguous because of a daylight-saving transition."
        )

    return candidates[0]


def _clock_hour(hour: int, meridiem: str) -> int:
    normalized = meridiem.casefold()
    if normalized not in {"am", "pm"}:
        raise ValueError("meridiem must be am or pm")
    if not 1 <= hour <= 12:
        raise ValueError("clock hour must be between 1 and 12")
    if normalized == "am":
        return 0 if hour == 12 else hour
    return 12 if hour == 12 else hour + 12


class ReminderCreateHandler(IntentHandler):
    intent_name = "PorterReminderCreate"

    def __init__(
        self,
        reminder_service: ReminderService,
        *,
        clock: Callable[[], datetime] | None = None,
        timezone_provider: Callable[[], ZoneInfo] | None = None,
    ) -> None:
        self._reminder_service = reminder_service
        self._clock = clock or utc_now
        self._timezone_provider = timezone_provider or system_timezone

    async def handle(
        self,
        request: RequestContext,
        intent: RecognizedIntent,
    ) -> IntentResult:
        message = _required_text_slot(intent, "message")
        schedule_kind = _required_text_slot(intent, "schedule_kind")
        timezone = self._timezone_provider()
        now_utc = self._now_utc()
        now_local = now_utc.astimezone(timezone)

        if schedule_kind == "relative":
            trigger_at = self._relative_trigger(intent, now_utc, timezone)
        elif schedule_kind == "clock":
            try:
                trigger_at = self._clock_trigger(intent, now_local, timezone)
            except _LocalWallTimeError as exc:
                return IntentResult(
                    text=str(exc),
                    data={
                        "intent": self.intent_name,
                        "operation": "create",
                        "outcome": "invalid_time",
                        "message": message,
                        "timezone": timezone.key,
                    },
                )
            if trigger_at is None:
                return IntentResult(
                    text="That time has already passed today.",
                    data={
                        "intent": self.intent_name,
                        "operation": "create",
                        "outcome": "invalid_time",
                        "message": message,
                        "timezone": timezone.key,
                    },
                )
        else:
            raise ValueError(f"unsupported reminder schedule kind: {schedule_kind}")

        reminder = self._reminder_service.create_reminder(
            request.principal_id,
            message,
            trigger_at,
        )
        show_seconds = (
            schedule_kind == "relative"
            and _required_text_slot(intent, "unit") == "seconds"
        )
        return IntentResult(
            text=(
                f"I'll remind you to {reminder.message} on "
                f"{_format_trigger(reminder.trigger_at, timezone, show_seconds=show_seconds)}."
            ),
            data={
                "intent": self.intent_name,
                "operation": "create",
                "outcome": "succeeded",
                "reminder_id": reminder.id,
                "message": reminder.message,
                "status": reminder.status.value,
                "trigger_at": reminder.trigger_at,
                "timezone": timezone.key,
                "schedule_kind": schedule_kind,
            },
        )

    def _relative_trigger(
        self,
        intent: RecognizedIntent,
        now_utc: datetime,
        timezone: ZoneInfo,
    ) -> datetime:
        amount = _required_int_slot(intent, "amount")
        unit = _required_text_slot(intent, "unit")
        return (now_utc + _duration(amount, unit)).astimezone(timezone)

    def _clock_trigger(
        self,
        intent: RecognizedIntent,
        now_local: datetime,
        timezone: ZoneInfo,
    ) -> datetime | None:
        hour = _clock_hour(
            _required_int_slot(intent, "hour"),
            _required_text_slot(intent, "meridiem"),
        )
        minute = _optional_int_slot(intent, "minute", default=0)
        if not 0 <= minute <= 59:
            raise ValueError("clock minute must be between 0 and 59")

        day_value = _optional_text_slot(intent, "day")
        if day_value is None:
            target_day = now_local.date()
        elif day_value.casefold() == "today":
            target_day = now_local.date()
        elif day_value.casefold() == "tomorrow":
            target_day = now_local.date() + timedelta(days=1)
        else:
            raise ValueError(f"unsupported reminder day: {day_value}")

        trigger_at = _resolve_local_wall_time(
            target_day,
            hour=hour,
            minute=minute,
            timezone=timezone,
        )

        if day_value is None and trigger_at <= now_local:
            return _resolve_local_wall_time(
                target_day + timedelta(days=1),
                hour=hour,
                minute=minute,
                timezone=timezone,
            )

        if day_value is not None and day_value.casefold() == "today":
            if trigger_at <= now_local:
                return None

        return trigger_at

    def _now_utc(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("reminder intent clock must be timezone-aware")
        return value.astimezone(UTC)


class ReminderListHandler(IntentHandler):
    intent_name = "PorterReminderList"

    def __init__(
        self,
        reminder_service: ReminderService,
        *,
        timezone_provider: Callable[[], ZoneInfo] | None = None,
    ) -> None:
        self._reminder_service = reminder_service
        self._timezone_provider = timezone_provider or system_timezone

    async def handle(
        self,
        request: RequestContext,
        intent: RecognizedIntent,
    ) -> IntentResult:
        del intent
        timezone = self._timezone_provider()
        reminders = tuple(
            item
            for item in self._reminder_service.list_reminders(
                request.principal_id,
                status=ReminderStatus.SCHEDULED,
            )
            if item.kind is ReminderKind.REMINDER
        )
        if not reminders:
            text = "You have no scheduled reminders."
        else:
            visible = reminders[:_TEXT_ITEM_LIMIT]
            rendered = "; ".join(
                f"{reminder.message} — {_format_trigger(reminder.trigger_at, timezone)}"
                for reminder in visible
            )
            remaining = len(reminders) - len(visible)
            suffix = f"; and {remaining} more" if remaining else ""
            text = f"Reminders: {rendered}{suffix}."

        return IntentResult(
            text=text,
            data={
                "intent": self.intent_name,
                "operation": "list",
                "outcome": "succeeded",
                "count": len(reminders),
                "reminder_ids": tuple(reminder.id for reminder in reminders),
                "messages": tuple(reminder.message for reminder in reminders),
                "trigger_at": tuple(reminder.trigger_at for reminder in reminders),
                "timezone": timezone.key,
            },
        )


class ReminderCancelHandler(IntentHandler):
    intent_name = "PorterReminderCancel"

    def __init__(self, reminder_service: ReminderService) -> None:
        self._reminder_service = reminder_service

    async def handle(
        self,
        request: RequestContext,
        intent: RecognizedIntent,
    ) -> IntentResult:
        reminder_text = _required_text_slot(intent, "message")
        reminders = tuple(
            item
            for item in self._reminder_service.list_reminders(
                request.principal_id,
                status=ReminderStatus.SCHEDULED,
            )
            if item.kind is ReminderKind.REMINDER
        )

        id_matches = tuple(
            reminder for reminder in reminders if reminder.id == reminder_text
        )
        matches = id_matches
        if not matches:
            key = _match_key(reminder_text)
            matches = tuple(
                reminder
                for reminder in reminders
                if _match_key(reminder.message) == key
            )

        if not matches:
            return IntentResult(
                text=f"I couldn't find a scheduled reminder for {reminder_text}.",
                data={
                    "intent": self.intent_name,
                    "operation": "cancel",
                    "outcome": "not_found",
                    "message": reminder_text,
                },
            )

        if len(matches) > 1:
            return IntentResult(
                text=(
                    f"There is more than one scheduled reminder for {reminder_text}; "
                    "specify the reminder ID."
                ),
                data={
                    "intent": self.intent_name,
                    "operation": "cancel",
                    "outcome": "ambiguous",
                    "message": reminder_text,
                    "candidate_reminder_ids": tuple(
                        reminder.id for reminder in matches
                    ),
                },
            )

        reminder = self._reminder_service.cancel_reminder(
            request.principal_id,
            matches[0].id,
        )
        return IntentResult(
            text=f"Cancelled reminder to {reminder.message}.",
            data={
                "intent": self.intent_name,
                "operation": "cancel",
                "outcome": "succeeded",
                "reminder_id": reminder.id,
                "message": reminder.message,
                "status": reminder.status.value,
            },
        )


class TimerCreateHandler(IntentHandler):
    intent_name = "PorterTimerCreate"

    def __init__(
        self,
        reminder_service: ReminderService,
        *,
        timezone_provider: Callable[[], ZoneInfo] | None = None,
    ) -> None:
        self._reminder_service = reminder_service
        self._timezone_provider = timezone_provider or system_timezone

    async def handle(
        self,
        request: RequestContext,
        intent: RecognizedIntent,
    ) -> IntentResult:
        amount = _required_int_slot(intent, "amount")
        unit = _required_text_slot(intent, "unit")
        duration = _duration(amount, unit)
        label = _optional_text_slot(intent, "message") or "Timer"
        timer = self._reminder_service.create_timer(
            request.principal_id,
            duration,
            label=label,
        )
        timezone = self._timezone_provider()
        singular = unit[:-1] if amount == 1 else unit
        return IntentResult(
            text=(
                f"Timer set for {amount} {singular} — "
                f"{_format_trigger(timer.trigger_at, timezone, show_seconds=True)}."
            ),
            data={
                "intent": self.intent_name,
                "operation": "create",
                "outcome": "succeeded",
                "timer_id": timer.id,
                "message": timer.message,
                "duration_seconds": timer.duration_seconds,
                "trigger_at": timer.trigger_at,
                "timezone": timezone.key,
            },
        )


class TimerListHandler(IntentHandler):
    intent_name = "PorterTimerList"

    def __init__(
        self,
        reminder_service: ReminderService,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._reminder_service = reminder_service
        self._clock = clock or utc_now

    async def handle(
        self,
        request: RequestContext,
        intent: RecognizedIntent,
    ) -> IntentResult:
        del intent
        timers = tuple(
            reminder
            for reminder in self._reminder_service.list_reminders(
                request.principal_id,
                status=ReminderStatus.SCHEDULED,
            )
            if reminder.kind is ReminderKind.TIMER
        )
        now = self._clock().astimezone(UTC)
        visible = timers[:_TEXT_ITEM_LIMIT]
        rendered = "; ".join(
            f"{timer.message} ({_remaining_text(timer.trigger_at, now)} remaining)"
            for timer in visible
        )
        more = len(timers) - len(visible)
        suffix = f"; and {more} more" if more else ""
        text = (
            f"Timers: {rendered}{suffix}."
            if timers
            else "You have no active timers."
        )
        return IntentResult(
            text=text,
            data={
                "intent": self.intent_name,
                "operation": "list",
                "outcome": "succeeded",
                "count": len(timers),
                "timer_ids": tuple(timer.id for timer in timers),
                "trigger_at": tuple(timer.trigger_at for timer in timers),
            },
        )


class TimerCancelHandler(IntentHandler):
    intent_name = "PorterTimerCancel"

    def __init__(self, reminder_service: ReminderService) -> None:
        self._reminder_service = reminder_service

    async def handle(
        self,
        request: RequestContext,
        intent: RecognizedIntent,
    ) -> IntentResult:
        text = _optional_text_slot(intent, "message")
        timers = tuple(
            reminder
            for reminder in self._reminder_service.list_reminders(
                request.principal_id,
                status=ReminderStatus.SCHEDULED,
            )
            if reminder.kind is ReminderKind.TIMER
        )
        matches = timers
        if text is not None:
            matches = tuple(
                timer
                for timer in timers
                if timer.id == text or _match_key(timer.message) == _match_key(text)
            )

        if not matches:
            return IntentResult(
                text="I couldn't find an active timer.",
                data={
                    "intent": self.intent_name,
                    "operation": "cancel",
                    "outcome": "not_found",
                },
            )
        if len(matches) > 1:
            return IntentResult(
                text="More than one timer matches; specify the timer ID.",
                data={
                    "intent": self.intent_name,
                    "operation": "cancel",
                    "outcome": "ambiguous",
                    "candidate_timer_ids": tuple(timer.id for timer in matches),
                },
            )

        cancelled = self._reminder_service.cancel_reminder(
            request.principal_id,
            matches[0].id,
        )
        return IntentResult(
            text=f"Cancelled timer {cancelled.message}.",
            data={
                "intent": self.intent_name,
                "operation": "cancel",
                "outcome": "succeeded",
                "timer_id": cancelled.id,
            },
        )
