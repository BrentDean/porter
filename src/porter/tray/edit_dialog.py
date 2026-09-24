from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from PySide6.QtCore import QDate, QDateTime, QTime
from PySide6.QtWidgets import (
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTimeEdit,
    QWidget,
)

from porter.core.clock import local_now, system_timezone
from porter.reminders import Reminder


class EditReminderDialog(QDialog):
    """Edit one scheduled reminder using the desktop's local timezone."""

    def __init__(
        self,
        parent: QWidget,
        reminder: Reminder,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(parent)
        self._clock = clock or local_now
        self.setWindowTitle("Edit reminder")
        self.setModal(True)
        self.setMinimumWidth(430)

        layout = QFormLayout(self)

        self._message = QLineEdit(reminder.message)
        self._message.setObjectName("reminderMessage")
        self._message.selectAll()
        layout.addRow("Reminder", self._message)

        self._date = QDateEdit()
        self._date.setObjectName("reminderDate")
        self._date.setCalendarPopup(True)
        self._date.setDisplayFormat("ddd MMM d, yyyy")
        self._date.setMinimumWidth(190)
        layout.addRow("Date", self._date)

        self._time = QTimeEdit()
        self._time.setObjectName("reminderTime")
        self._time.setDisplayFormat("h:mm AP")
        self._time.setMinimumWidth(120)
        layout.addRow("Time", self._time)

        quick_row = QWidget()
        quick_layout = QHBoxLayout(quick_row)
        quick_layout.setContentsMargins(0, 0, 0, 0)
        quick_layout.setSpacing(6)
        for label, delta, object_name in (
            ("+10 min", timedelta(minutes=10), "quick10Minutes"),
            ("+30 min", timedelta(minutes=30), "quick30Minutes"),
            ("+1 hour", timedelta(hours=1), "quick1Hour"),
        ):
            button = QPushButton(label)
            button.setObjectName(object_name)
            button.clicked.connect(
                lambda _checked=False, offset=delta: self._set_relative(offset)
            )
            quick_layout.addWidget(button)
        quick_layout.addStretch(1)
        layout.addRow("Quick set", quick_row)

        local_trigger = reminder.trigger_at.astimezone(system_timezone()).replace(
            second=0,
            microsecond=0,
        )
        self._set_fields(local_trigger)
        now = self._now_local()
        self._date.setMinimumDate(QDate(now.year, now.month, now.day))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def message(self) -> str:
        return self._message.text()

    def trigger_at(self) -> datetime:
        selected = QDateTime(self._date.date(), self._time.time())
        if not selected.isValid():
            raise ValueError("selected local reminder time is invalid")
        timestamp = selected.toSecsSinceEpoch()
        return datetime.fromtimestamp(timestamp, tz=system_timezone()).replace(
            second=0,
            microsecond=0,
        )

    def accept(self) -> None:
        if not self.message().strip():
            QMessageBox.warning(
                self,
                "Invalid reminder",
                "Reminder text cannot be empty.",
            )
            return

        try:
            trigger = self.trigger_at()
        except ValueError:
            QMessageBox.warning(
                self,
                "Invalid reminder time",
                "Choose a valid local date and time.",
            )
            return

        if trigger <= self._now_local():
            QMessageBox.warning(
                self,
                "Invalid reminder time",
                "Choose a reminder time in the future.",
            )
            return

        super().accept()

    def _set_relative(self, delta: timedelta) -> None:
        now = self._now_local()
        target = (now.astimezone(UTC) + delta).astimezone(system_timezone())
        self._set_fields(target.replace(second=0, microsecond=0))

    def _set_fields(self, value: datetime) -> None:
        self._date.setDate(QDate(value.year, value.month, value.day))
        self._time.setTime(QTime(value.hour, value.minute))

    def _now_local(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("edit reminder dialog clock must be timezone-aware")
        return value.astimezone(system_timezone()).replace(second=0, microsecond=0)
