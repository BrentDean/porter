from __future__ import annotations

import asyncio
import logging
import math

from porter.reminders import ReminderRunner
from porter.telemetry.structured_logging import emit_event

DEFAULT_POLL_INTERVAL_SECONDS = 1.0


class PorterService:
    """Long-running lightweight service loop for background Porter work."""

    def __init__(
        self,
        reminder_runner: ReminderRunner,
        *,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    ) -> None:
        if not math.isfinite(poll_interval_seconds) or poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be a finite positive number")
        self._reminder_runner = reminder_runner
        self._poll_interval_seconds = float(poll_interval_seconds)

    @property
    def poll_interval_seconds(self) -> float:
        return self._poll_interval_seconds

    async def run(self, stop_event: asyncio.Event) -> None:
        """Run reminder passes until stop_event is set.

        A pass starts immediately on service startup. Shutdown is graceful: if a
        pass is already running, it is allowed to finish before the service exits.
        """
        emit_event(
            "service.started",
            poll_interval_seconds=self._poll_interval_seconds,
        )
        try:
            while not stop_event.is_set():
                await self._reminder_runner.run_once()

                if stop_event.is_set():
                    break

                try:
                    await asyncio.wait_for(
                        stop_event.wait(),
                        timeout=self._poll_interval_seconds,
                    )
                except TimeoutError:
                    pass
        except Exception as exc:
            emit_event(
                "service.failed",
                level=logging.ERROR,
                error_classification=type(exc).__name__,
            )
            raise
        finally:
            emit_event("service.stopped")
