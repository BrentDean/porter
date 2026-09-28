from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton

from porter.notifications import TrayNotificationRequest
from porter.reminders import Reminder, ReminderKind, ReminderStatus
from porter.tray.qt_app import PorterTrayController

NOW = datetime(2026, 8, 15, 20, tzinfo=UTC)


class FakeReminderService:
    def __init__(self, reminders: tuple[Reminder, ...]) -> None:
        self.reminders = list(reminders)

    def get_reminder(self, principal_id: str, reminder_id: str) -> Reminder:
        return self._get(principal_id, reminder_id)

    def list_reminders(self, principal_id: str, *, status=None):
        return tuple(
            reminder
            for reminder in self.reminders
            if reminder.principal_id == principal_id
            and (status is None or reminder.status is status)
        )

    def edit_reminder(
        self,
        principal_id: str,
        reminder_id: str,
        *,
        message: str,
        trigger_at: datetime,
    ) -> Reminder:
        reminder = self._get(principal_id, reminder_id)
        updated = replace(
            reminder,
            message=message,
            trigger_at=trigger_at,
            updated_at=NOW,
        )
        self._replace(updated)
        return updated

    def snooze_reminder(self, principal_id: str, reminder_id: str):
        reminder = self._get(principal_id, reminder_id)
        trigger_base = max(NOW, reminder.trigger_at)
        updated = replace(
            reminder,
            trigger_at=trigger_base + timedelta(minutes=10),
            status=ReminderStatus.SCHEDULED,
            updated_at=NOW,
            delivered_at=None,
            cancelled_at=None,
        )
        self._replace(updated)
        return updated

    def restart_timer(self, principal_id: str, timer_id: str):
        timer = self._get(principal_id, timer_id)
        assert timer.duration_seconds is not None
        updated = replace(
            timer,
            trigger_at=NOW + timedelta(seconds=timer.duration_seconds),
            status=ReminderStatus.SCHEDULED,
            updated_at=NOW,
            delivered_at=None,
            cancelled_at=None,
        )
        self._replace(updated)
        return updated

    def cancel_reminder(self, principal_id: str, reminder_id: str):
        reminder = self._get(principal_id, reminder_id)
        updated = replace(
            reminder,
            status=ReminderStatus.CANCELLED,
            updated_at=NOW,
            cancelled_at=NOW,
        )
        self._replace(updated)
        return updated

    def delete_terminal_reminder(self, principal_id: str, reminder_id: str) -> None:
        reminder = self._get(principal_id, reminder_id)
        self.reminders.remove(reminder)

    def clear_reminder_history(self, principal_id: str) -> int:
        before = len(self.reminders)
        self.reminders = [
            reminder
            for reminder in self.reminders
            if reminder.principal_id != principal_id
            or reminder.status is ReminderStatus.SCHEDULED
        ]
        return before - len(self.reminders)

    def _get(self, principal_id: str, reminder_id: str) -> Reminder:
        return next(
            reminder
            for reminder in self.reminders
            if reminder.principal_id == principal_id and reminder.id == reminder_id
        )

    def _replace(self, updated: Reminder) -> None:
        self.reminders = [
            updated if reminder.id == updated.id else reminder
            for reminder in self.reminders
        ]


class FakeEditDialog:
    def __init__(self, _parent, _reminder: Reminder) -> None:
        pass

    def exec(self) -> QDialog.DialogCode:
        return QDialog.DialogCode.Accepted

    def message(self) -> str:
        return "Edited tray reminder"

    def trigger_at(self) -> datetime:
        return NOW + timedelta(minutes=45)


def _scheduled() -> Reminder:
    return Reminder(
        id="scheduled",
        principal_id="local-user",
        message="Test tray reminder",
        trigger_at=NOW + timedelta(minutes=5),
        status=ReminderStatus.SCHEDULED,
        created_at=NOW,
        updated_at=NOW,
    )


def _delivered() -> Reminder:
    return Reminder(
        id="delivered",
        principal_id="local-user",
        message="Recent tray notification",
        trigger_at=NOW - timedelta(minutes=2),
        status=ReminderStatus.DELIVERED,
        created_at=NOW - timedelta(minutes=3),
        updated_at=NOW - timedelta(minutes=1),
        delivered_at=NOW - timedelta(minutes=1),
    )


def _button(controller: PorterTrayController, text: str) -> QPushButton:
    return next(
        button
        for button in controller.panel.findChildren(QPushButton)
        if button.text() == text
    )


def test_tray_panel_lists_reminders_and_lifecycle_controls() -> None:
    application = QApplication.instance() or QApplication([])
    controller = PorterTrayController(
        application,
        FakeReminderService((_scheduled(), _delivered())),  # type: ignore[arg-type]
    )

    menu_labels = [action.text() for action in controller.menu.actions()]
    panel_text = controller.panel.visible_text()

    assert "Show Porter Reminders" in menu_labels
    assert "Refresh" in menu_labels
    assert "Quit Porter Tray" in menu_labels
    assert "Scheduled" in panel_text
    assert any("Test tray reminder" in label for label in panel_text)
    assert "Edit" in panel_text
    assert "Snooze 10 min" in panel_text
    assert "Cancel" in panel_text
    assert "Recent notifications" in panel_text
    assert any("Recent tray notification" in label for label in panel_text)
    assert "Remind in 10 min" in panel_text
    assert "Clear" in panel_text
    assert "Clear history" in panel_text
    assert controller.tray_icon.toolTip() == "Porter — 1 scheduled reminder"
    assert not controller.tray_icon.icon().isNull()


