from __future__ import annotations

import asyncio
import shutil

from porter.notifications import (
    FallbackReminderDelivery,
    NotifySendReminderDelivery,
    TraySocketReminderDelivery,
)
from porter.service.bootstrap import PorterServiceRuntime, build_service_runtime
from porter.service.signals import run_until_shutdown


def build_desktop_service_runtime() -> PorterServiceRuntime:
    """Compose the background service with tray-first desktop notification delivery."""
    executable = shutil.which("notify-send")
    if executable is None:
        raise RuntimeError(
            "Porter desktop reminders require the notify-send executable"
        )

    return build_service_runtime(
        FallbackReminderDelivery(
            TraySocketReminderDelivery(),
            NotifySendReminderDelivery(executable=executable),
        ),
    )


async def run() -> None:
    """Run Porter's lightweight reminder service until process shutdown."""
    runtime = build_desktop_service_runtime()
    await run_until_shutdown(runtime.service)


def main() -> None:
    """Console entry point for Porter's lightweight reminder service."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
