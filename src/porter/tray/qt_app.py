from __future__ import annotations

import signal
import sys
from collections import deque

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QCursor,
    QFont,
    QIcon,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from porter.config.loader import ConfigLoader
from porter.notifications import TrayNotificationRequest, tray_socket_path
from porter.reminders import (
    Reminder,
    ReminderError,
    ReminderKind,
    ReminderService,
    ReminderStatus,
    SqliteReminderRepository,
)
from porter.storage.database import Database
from porter.storage.migrations import MigrationRunner
from porter.telemetry.structured_logging import emit_event
from porter.tray.edit_dialog import EditReminderDialog
from porter.tray.model import (
    TrayReminderSnapshot,
    build_tray_snapshot,
    format_timer_countdown,
    format_tray_reminder,
)
from porter.tray.notification_server import TrayNotificationServer

_REFRESH_INTERVAL_MS = 2_000
_PANEL_MIN_WIDTH = 440
_PANEL_MAX_HEIGHT = 600
_NOTIFICATION_WIDTH = 420
_NOTIFICATION_TIMEOUT_MS = 30_000

_UI_BACKGROUND = "#182638"
_UI_SURFACE = "#23374f"
_UI_BORDER = "#3c536c"
_UI_TEXT = "#eff5fc"
_UI_MUTED = "#adc0d4"
_UI_ACCENT = "#45cfbe"
_UI_ACCENT_HOVER = "#6adfd0"



