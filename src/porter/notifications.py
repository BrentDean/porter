from __future__ import annotations

import asyncio
import json
import math
import os
from asyncio.subprocess import PIPE
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from porter.reminders import (
    Reminder,
    ReminderDelivery,
    ReminderDeliveryError,
    ReminderKind,
)

_DEFAULT_TIMEOUT_SECONDS = 10.0
_TRAY_TIMEOUT_SECONDS = 2.0
_MAX_ERROR_DETAIL_LENGTH = 500
_TRAY_SOCKET_NAME = "reminders.sock"


@dataclass(frozen=True, slots=True)
class TrayNotificationRequest:
    reminder_id: str
    principal_id: str
    message: str
    kind: ReminderKind = ReminderKind.REMINDER

    @classmethod
    def from_reminder(cls, reminder: Reminder) -> TrayNotificationRequest:
        return cls(
            reminder_id=reminder.id,
            principal_id=reminder.principal_id,
            message=reminder.message,
            kind=reminder.kind,
        )


def tray_socket_path(
    env: Mapping[str, str] | None = None,
) -> Path | None:
    source = os.environ if env is None else env
    runtime_dir = source.get("XDG_RUNTIME_DIR")
    if not runtime_dir:
        return None
    return Path(runtime_dir) / "porter" / _TRAY_SOCKET_NAME


def encode_tray_notification(request: TrayNotificationRequest) -> bytes:
    payload = {
        "reminder_id": request.reminder_id,
        "principal_id": request.principal_id,
        "message": request.message,
        "kind": request.kind.value,
    }
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode()


def decode_tray_notification(payload: bytes) -> TrayNotificationRequest:
    try:
        decoded = json.loads(payload.decode())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid tray notification payload") from exc

    if not isinstance(decoded, dict):
        raise ValueError("tray notification payload must be an object")

    values: dict[str, str] = {}
    for key in ("reminder_id", "principal_id", "message"):
        value = decoded.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"tray notification {key} must be non-empty text")
        values[key] = value

    try:
        kind = ReminderKind(decoded.get("kind", "reminder"))
    except ValueError as exc:
        raise ValueError("invalid tray notification kind") from exc

    return TrayNotificationRequest(
        reminder_id=values["reminder_id"],
        principal_id=values["principal_id"],
        message=values["message"],
        kind=kind,
    )


class TraySocketReminderDelivery:
    """Deliver reminder presentation requests to the running Porter tray."""

    def __init__(
        self,
        *,
        socket_path: Path | None = None,
        timeout_seconds: float = _TRAY_TIMEOUT_SECONDS,
    ) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a finite positive number")
        self._socket_path = socket_path if socket_path is not None else tray_socket_path()
        self._timeout_seconds = float(timeout_seconds)

    @property
    def socket_path(self) -> Path | None:
        return self._socket_path

    async def deliver(self, reminder: Reminder) -> None:
        if self._socket_path is None:
            raise ReminderDeliveryError(
                "Porter tray delivery requires XDG_RUNTIME_DIR"
            )

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(str(self._socket_path)),
                timeout=self._timeout_seconds,
            )
        except (OSError, TimeoutError) as exc:
            raise ReminderDeliveryError(
                f"Porter tray is unavailable: {exc}"
            ) from exc

        try:
            writer.write(
                encode_tray_notification(
                    TrayNotificationRequest.from_reminder(reminder)
                )
            )
            await asyncio.wait_for(
                writer.drain(),
                timeout=self._timeout_seconds,
            )
            response = await asyncio.wait_for(
                reader.readline(),
                timeout=self._timeout_seconds,
            )
            if response != b"OK\n":
                raise ReminderDeliveryError(
                    "Porter tray rejected the reminder notification"
                )
        except (OSError, TimeoutError) as exc:
            raise ReminderDeliveryError(
                f"Porter tray delivery failed: {exc}"
            ) from exc
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass


class FallbackReminderDelivery:
    """Try the Porter tray first, then a durable desktop fallback."""

    def __init__(
        self,
        primary: ReminderDelivery,
        fallback: ReminderDelivery,
    ) -> None:
        self._primary = primary
        self._fallback = fallback

    async def deliver(self, reminder: Reminder) -> None:
        try:
            await self._primary.deliver(reminder)
        except ReminderDeliveryError:
            await self._fallback.deliver(reminder)


class NotifySendReminderDelivery:
    """Deliver reminders through the host's freedesktop notify-send client."""

    def __init__(
        self,
        *,
        executable: str = "notify-send",
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not executable.strip():
            raise ValueError("notify-send executable must not be empty")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a finite positive number")

        self._executable = executable
        self._timeout_seconds = float(timeout_seconds)

    @property
    def executable(self) -> str:
        return self._executable

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

    async def deliver(self, reminder: Reminder) -> None:
        try:
            process = await asyncio.create_subprocess_exec(
                self._executable,
                "--app-name",
                "Porter",
                "--urgency",
                "normal",
                "--",
                "Porter Timer" if reminder.kind is ReminderKind.TIMER else "Porter Reminder",
                reminder.message,
                stdout=PIPE,
                stderr=PIPE,
            )
        except OSError as exc:
            raise ReminderDeliveryError(
                f"could not launch notify-send: {exc}"
            ) from exc

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self._timeout_seconds,
            )
        except TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.communicate()
            raise ReminderDeliveryError("notify-send timed out") from None

        if process.returncode != 0:
            detail = _error_detail(stderr, stdout)
            raise ReminderDeliveryError(
                f"notify-send failed with exit status {process.returncode}: {detail}"
            )


def _error_detail(stderr: bytes, stdout: bytes) -> str:
    detail = stderr.decode(errors="replace").strip()
    if not detail:
        detail = stdout.decode(errors="replace").strip()
    if not detail:
        return "no error detail"
    if len(detail) > _MAX_ERROR_DETAIL_LENGTH:
        return f"{detail[:_MAX_ERROR_DETAIL_LENGTH]}..."
    return detail


__all__ = [
    "FallbackReminderDelivery",
    "NotifySendReminderDelivery",
    "TrayNotificationRequest",
    "TraySocketReminderDelivery",
    "decode_tray_notification",
    "encode_tray_notification",
    "tray_socket_path",
]
