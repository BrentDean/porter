from __future__ import annotations

import asyncio
import signal
from collections.abc import Iterator
from contextlib import contextmanager

from porter.service.runtime import PorterService
from porter.telemetry.structured_logging import emit_event

_SHUTDOWN_SIGNALS = (signal.SIGINT, signal.SIGTERM)


@contextmanager
def shutdown_signal_handlers(
    stop_event: asyncio.Event,
) -> Iterator[None]:
    """Translate supported process shutdown signals into a service stop event."""
    loop = asyncio.get_running_loop()
    installed: list[signal.Signals] = []

    for signum in _SHUTDOWN_SIGNALS:
        try:
            loop.add_signal_handler(
                signum,
                _request_shutdown,
                signum,
                stop_event,
            )
        except NotImplementedError:
            continue
        installed.append(signum)

    try:
        yield
    finally:
        for signum in installed:
            loop.remove_signal_handler(signum)


def _request_shutdown(
    signum: signal.Signals,
    stop_event: asyncio.Event,
) -> None:
    emit_event(
        "service.shutdown_requested",
        signal=signum.name,
    )
    stop_event.set()


async def run_until_shutdown(service: PorterService) -> None:
    """Run a service until SIGINT/SIGTERM requests graceful shutdown."""
    stop_event = asyncio.Event()
    with shutdown_signal_handlers(stop_event):
        await service.run(stop_event)