class PorterTrayPanel(QWidget):
    """Applet-style popup panel anchored to Porter's system-tray icon."""

    def __init__(
        self,
        *,
        on_refresh,
        on_quit,
        on_edit,
        on_snooze,
        on_cancel,
        on_restart,
        on_clear,
        on_clear_history,
    ) -> None:
        super().__init__(
            None,
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint,
        )
        self._on_edit = on_edit
        self._on_snooze = on_snooze
        self._on_cancel = on_cancel
        self._on_restart = on_restart
        self._on_clear = on_clear
        self._timer_labels: list[tuple[Reminder, QLabel]] = []
        self._on_clear_history = on_clear_history

        self.setObjectName("porterPanel")
        self.setMinimumWidth(_PANEL_MIN_WIDTH)
        self.setMaximumHeight(_PANEL_MAX_HEIGHT)

        self.setStyleSheet(
            f"""
            QWidget#porterPanel {{
                background: {_UI_BACKGROUND};
                color: {_UI_TEXT};
                border: 1px solid {_UI_BORDER};
                border-radius: 12px;
            }}
            QWidget#porterPanel QLabel {{
                color: {_UI_TEXT};
                background: transparent;
            }}
            QFrame#reminderCard {{
                background: {_UI_SURFACE};
                border: 1px solid {_UI_BORDER};
                border-radius: 8px;
            }}
            QLabel#sectionHeading {{
                font-weight: 600;
            }}
            QWidget#porterPanel QLabel#emptyState,
            QWidget#porterPanel QLabel#secondaryText {{
                color: {_UI_MUTED};
            }}
            QWidget#porterPanel QLabel#countBadge {{
                background: {_UI_ACCENT};
                color: {_UI_BACKGROUND};
                border-radius: 9px;
                padding: 1px 6px;
                font-weight: 700;
            }}
            QPushButton {{
                color: {_UI_TEXT};
                background: {_UI_SURFACE};
                border: 1px solid {_UI_BORDER};
                border-radius: 7px;
                min-height: 22px;
                padding: 5px 10px;
            }}
            QPushButton:hover {{
                background: {_UI_BORDER};
            }}
            QPushButton:pressed {{
                background: {_UI_BACKGROUND};
            }}
            QScrollArea, QScrollArea > QWidget > QWidget {{
                border: none;
                background: transparent;
            }}
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("Porter")
        title_font = title.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 2)
        title.setFont(title_font)
        header.addWidget(title)

        self._count_badge = QLabel("0")
        self._count_badge.setObjectName("countBadge")
        self._count_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self._count_badge)
        header.addStretch(1)

        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(on_refresh)
        header.addWidget(refresh_button)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.hide)
        header.addWidget(close_button)
        root.addLayout(header)

        subtitle = QLabel("Timers, reminders and recent notifications")
        subtitle.setObjectName("secondaryText")
        root.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(8)
        scroll.setWidget(self._content)
        root.addWidget(scroll, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        quit_button = QPushButton("Quit Porter Tray")
        quit_button.clicked.connect(on_quit)
        footer.addWidget(quit_button)
        root.addLayout(footer)

    def update_snapshot(self, snapshot: TrayReminderSnapshot) -> None:
        self._clear_content()
        count = len(snapshot.scheduled)
        self._count_badge.setText(str(count))
        self._count_badge.setVisible(count > 0)

        timers = tuple(
            item for item in snapshot.scheduled if item.kind is ReminderKind.TIMER
        )
        reminders = tuple(
            item for item in snapshot.scheduled if item.kind is ReminderKind.REMINDER
        )

        self._add_heading("Active timers")
        if timers:
            for timer in timers:
                self._add_timer_card(timer)
        else:
            self._add_empty("No active timers")

        self._add_heading("Scheduled")
        if reminders:
            for reminder in reminders:
                self._add_scheduled_card(reminder)
        else:
            self._add_empty("No scheduled reminders")

        self._add_history_heading()
        if snapshot.recent_delivered:
            for reminder in snapshot.recent_delivered:
                self._add_delivered_card(reminder)
        else:
            self._add_empty("No recent notifications")

        self._content_layout.addStretch(1)
        self.update_countdowns()

    def update_countdowns(self) -> None:
        for timer, label in self._timer_labels:
            remaining = format_timer_countdown(timer)
            if label.text() != remaining:
                label.setText(remaining)

    def visible_text(self) -> tuple[str, ...]:
        labels = [
            label.text()
            for label in self.findChildren(QLabel)
            if label.text()
        ]
        buttons = [
            button.text()
            for button in self.findChildren(QPushButton)
            if button.text()
        ]
        return tuple(labels + buttons)

    def _clear_content(self) -> None:
        self._timer_labels.clear()
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _add_heading(self, text: str) -> None:
        label = QLabel(text)
        label.setObjectName("sectionHeading")
        self._content_layout.addWidget(label)

    def _add_history_heading(self) -> None:
        row_widget = QWidget()
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(0, 0, 0, 0)
        heading = QLabel("Recent notifications")
        heading.setObjectName("sectionHeading")
        row.addWidget(heading)
        row.addStretch(1)
        clear_history = QPushButton("Clear history")
        clear_history.clicked.connect(self._confirm_clear_history)
        row.addWidget(clear_history)
        self._content_layout.addWidget(row_widget)

    def _add_empty(self, text: str) -> None:
        label = QLabel(text)
        label.setObjectName("emptyState")
        self._content_layout.addWidget(label)

    def _add_scheduled_card(self, reminder: Reminder) -> None:
        self._add_reminder_card(
            reminder,
            actions=(
                ("Edit", self._on_edit),
                ("Snooze 10 min", self._on_snooze),
                ("Cancel", self._on_cancel),
            ),
        )

    def _add_timer_card(self, timer: Reminder) -> None:
        self._add_reminder_card(
            timer,
            actions=(
                ("Restart", self._on_restart),
                ("Cancel", self._on_cancel),
            ),
        )

    def _add_delivered_card(self, reminder: Reminder) -> None:
        actions = (
            ("Restart", self._on_restart),
            ("Clear", self._on_clear),
        ) if reminder.kind is ReminderKind.TIMER else (
            ("Remind in 10 min", self._on_snooze),
            ("Clear", self._on_clear),
        )
        self._add_reminder_card(reminder, actions=actions)

    def _add_reminder_card(self, reminder: Reminder, *, actions) -> None:
        card = QFrame()
        card.setObjectName("reminderCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)

        label = QLabel(format_tray_reminder(reminder))
        label.setWordWrap(True)
        layout.addWidget(label)

        if reminder.kind is ReminderKind.TIMER and (
            reminder.status is ReminderStatus.SCHEDULED
        ):
            countdown = QLabel()
            countdown.setObjectName("timerCountdown")
            countdown.setStyleSheet(f"color: {_UI_ACCENT}; font-weight: 700;")
            layout.addWidget(countdown)
            self._timer_labels.append((reminder, countdown))

        action_row = QHBoxLayout()
        action_row.addStretch(1)
        for text, callback in actions:
            button = QPushButton(text)
            button.clicked.connect(
                lambda _checked=False, reminder_id=reminder.id, action=callback: action(
                    reminder_id
                )
            )
            action_row.addWidget(button)
        layout.addLayout(action_row)
        self._content_layout.addWidget(card)

    def _confirm_clear_history(self) -> None:
        answer = QMessageBox.question(
            self,
            "Clear reminder history",
            "Clear all delivered and cancelled reminders? Scheduled reminders are kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._on_clear_history()


class PorterReminderPopup(QWidget):
    """Porter-owned reminder popup anchored to the tray icon."""

    def __init__(
        self,
        *,
        on_snooze,
        on_open,
        on_dismiss,
    ) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._request: TrayNotificationRequest | None = None
        self._on_snooze = on_snooze
        self._on_open = on_open
        self._on_dismiss = on_dismiss
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setObjectName("porterReminderPopup")
        self.setFixedWidth(_NOTIFICATION_WIDTH)

        self.setStyleSheet(
            f"""
            QWidget#porterReminderPopup {{
                background: {_UI_BACKGROUND};
                color: {_UI_TEXT};
                border: 1px solid {_UI_BORDER};
                border-radius: 12px;
            }}
            QLabel {{
                color: {_UI_TEXT};
                background: transparent;
            }}
            QLabel#notificationMonogram {{
                background: {_UI_ACCENT};
                color: {_UI_BACKGROUND};
                border-radius: 16px;
                font-size: 16px;
                font-weight: 700;
            }}
            QLabel#notificationTitle {{
                font-size: 14px;
                font-weight: 700;
            }}
            QLabel#notificationLabel {{
                font-size: 14px;
            }}
            QLabel#notificationMeta {{
                color: {_UI_MUTED};
                font-size: 11px;
            }}
            QFrame#notificationDivider {{
                background: {_UI_BORDER};
                border: none;
                min-height: 1px;
                max-height: 1px;
            }}
            QPushButton {{
                color: {_UI_TEXT};
                background: {_UI_SURFACE};
                border: 1px solid {_UI_BORDER};
                border-radius: 7px;
                min-height: 24px;
                padding: 6px 10px;
            }}
            QPushButton:hover {{
                background: {_UI_BORDER};
            }}
            QPushButton:pressed {{
                background: {_UI_BACKGROUND};
            }}
            QPushButton#notificationPrimary {{
                color: {_UI_BACKGROUND};
                background: {_UI_ACCENT};
                border: 1px solid {_UI_ACCENT};
                font-weight: 600;
            }}
            QPushButton#notificationPrimary:hover {{
                background: {_UI_ACCENT_HOVER};
            }}
            QPushButton#notificationDismiss {{
                background: transparent;
            }}
            QPushButton#notificationDismiss:hover {{
                background: {_UI_SURFACE};
            }}
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(10)

        monogram = QLabel("P")
        monogram.setObjectName("notificationMonogram")
        monogram.setAlignment(Qt.AlignmentFlag.AlignCenter)
        monogram.setFixedSize(32, 32)
        header.addWidget(monogram)

        heading = QVBoxLayout()
        heading.setSpacing(1)
        self._title = QLabel("Porter Reminder")
        self._title.setObjectName("notificationTitle")
        heading.addWidget(self._title)
        meta = QLabel("Delivered by Porter")
        meta.setObjectName("notificationMeta")
        heading.addWidget(meta)
        header.addLayout(heading)
        header.addStretch(1)
        root.addLayout(header)

        self._message = QLabel()
        self._message.setObjectName("notificationLabel")
        self._message.setTextFormat(Qt.TextFormat.PlainText)
        self._message.setWordWrap(True)
        self._message.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        root.addWidget(self._message)

        divider = QFrame()
        divider.setObjectName("notificationDivider")
        divider.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(divider)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self._snooze_button = QPushButton("Snooze 10 min")
        self._snooze_button.setObjectName("notificationPrimary")
        self._snooze_button.clicked.connect(self._snooze)
        actions.addWidget(self._snooze_button)
        actions.addStretch(1)
        open_button = QPushButton("Open Porter")
        open_button.clicked.connect(self._open)
        actions.addWidget(open_button)
        dismiss = QPushButton("Dismiss")
        dismiss.setObjectName("notificationDismiss")
        dismiss.clicked.connect(self.dismiss)
        actions.addWidget(dismiss)
        root.addLayout(actions)

        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.setInterval(_NOTIFICATION_TIMEOUT_MS)
        self._timeout.timeout.connect(self.dismiss)

    @property
    def request(self) -> TrayNotificationRequest | None:
        return self._request

    def set_request(self, request: TrayNotificationRequest) -> None:
        self._request = request
        self._message.setText(request.message)
        is_timer = request.kind is ReminderKind.TIMER
        self._title.setText("Porter Timer" if is_timer else "Porter Reminder")
        self._snooze_button.setText("Restart timer" if is_timer else "Snooze 10 min")
        self.adjustSize()

    def show_at(self, position: QPoint) -> None:
        self.move(position)
        self.show()
        self.raise_()
        self._timeout.start()

    def dismiss(self) -> None:
        if self._request is None:
            self.hide()
            return
        self._timeout.stop()
        self.hide()
        self._request = None
        self._on_dismiss()

    def _snooze(self) -> None:
        request = self._request
        if request is None:
            return
        self._on_snooze(request)
        self.dismiss()

    def _open(self) -> None:
        self._on_open()
        self.dismiss()


