from __future__ import annotations

from datetime import UTC, datetime, timedelta

from PySide6.QtWidgets import QApplication

from porter.reminders import Reminder, ReminderStatus
from porter.tray.qt_app import PorterTrayController

NOW = datetime(2026, 8, 15, 20, tzinfo=UTC)


class MutableReminderService:
    def __init__(self) -> None:
        self.reminders: list[Reminder] = []

    def list_reminders(self, principal_id: str, *, status=None):
        return tuple(
            reminder
            for reminder in self.reminders
            if reminder.principal_id == principal_id
            and (status is None or reminder.status is status)
        )


def _scheduled(reminder_id: str) -> Reminder:
    return Reminder(
        id=reminder_id,
        principal_id="local-user",
        message="Refresh test",
        trigger_at=NOW + timedelta(hours=1),
        status=ReminderStatus.SCHEDULED,
        created_at=NOW,
        updated_at=NOW,
    )


def test_unchanged_poll_does_not_rebuild_panel(monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    service = MutableReminderService()
    controller = PorterTrayController(
        application,
        service,  # type: ignore[arg-type]
    )
    calls = 0
    original = controller.panel.update_snapshot

    def recording_update(snapshot) -> None:
        nonlocal calls
        calls += 1
        original(snapshot)

    monkeypatch.setattr(controller.panel, "update_snapshot", recording_update)

    controller.refresh()
    controller.refresh()
    assert calls == 0

    service.reminders.append(_scheduled("reminder-1"))
    controller.refresh()
    assert calls == 1

    controller.refresh()
    assert calls == 1
