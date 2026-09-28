from __future__ import annotations

from datetime import datetime
from typing import Protocol

from porter.reminders.models import Reminder, ReminderStatus


class ReminderRepository(Protocol):
    """Persistence boundary for Porter reminders."""

    def create_reminder(self, reminder: Reminder) -> Reminder:
        ...

    def get_reminder(self, principal_id: str, reminder_id: str) -> Reminder:
        ...

    def list_reminders(
        self,
        principal_id: str,
        *,
        status: ReminderStatus | None = None,
    ) -> tuple[Reminder, ...]:
        ...

    def list_due_reminders(
        self,
        principal_id: str,
        *,
        as_of: datetime,
    ) -> tuple[Reminder, ...]:
        ...

    def list_all_due_reminders(
        self,
        *,
        as_of: datetime,
    ) -> tuple[Reminder, ...]:
        """Return system-wide reminders currently eligible for delivery."""
        ...

    def claim_due_reminder(
        self,
        principal_id: str,
        reminder_id: str,
        *,
        claimed_at: datetime,
    ) -> Reminder | None:
        """Atomically claim one still-due scheduled reminder for delivery."""
        ...

    def recover_stale_delivery_claims(
        self,
        *,
        stale_before: datetime,
        retry_at: datetime,
    ) -> int:
        """Return stale delivery claims to scheduled state."""
        ...

    def update_reminder(
        self,
        principal_id: str,
        reminder: Reminder,
        *,
        expected_status: ReminderStatus | None = None,
        expected_claimed_at: datetime | None = None,
    ) -> Reminder:
        """Update a reminder while optionally requiring persisted claim state."""
        ...

    def delete_reminder(
        self,
        principal_id: str,
        reminder_id: str,
        *,
        expected_status: ReminderStatus | None = None,
    ) -> None:
        ...

    def delete_terminal_reminders(self, principal_id: str) -> int:
        """Delete delivered/cancelled reminders for one principal."""
        ...
