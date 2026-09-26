from __future__ import annotations


class ReminderError(Exception):
    """Base error for Porter reminder operations."""


class ReminderValidationError(ReminderError, ValueError):
    """Raised when reminder data violates the Porter reminder contract."""


class ReminderNotFoundError(ReminderError):
    """Raised when a reminder ID does not exist for a principal."""


class ReminderStateError(ReminderError):
    """Raised when a reminder cannot make the requested state transition."""


class ReminderDeliveryError(ReminderError):
    """Expected failure handing a reminder to its configured delivery endpoint."""
