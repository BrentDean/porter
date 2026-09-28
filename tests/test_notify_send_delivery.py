from __future__ import annotations

import json
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from porter.notifications import NotifySendReminderDelivery
from porter.reminders import (
    Reminder,
    ReminderDeliveryError,
    ReminderStatus,
)

NOW = datetime(2026, 8, 15, 20, tzinfo=UTC)


def _reminder(message: str = "Take out the garbage") -> Reminder:
    return Reminder(
        id="reminder-1",
        principal_id="alice",
        message=message,
        trigger_at=NOW,
        status=ReminderStatus.SCHEDULED,
        created_at=NOW,
        updated_at=NOW,
    )


def _write_executable(path: Path, body: str) -> Path:
    path.write_text(f"#!/usr/bin/env python3\n{body}", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.mark.asyncio
async def test_notify_send_passes_reminder_as_literal_arguments(tmp_path: Path) -> None:
    arguments_path = tmp_path / "arguments.json"
    executable = _write_executable(
        tmp_path / "fake-notify-send",
        (
            "import json\n"
            "import sys\n"
            "from pathlib import Path\n"
            f"Path({str(arguments_path)!r}).write_text("
            "json.dumps(sys.argv[1:]), encoding='utf-8')\n"
        ),
    )
    message = "--urgency=critical; touch /tmp/porter-should-not-exist"
    delivery = NotifySendReminderDelivery(executable=str(executable))

    await delivery.deliver(_reminder(message))

    arguments = json.loads(arguments_path.read_text(encoding="utf-8"))
    assert arguments == [
        "--app-name",
        "Porter",
        "--urgency",
        "normal",
        "--",
        "Porter Reminder",
        message,
    ]


@pytest.mark.asyncio
async def test_notify_send_nonzero_exit_is_delivery_error(tmp_path: Path) -> None:
    executable = _write_executable(
        tmp_path / "failing-notify-send",
        (
            "import sys\n"
            "sys.stdout.write('less useful output\\n')\n"
            "sys.stderr.write('notification server unavailable\\n')\n"
            "raise SystemExit(3)\n"
        ),
    )
    delivery = NotifySendReminderDelivery(executable=str(executable))

    with pytest.raises(
        ReminderDeliveryError,
        match="exit status 3: notification server unavailable",
    ):
        await delivery.deliver(_reminder())


@pytest.mark.asyncio
async def test_notify_send_timeout_is_delivery_error(tmp_path: Path) -> None:
    executable = _write_executable(
        tmp_path / "slow-notify-send",
        "import time\ntime.sleep(5)\n",
    )
    delivery = NotifySendReminderDelivery(
        executable=str(executable),
        timeout_seconds=0.05,
    )

    with pytest.raises(ReminderDeliveryError, match="timed out"):
        await delivery.deliver(_reminder())


@pytest.mark.asyncio
async def test_notify_send_missing_executable_is_delivery_error(tmp_path: Path) -> None:
    delivery = NotifySendReminderDelivery(
        executable=str(tmp_path / "missing-notify-send")
    )

    with pytest.raises(ReminderDeliveryError, match="could not launch notify-send"):
        await delivery.deliver(_reminder())


@pytest.mark.parametrize(
    "timeout_seconds",
    [0.0, -1.0, float("inf"), float("-inf"), float("nan")],
)
def test_notify_send_rejects_invalid_timeout(timeout_seconds: float) -> None:
    with pytest.raises(ValueError, match="finite positive"):
        NotifySendReminderDelivery(timeout_seconds=timeout_seconds)


def test_notify_send_rejects_empty_executable() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        NotifySendReminderDelivery(executable="   ")