def test_tray_edit_updates_message_and_precise_trigger() -> None:
    application = QApplication.instance() or QApplication([])
    service = FakeReminderService((_scheduled(),))
    controller = PorterTrayController(
        application,
        service,  # type: ignore[arg-type]
        edit_dialog_factory=FakeEditDialog,
    )

    _button(controller, "Edit").click()
    application.processEvents()

    edited = service.reminders[0]
    assert edited.message == "Edited tray reminder"
    assert edited.trigger_at == NOW + timedelta(minutes=45)
    assert any(
        "Edited tray reminder" in text
        for text in controller.panel.visible_text()
    )


def test_tray_snooze_and_cancel_update_scheduled_state() -> None:
    application = QApplication.instance() or QApplication([])
    service = FakeReminderService((_scheduled(),))
    controller = PorterTrayController(
        application,
        service,  # type: ignore[arg-type]
    )

    _button(controller, "Snooze 10 min").click()
    application.processEvents()

    snoozed = service.reminders[0]
    assert snoozed.status is ReminderStatus.SCHEDULED
    assert snoozed.trigger_at == NOW + timedelta(minutes=15)

    _button(controller, "Cancel").click()
    application.processEvents()

    assert service.reminders[0].status is ReminderStatus.CANCELLED
    assert controller.tray_icon.toolTip() == "Porter — 0 scheduled reminders"


def test_tray_delivered_reminder_can_be_reminded_again_or_cleared() -> None:
    application = QApplication.instance() or QApplication([])
    service = FakeReminderService((_delivered(),))
    controller = PorterTrayController(
        application,
        service,  # type: ignore[arg-type]
    )

    _button(controller, "Remind in 10 min").click()
    application.processEvents()

    assert service.reminders[0].status is ReminderStatus.SCHEDULED
    assert service.reminders[0].delivered_at is None
    assert controller.tray_icon.toolTip() == "Porter — 1 scheduled reminder"

    service.reminders = [_delivered()]
    controller.refresh()
    _button(controller, "Clear").click()
    application.processEvents()

    assert service.reminders == []
    assert "No recent notifications" in controller.panel.visible_text()


def test_tray_panel_can_be_opened_and_closed() -> None:
    application = QApplication.instance() or QApplication([])
    controller = PorterTrayController(
        application,
        FakeReminderService((_scheduled(),)),  # type: ignore[arg-type]
    )

    controller.show_panel()
    application.processEvents()
    assert controller.panel.isVisible()

    controller.toggle_panel()
    application.processEvents()
    assert not controller.panel.isVisible()


def test_tray_notification_popup_is_anchored_surface_with_actions() -> None:
    application = QApplication.instance() or QApplication([])
    controller = PorterTrayController(
        application,
        FakeReminderService((_delivered(),)),  # type: ignore[arg-type]
    )
    request = TrayNotificationRequest(
        reminder_id="delivered",
        principal_id="local-user",
        message="Custom Porter popup",
    )

    controller.show_notification(request)
    application.processEvents()

    popup = controller.notification_popup
    labels = [label.text() for label in popup.findChildren(QLabel)]
    buttons = [button.text() for button in popup.findChildren(QPushButton)]
    assert popup.isVisible()
    assert "Porter Reminder" in labels
    assert "Custom Porter popup" in labels
    assert "Snooze 10 min" in buttons
    assert "Open Porter" in buttons
    assert "Dismiss" in buttons

    popup.dismiss()
    application.processEvents()
    assert not popup.isVisible()


def test_tray_popup_and_panel_have_matching_dark_style() -> None:
    application = QApplication.instance() or QApplication([])
    controller = PorterTrayController(
        application,
        FakeReminderService((_delivered(),)),  # type: ignore[arg-type]
    )
    request = TrayNotificationRequest(
        reminder_id="delivered",
        principal_id="local-user",
        message="<b>Literal reminder text</b>",
    )

    controller.show_notification(request)
    application.processEvents()

    popup = controller.notification_popup
    assert popup.width() == 420
    assert "#182638" in popup.styleSheet()
    assert "#182638" in controller.panel.styleSheet()
    assert "#45cfbe" in popup.styleSheet()
    assert "#45cfbe" in controller.panel.styleSheet()

    message_label = popup.findChild(QLabel, "notificationLabel")
    assert message_label is not None
    assert message_label.textFormat() is Qt.TextFormat.PlainText
    assert message_label.text() == request.message
    assert message_label.wordWrap()

    buttons = {
        button.text(): button
        for button in popup.findChildren(QPushButton)
    }
    assert buttons["Snooze 10 min"].objectName() == "notificationPrimary"
    assert buttons["Dismiss"].objectName() == "notificationDismiss"
    popup.dismiss()