class PorterTrayController:
    def __init__(
        self,
        application: QApplication,
        reminder_service: ReminderService,
        *,
        principal_id: str = "local-user",
        edit_dialog_factory=EditReminderDialog,
    ) -> None:
        self._application = application
        self._reminder_service = reminder_service
        self._principal_id = principal_id
        self._edit_dialog_factory = edit_dialog_factory
        self._snapshot: TrayReminderSnapshot | None = None
        self._icon_count: tuple[int, int] | None = None
        self._pending_notifications: deque[TrayNotificationRequest] = deque()
        self._notification_show_queued = False
        self._last_tray_icon_rect: QRect | None = None

        self._menu = QMenu()
        show_action = QAction("Show Porter Reminders", self._menu)
        show_action.triggered.connect(self.show_panel)
        self._menu.addAction(show_action)
        refresh_action = QAction("Refresh", self._menu)
        refresh_action.triggered.connect(self.refresh)
        self._menu.addAction(refresh_action)
        self._menu.addSeparator()
        quit_action = QAction("Quit Porter Tray", self._menu)
        quit_action.triggered.connect(self._application.quit)
        self._menu.addAction(quit_action)

        self._tray_icon = QSystemTrayIcon(_porter_icon(application, 0))
        self._tray_icon.setContextMenu(self._menu)
        self._tray_icon.activated.connect(self._on_activated)

        self._notification_popup = PorterReminderPopup(
            on_snooze=self._snooze_notification,
            on_open=self.show_panel,
            on_dismiss=self._show_next_notification,
        )

        self._panel = PorterTrayPanel(
            on_refresh=self.refresh,
            on_quit=self._application.quit,
            on_edit=self._edit,
            on_snooze=self._snooze,
            on_cancel=self._cancel,
            on_restart=self._restart_timer,
            on_clear=self._clear,
            on_clear_history=self._clear_history,
        )

        self._timer = QTimer()
        self._timer.setInterval(_REFRESH_INTERVAL_MS)
        self._timer.timeout.connect(self.refresh)

        self._countdown_timer = QTimer()
        self._countdown_timer.setInterval(1_000)
        self._countdown_timer.timeout.connect(self._panel.update_countdowns)

        self.refresh()

    @property
    def tray_icon(self) -> QSystemTrayIcon:
        return self._tray_icon

    @property
    def menu(self) -> QMenu:
        return self._menu

    @property
    def panel(self) -> PorterTrayPanel:
        return self._panel

    @property
    def notification_popup(self) -> PorterReminderPopup:
        return self._notification_popup

    def start(self) -> None:
        self._tray_icon.show()
        self._timer.start()
        self._countdown_timer.start()

    def refresh(self) -> None:
        snapshot = build_tray_snapshot(
            self._reminder_service,
            principal_id=self._principal_id,
        )
        if snapshot != self._snapshot:
            self._snapshot = snapshot
            self._panel.update_snapshot(snapshot)

        timers = sum(
            item.kind is ReminderKind.TIMER for item in snapshot.scheduled
        )
        reminders = len(snapshot.scheduled) - timers
        state = (reminders, timers)
        if state != self._icon_count:
            self._icon_count = state
            noun = "reminder" if reminders == 1 else "reminders"
            tooltip = f"{reminders} scheduled {noun}"
            if timers:
                timer_noun = "timer" if timers == 1 else "timers"
                tooltip = (
                    f"{tooltip}, {timers} active {timer_noun}"
                    if reminders
                    else f"{timers} active {timer_noun}"
                )
            self._tray_icon.setToolTip(f"Porter — {tooltip}")
            self._tray_icon.setIcon(
                _porter_icon(self._application, len(snapshot.scheduled))
            )

    def show_notification(self, request: TrayNotificationRequest) -> None:
        self._pending_notifications.append(request)
        emit_event(
            "tray.notification.queued",
            pending=len(self._pending_notifications),
            popup_visible=self._notification_popup.isVisible(),
        )
        if not self._notification_popup.isVisible():
            self._schedule_next_notification()

    def _schedule_next_notification(self) -> None:
        if self._notification_show_queued or not self._pending_notifications:
            return
        self._notification_show_queued = True
        # Allow the socket callback to return before Qt maps the popup window.
        QTimer.singleShot(0, self._show_next_notification)

    def _show_next_notification(self) -> None:
        self._notification_show_queued = False
        if not self._pending_notifications:
            return
        request = self._pending_notifications.popleft()
        self._notification_popup.set_request(request)
        height = self._notification_popup.sizeHint().height()
        position = self._anchored_position(
            _NOTIFICATION_WIDTH,
            height,
            allow_cursor_fallback=False,
        )
        self._notification_popup.show_at(position)
        icon_rect = self._tray_icon.geometry()
        emit_event(
            "tray.notification.show_requested",
            platform=QApplication.platformName(),
            icon_geometry_known=icon_rect.isValid() and not icon_rect.isNull(),
            position_x=position.x(),
            position_y=position.y(),
            popup_visible=self._notification_popup.isVisible(),
        )

    def show_panel(self) -> None:
        self.refresh()
        self._panel.adjustSize()
        width = max(_PANEL_MIN_WIDTH, self._panel.sizeHint().width())
        height = min(_PANEL_MAX_HEIGHT, max(280, self._panel.sizeHint().height()))
        self._panel.resize(width, height)
        self._panel.move(self._anchored_position(width, height))
        self._panel.show()
        self._panel.raise_()
        self._panel.activateWindow()

    def toggle_panel(self) -> None:
        if self._panel.isVisible():
            self._panel.hide()
        else:
            self.show_panel()

    def _anchored_position(
        self,
        width: int,
        height: int,
        *,
        allow_cursor_fallback: bool = True,
    ) -> QPoint:
        icon_rect = self._tray_icon.geometry()
        if not icon_rect.isValid() or icon_rect.isNull():
            icon_rect = self._last_tray_icon_rect or QRect()

        if not icon_rect.isValid() or icon_rect.isNull():
            if allow_cursor_fallback:
                anchor = QCursor.pos()
                icon_rect = QRect(anchor.x(), anchor.y(), 1, 1)
            else:
                # On some Linux trays, icon geometry is unknown until the user
                # clicks it. A cursor fallback can put timed notifications at
                # an arbitrary screen edge instead of near the taskbar.
                screen = QApplication.primaryScreen()
                if screen is None:
                    return QPoint(0, 0)
                available = screen.availableGeometry()
                return QPoint(
                    available.right() - width - 8,
                    available.bottom() - height - 8,
                )

        anchor = icon_rect.center()
        screen = QApplication.screenAt(anchor) or QApplication.primaryScreen()
        if screen is None:
            return anchor

        available = screen.availableGeometry()
        x = anchor.x() - width // 2
        x = max(available.left() + 8, min(x, available.right() - width - 8))

        above = icon_rect.top() - height - 8
        below = icon_rect.bottom() + 8
        y = above if above >= available.top() else below
        y = max(available.top() + 8, min(y, available.bottom() - height - 8))
        return QPoint(x, y)

    def _edit(self, reminder_id: str) -> None:
        try:
            reminder = self._reminder_service.get_reminder(
                self._principal_id,
                reminder_id,
            )
        except ReminderError as exc:
            QMessageBox.warning(self._panel, "Porter reminder", str(exc))
            self.refresh()
            return

        self._panel.hide()
        dialog = self._edit_dialog_factory(self._panel, reminder)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._run_reminder_action(
                lambda: self._reminder_service.edit_reminder(
                    self._principal_id,
                    reminder_id,
                    message=dialog.message(),
                    trigger_at=dialog.trigger_at(),
                )
            )
        self.show_panel()

    def _snooze_notification(self, request: TrayNotificationRequest) -> None:
        if request.kind is ReminderKind.TIMER:
            self._run_reminder_action(
                lambda: self._reminder_service.restart_timer(
                    request.principal_id,
                    request.reminder_id,
                )
            )
        else:
            self._run_reminder_action(
                lambda: self._reminder_service.snooze_reminder(
                    request.principal_id,
                    request.reminder_id,
                )
            )

    def _snooze(self, reminder_id: str) -> None:
        self._run_reminder_action(
            lambda: self._reminder_service.snooze_reminder(
                self._principal_id,
                reminder_id,
            )
        )

    def _restart_timer(self, timer_id: str) -> None:
        self._run_reminder_action(
            lambda: self._reminder_service.restart_timer(
                self._principal_id,
                timer_id,
            )
        )

    def _cancel(self, reminder_id: str) -> None:
        self._run_reminder_action(
            lambda: self._reminder_service.cancel_reminder(
                self._principal_id,
                reminder_id,
            )
        )

    def _clear(self, reminder_id: str) -> None:
        self._run_reminder_action(
            lambda: self._reminder_service.delete_terminal_reminder(
                self._principal_id,
                reminder_id,
            )
        )

    def _clear_history(self) -> None:
        self._run_reminder_action(
            lambda: self._reminder_service.clear_reminder_history(
                self._principal_id
            )
        )

    def _run_reminder_action(self, action) -> None:
        try:
            action()
        except ReminderError as exc:
            QMessageBox.warning(self._panel, "Porter reminder", str(exc))
        self.refresh()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        icon_rect = self._tray_icon.geometry()
        if icon_rect.isValid() and not icon_rect.isNull():
            self._last_tray_icon_rect = QRect(icon_rect)
        else:
            # Activation is the only trustworthy cursor sample for a tray
            # that cannot report icon geometry through QSystemTrayIcon.
            cursor = QCursor.pos()
            self._last_tray_icon_rect = QRect(cursor.x(), cursor.y(), 1, 1)
        if reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            self.toggle_panel()


