from __future__ import annotations

from datetime import UTC, timedelta

from PySide6.QtCore import QTime
from PySide6.QtWidgets import (
    QApplication,
    QDateEdit,
    QLineEdit,
    QPushButton,
    QTimeEdit,
    QWidget,
)

from porter.core.clock import local_now, system_timezone
from porter.reminders import Reminder, ReminderStatus
from porter.tray.edit_dialog import EditReminderDialog


def _reminder(trigger_at, *, now):
    return Reminder(
        id="reminder-1",
        principal_id="local-user",
        message="Original reminder",
        trigger_at=trigger_at,
        status=ReminderStatus.SCHEDULED,
        created_at=now,
        updated_at=now,
    )


def test_edit_dialog_separates_date_and_time_controls() -> None:
    _application = QApplication.instance() or QApplication([])
    now = local_now().replace(second=0, microsecond=0)
    trigger = now + timedelta(days=1, hours=2, minutes=17)
    parent = QWidget()

    dialog = EditReminderDialog(parent, _reminder(trigger, now=now))

    message = dialog.findChild(QLineEdit, "reminderMessage")
    date_editor = dialog.findChild(QDateEdit, "reminderDate")
    time_editor = dialog.findChild(QTimeEdit, "reminderTime")
    assert message is not None
    assert date_editor is not None
    assert time_editor is not None
    assert message.text() == "Original reminder"
    assert date_editor.calendarPopup()
    assert not time_editor.isReadOnly()
    assert date_editor.displayFormat() == "ddd MMM d, yyyy"
    assert time_editor.displayFormat() == "h:mm AP"
    assert dialog.trigger_at() == trigger.astimezone(system_timezone())


def test_edit_dialog_time_can_be_changed_independently() -> None:
    _application = QApplication.instance() or QApplication([])
    now = local_now().replace(second=0, microsecond=0)
    trigger = now + timedelta(days=1)
    parent = QWidget()
    dialog = EditReminderDialog(parent, _reminder(trigger, now=now))
    time_editor = dialog.findChild(QTimeEdit, "reminderTime")
    assert time_editor is not None

    time_editor.setTime(QTime(7, 45))

    edited = dialog.trigger_at()
    assert edited.hour == 7
    assert edited.minute == 45
    assert edited.date() == trigger.astimezone(system_timezone()).date()


def test_edit_dialog_quick_set_uses_relative_future_time() -> None:
    _application = QApplication.instance() or QApplication([])
    now = local_now().replace(second=0, microsecond=0)
    trigger = now + timedelta(days=1)
    parent = QWidget()
    dialog = EditReminderDialog(
        parent,
        _reminder(trigger, now=now),
        clock=lambda: now,
    )
    button = dialog.findChild(QPushButton, "quick30Minutes")
    assert button is not None

    button.click()

    expected = (now.astimezone(UTC) + timedelta(minutes=30)).astimezone(
        system_timezone()
    )
    assert dialog.trigger_at() == expected


def test_edit_dialog_returns_edited_message() -> None:
    _application = QApplication.instance() or QApplication([])
    now = local_now().replace(second=0, microsecond=0)
    reminder = _reminder(now + timedelta(days=1), now=now)
    parent = QWidget()
    dialog = EditReminderDialog(parent, reminder)
    message = dialog.findChild(QLineEdit, "reminderMessage")
    assert message is not None

    message.setText("Changed reminder")

    assert dialog.message() == "Changed reminder"
