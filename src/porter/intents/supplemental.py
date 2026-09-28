from __future__ import annotations

from copy import deepcopy
from typing import Any

PORTER_SUPPLEMENTAL_LISTS: dict[str, dict[str, Any]] = {
    "porter_meridiem": {
        "values": [
            {"in": "am", "out": "am"},
            {"in": "a m", "out": "am"},
            {"in": "pm", "out": "pm"},
            {"in": "p m", "out": "pm"},
        ]
    },
    "porter_reminder_day": {
        "values": [
            {"in": "today", "out": "today"},
            {"in": "tomorrow", "out": "tomorrow"},
        ]
    },
}


PORTER_SUPPLEMENTAL_INTENTS: dict[str, dict[str, Any]] = {
    "HassGetCurrentDate": {
        "data": [
            {
                "sentences": [
                    "what day is it",
                    "what day is it today",
                    "what is the day today",
                ],
                "metadata": {
                    "slot_combination": "default",
                },
                "response": "default",
            }
        ]
    },
    "PorterPlannerToday": {
        "data": [
            {
                "sentences": [
                    "what tasks are due today",
                    "what tasks do i have today",
                    "show me my tasks for today",
                    "show my tasks for today",
                    "show me my tasks due today",
                    "show my tasks due today",
                ],
                "metadata": {"slot_combination": "default"},
                "response": "default",
            }
        ]
    },
    "PorterPlannerOverdue": {
        "data": [
            {
                "sentences": [
                    "what tasks are overdue",
                    "do i have any overdue tasks",
                    "show me my overdue tasks",
                    "show my overdue tasks",
                ],
                "metadata": {"slot_combination": "default"},
                "response": "default",
            }
        ]
    },
    "PorterPlannerUpcoming": {
        "data": [
            {
                "sentences": [
                    "what tasks are coming up",
                    "what tasks are due soon",
                    "show me my upcoming tasks",
                    "show my upcoming tasks",
                ],
                "metadata": {"slot_combination": "default"},
                "response": "default",
            }
        ]
    },
    "PorterPlannerUnscheduled": {
        "data": [
            {
                "sentences": [
                    "what tasks are unscheduled",
                    "what tasks have no due date",
                    "show me my unscheduled tasks",
                    "show my unscheduled tasks",
                ],
                "metadata": {"slot_combination": "default"},
                "response": "default",
            }
        ]
    },
    "PorterTimerCreate": {
        "data": [
            {
                "sentences": [
                    "set [a] timer for {1..100:amount} second[s]",
                    "set [a] timer for {1..100:amount} second[s] "
                    "called {timer_command:message}",
                    "start [a] timer for {1..100:amount} second[s]",
                    "set [a] {1..100:amount} second[s] timer",
                    "start [a] {1..100:amount} second[s] timer",
                ],
                "slots": {"unit": "seconds"},
                "metadata": {"slot_combination": "seconds"},
                "response": "default",
            },
            {
                "sentences": [
                    "set [a] timer for {1..100:amount} minute[s]",
                    "set [a] timer for {1..100:amount} minute[s] "
                    "called {timer_command:message}",
                    "start [a] timer for {1..100:amount} minute[s]",
                    "set [a] {1..100:amount} minute[s] timer",
                    "start [a] {1..100:amount} minute[s] timer",
                ],
                "slots": {"unit": "minutes"},
                "metadata": {"slot_combination": "minutes"},
                "response": "default",
            },
            {
                "sentences": [
                    "set [a] timer for {1..100:amount} hour[s]",
                    "set [a] timer for {1..100:amount} hour[s] "
                    "called {timer_command:message}",
                    "start [a] timer for {1..100:amount} hour[s]",
                    "set [a] {1..100:amount} hour[s] timer",
                    "start [a] {1..100:amount} hour[s] timer",
                ],
                "slots": {"unit": "hours"},
                "metadata": {"slot_combination": "hours"},
                "response": "default",
            },
        ]
    },
    "PorterTimerList": {
        "data": [
            {
                "sentences": [
                    "show [me] [my] timer[s]",
                    "list [my] timer[s]",
                    "what timer[s] [do i have]",
                    "how much time is left on my timer",
                ],
                "metadata": {"slot_combination": "default"},
                "response": "default",
            }
        ]
    },
    "PorterTimerCancel": {
        "data": [
            {
                "sentences": [
                    "cancel [my] timer",
                    "stop [my] timer",
                ],
                "metadata": {"slot_combination": "default"},
                "response": "default",
            },
            {
                "sentences": [
                    "cancel [my] timer [called] {timer_command:message}",
                    "stop [my] timer [called] {timer_command:message}",
                ],
                "metadata": {"slot_combination": "named"},
                "response": "default",
            },
        ]
    },
    "PorterReminderCreate": {
        "data": [
            {
                "sentences": [
                    "remind me [to] {timer_command:message} in "
                    "{1..100:amount} second[s]",
                    "remind me in {1..100:amount} second[s] [to] "
                    "{timer_command:message}",
                ],
                "slots": {
                    "schedule_kind": "relative",
                    "unit": "seconds",
                },
                "metadata": {"slot_combination": "relative_seconds"},
                "response": "default",
            },
            {
                "sentences": [
                    "remind me [to] {timer_command:message} in "
                    "{1..100:amount} minute[s]",
                    "remind me in {1..100:amount} minute[s] [to] "
                    "{timer_command:message}",
                ],
                "slots": {
                    "schedule_kind": "relative",
                    "unit": "minutes",
                },
                "metadata": {"slot_combination": "relative_minutes"},
                "response": "default",
            },
            {
                "sentences": [
                    "remind me [to] {timer_command:message} in "
                    "{1..100:amount} hour[s]",
                    "remind me in {1..100:amount} hour[s] [to] "
                    "{timer_command:message}",
                ],
                "slots": {
                    "schedule_kind": "relative",
                    "unit": "hours",
                },
                "metadata": {"slot_combination": "relative_hours"},
                "response": "default",
            },
            {
                "sentences": [
                    "remind me [to] {timer_command:message} at "
                    "{1..12:hour} {porter_meridiem:meridiem}",
                    "remind me at {1..12:hour} {porter_meridiem:meridiem} "
                    "[to] {timer_command:message}",
                    "remind me [to] {timer_command:message} at "
                    "{1..12:hour}:{0..59:minute} {porter_meridiem:meridiem}",
                    "remind me at {1..12:hour}:{0..59:minute} "
                    "{porter_meridiem:meridiem} [to] {timer_command:message}",
                ],
                "slots": {"schedule_kind": "clock"},
                "metadata": {"slot_combination": "clock"},
                "response": "default",
            },
            {
                "sentences": [
                    "remind me [to] {timer_command:message} "
                    "{porter_reminder_day:day} at {1..12:hour} "
                    "{porter_meridiem:meridiem}",
                    "remind me {porter_reminder_day:day} at {1..12:hour} "
                    "{porter_meridiem:meridiem} [to] {timer_command:message}",
                    "remind me [to] {timer_command:message} at {1..12:hour} "
                    "{porter_meridiem:meridiem} {porter_reminder_day:day}",
                    "remind me [to] {timer_command:message} "
                    "{porter_reminder_day:day} at "
                    "{1..12:hour}:{0..59:minute} "
                    "{porter_meridiem:meridiem}",
                    "remind me {porter_reminder_day:day} at "
                    "{1..12:hour}:{0..59:minute} "
                    "{porter_meridiem:meridiem} [to] {timer_command:message}",
                    "remind me [to] {timer_command:message} at "
                    "{1..12:hour}:{0..59:minute} "
                    "{porter_meridiem:meridiem} {porter_reminder_day:day}",
                ],
                "slots": {"schedule_kind": "clock"},
                "metadata": {"slot_combination": "clock_day"},
                "response": "default",
            },
        ]
    },
    "PorterReminderList": {
        "data": [
            {
                "sentences": [
                    "what reminders do i have",
                    "what are my reminders",
                    "show me my reminders",
                    "show my reminders",
                ],
                "metadata": {"slot_combination": "default"},
                "response": "default",
            }
        ]
    },
    "PorterReminderCancel": {
        "data": [
            {
                "sentences": [
                    "cancel [my] reminder [to] {timer_command:message}",
                    "delete [my] reminder [to] {timer_command:message}",
                    "remove [my] reminder [to] {timer_command:message}",
                ],
                "metadata": {"slot_combination": "message"},
                "response": "default",
            }
        ]
    },
}


def apply_supplemental_intents(
    intent_data: dict[str, Any],
) -> dict[str, Any]:
    merged = deepcopy(intent_data)
    lists = merged.setdefault("lists", {})
    for list_name, supplemental in PORTER_SUPPLEMENTAL_LISTS.items():
        lists[list_name] = deepcopy(supplemental)

    intents = merged.setdefault("intents", {})
    for intent_name, supplemental in PORTER_SUPPLEMENTAL_INTENTS.items():
        existing = intents.setdefault(
            intent_name,
            {"data": []},
        )
        existing.setdefault("data", []).extend(
            deepcopy(supplemental["data"])
        )

    return merged
