from __future__ import annotations

from typing import Protocol

from porter.reminders.models import Reminder


class ReminderDelivery(Protocol):
    """Delivery boundary for one-shot reminder notifications."""

    async def deliver(self, reminder: Reminder) -> None:
        ...