def test_notification_uses_screen_edge_when_tray_geometry_is_unavailable() -> None:
    application = QApplication.instance() or QApplication([])
    controller = PorterTrayController(
        application,
        FakeReminderService((_delivered(),)),  # type: ignore[arg-type]
    )
    controller._tray_icon = SimpleNamespace(geometry=QRect)  # type: ignore[assignment]
    screen = QApplication.primaryScreen()
    assert screen is not None

    width, height = 420, 180
    position = controller._anchored_position(
        width,
        height,
        allow_cursor_fallback=False,
    )
    available = screen.availableGeometry()
    assert position == QPoint(
        available.right() - width - 8,
        available.bottom() - height - 8,
    )


def test_notification_prefers_last_real_tray_anchor_when_geometry_unavailable() -> None:
    application = QApplication.instance() or QApplication([])
    controller = PorterTrayController(
        application,
        FakeReminderService((_delivered(),)),  # type: ignore[arg-type]
    )
    screen = QApplication.primaryScreen()
    assert screen is not None
    available = screen.availableGeometry()
    anchor = QPoint(available.center().x(), available.bottom() - 4)

    controller._tray_icon = SimpleNamespace(geometry=QRect)  # type: ignore[assignment]
    controller._last_tray_icon_rect = QRect(anchor.x(), anchor.y(), 1, 1)

    result = controller._anchored_position(
        420,
        180,
        allow_cursor_fallback=False,
    )
    assert result.x() == anchor.x() - 210
    assert result.y() == anchor.y() - 188


def test_notification_is_queued_until_qt_processes_next_event() -> None:
    application = QApplication.instance() or QApplication([])
    controller = PorterTrayController(
        application,
        FakeReminderService((_delivered(),)),  # type: ignore[arg-type]
    )
    request = TrayNotificationRequest(
        reminder_id="delivered",
        principal_id="local-user",
        message="Show after socket callback",
    )

    controller.show_notification(request)

    assert controller.notification_popup.request is None
    application.processEvents()
    assert controller.notification_popup.request == request
    controller.notification_popup.dismiss()


def _timer(*, delivered: bool = False) -> Reminder:
    return Reminder(
        id="timer",
        principal_id="local-user",
        message="Kitchen timer",
        trigger_at=NOW - timedelta(seconds=5) if delivered else NOW + timedelta(seconds=30),
        status=ReminderStatus.DELIVERED if delivered else ReminderStatus.SCHEDULED,
        created_at=NOW - timedelta(seconds=10),
        updated_at=NOW,
        delivered_at=NOW if delivered else None,
        kind=ReminderKind.TIMER,
        duration_seconds=30,
    )


def test_tray_timer_is_shown_with_countdown_and_restart_cancel_controls() -> None:
    application = QApplication.instance() or QApplication([])
    service = FakeReminderService((_timer(),))
    controller = PorterTrayController(
        application,
        service,  # type: ignore[arg-type]
    )

    panel_text = controller.panel.visible_text()
    assert "Active timers" in panel_text
    assert any("Kitchen timer" in label for label in panel_text)
    assert "Restart" in panel_text
    assert "Cancel" in panel_text
    assert controller.tray_icon.toolTip() == "Porter — 1 active timer"
    countdown = controller.panel.findChild(QLabel, "timerCountdown")
    assert countdown is not None
    assert countdown.text() != ""

    _button(controller, "Cancel").click()
    application.processEvents()
    assert service.reminders[0].status is ReminderStatus.CANCELLED
    assert "No active timers" in controller.panel.visible_text()


def test_tray_delivered_timer_can_be_restarted() -> None:
    application = QApplication.instance() or QApplication([])
    service = FakeReminderService((_timer(delivered=True),))
    controller = PorterTrayController(
        application,
        service,  # type: ignore[arg-type]
    )
    assert "Restart" in controller.panel.visible_text()
    _button(controller, "Restart").click()
    application.processEvents()
    assert service.reminders[0].status is ReminderStatus.SCHEDULED
    assert service.reminders[0].trigger_at == NOW + timedelta(seconds=30)


def test_popup_uses_timer_title() -> None:
    application = QApplication.instance() or QApplication([])
    controller = PorterTrayController(
        application,
        FakeReminderService((_timer(delivered=True),)),  # type: ignore[arg-type]
    )
    controller.show_notification(
        TrayNotificationRequest(
            reminder_id="timer",
            principal_id="local-user",
            message="Kitchen timer",
            kind=ReminderKind.TIMER,
        )
    )
    application.processEvents()
    titles = [label.text() for label in controller.notification_popup.findChildren(QLabel)]
    assert "Porter Timer" in titles
    assert "Restart timer" in [
        button.text()
        for button in controller.notification_popup.findChildren(QPushButton)
    ]
    controller.notification_popup.dismiss()
