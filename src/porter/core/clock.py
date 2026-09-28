from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from tzlocal import get_localzone


def utc_now() -> datetime:
    """Return the current instant as an aware UTC datetime."""
    return datetime.now(UTC)


def system_timezone() -> ZoneInfo:
    """Return the operating system's configured IANA timezone."""
    return get_localzone()


def local_now() -> datetime:
    """Return the current instant in the operating system timezone."""
    return utc_now().astimezone(system_timezone())