def run_tray() -> int:
    application = QApplication(sys.argv)
    application.setApplicationName("Porter")
    application.setApplicationDisplayName("Porter")
    application.setQuitOnLastWindowClosed(False)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("porter-tray: no system tray is available", file=sys.stderr)
        return 1

    storage = ConfigLoader().load_storage()
    database = Database(storage.database_path)
    migration_runner = MigrationRunner(database)
    migration_runner.apply_all()
    reminder_service = ReminderService(SqliteReminderRepository(database))

    controller = PorterTrayController(application, reminder_service)
    controller.start()

    socket_path = tray_socket_path()
    notification_server = None
    if socket_path is not None:
        notification_server = TrayNotificationServer(
            socket_path,
            controller.show_notification,
        )
        try:
            notification_server.start()
        except RuntimeError as exc:
            print(f"porter-tray: {exc}", file=sys.stderr)
            return 1
        application.aboutToQuit.connect(notification_server.close)

    signal.signal(signal.SIGINT, lambda *_: application.quit())
    signal.signal(signal.SIGTERM, lambda *_: application.quit())

    return application.exec()


def _porter_icon(application: QApplication, scheduled_count: int) -> QIcon:
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    palette = application.palette()
    foreground = palette.color(QPalette.ColorRole.WindowText)
    badge = palette.color(QPalette.ColorRole.Highlight)
    badge_text = palette.color(QPalette.ColorRole.HighlightedText)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    pen = QPen(foreground)
    pen.setWidth(5)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(6, 6, size - 12, size - 12)

    font = QFont(application.font())
    font.setBold(True)
    font.setPixelSize(34)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "P")

    if scheduled_count > 0:
        badge_rect = QRect(39, 1, 24, 24)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(badge)
        painter.drawEllipse(badge_rect)
        painter.setPen(badge_text)
        badge_font = QFont(application.font())
        badge_font.setBold(True)
        badge_font.setPixelSize(14)
        painter.setFont(badge_font)
        badge_label = "99+" if scheduled_count > 99 else str(scheduled_count)
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_label)

    painter.end()
    return QIcon(pixmap)
