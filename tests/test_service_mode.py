from __future__ import annotations

import asyncio
import signal
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from porter.reminders import Reminder, ReminderStatus
from porter.service import PorterService, build_service_runtime, shutdown_signal_handlers


class CountingRunner:
    def __init__(
        self,
        *,
        stop_event: asyncio.Event | None = None,
        stop_after: int | None = None,
    ) -> None:
        self.stop_event = stop_event
        self.stop_after = stop_after
        self.calls = 0

    async def run_once(self) -> None:
        self.calls += 1
        if self.stop_after == self.calls and self.stop_event is not None:
            self.stop_event.set()


class BlockingRunner:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def run_once(self) -> None:
        self.calls += 1
        self.started.set()
        await self.release.wait()


class FailingRunner:
    async def run_once(self) -> None:
        raise RuntimeError("systemic reminder failure")


class StoppingDelivery:
    def __init__(self, stop_event: asyncio.Event) -> None:
        self.stop_event = stop_event
        self.reminders: list[Reminder] = []

    async def deliver(self, reminder: Reminder) -> None:
        self.reminders.append(reminder)
        self.stop_event.set()


class FakeSignalLoop:
    def __init__(self, *, supported: bool = True) -> None:
        self.supported = supported
        self.handlers: dict[signal.Signals, tuple[object, tuple[object, ...]]] = {}
        self.removed: list[signal.Signals] = []

    def add_signal_handler(self, signum, callback, *args) -> None:
        if not self.supported:
            raise NotImplementedError
        self.handlers[signum] = (callback, args)

    def remove_signal_handler(self, signum) -> bool:
        self.removed.append(signum)
        self.handlers.pop(signum, None)
        return True


@pytest.mark.asyncio
async def test_service_runs_immediately_and_repeats_until_stopped() -> None:
    stop_event = asyncio.Event()
    runner = CountingRunner(stop_event=stop_event, stop_after=3)
    service = PorterService(runner, poll_interval_seconds=0.001)

    await service.run(stop_event)

    assert runner.calls == 3
    assert service.poll_interval_seconds == 0.001


@pytest.mark.asyncio
async def test_service_does_no_work_when_already_stopped() -> None:
    stop_event = asyncio.Event()
    stop_event.set()
    runner = CountingRunner()
    service = PorterService(runner)

    await service.run(stop_event)

    assert runner.calls == 0


@pytest.mark.asyncio
async def test_stop_event_interrupts_long_idle_wait() -> None:
    stop_event = asyncio.Event()
    first_pass_done = asyncio.Event()

    class FirstPassRunner:
        def __init__(self) -> None:
            self.calls = 0

        async def run_once(self) -> None:
            self.calls += 1
            first_pass_done.set()

    runner = FirstPassRunner()
    service = PorterService(runner, poll_interval_seconds=60.0)
    task = asyncio.create_task(service.run(stop_event))

    await asyncio.wait_for(first_pass_done.wait(), timeout=1.0)
    stop_event.set()
    await asyncio.wait_for(task, timeout=1.0)

    assert runner.calls == 1


@pytest.mark.resilience
@pytest.mark.asyncio
async def test_shutdown_allows_in_flight_pass_to_finish() -> None:
    stop_event = asyncio.Event()
    runner = BlockingRunner()
    service = PorterService(runner, poll_interval_seconds=60.0)
    task = asyncio.create_task(service.run(stop_event))

    await asyncio.wait_for(runner.started.wait(), timeout=1.0)
    stop_event.set()

    assert not task.done()

    runner.release.set()
    await asyncio.wait_for(task, timeout=1.0)

    assert runner.calls == 1


@pytest.mark.asyncio
async def test_unexpected_runner_error_stops_service() -> None:
    stop_event = asyncio.Event()
    service = PorterService(FailingRunner())

    with pytest.raises(RuntimeError, match="systemic reminder failure"):
        await service.run(stop_event)


@pytest.mark.parametrize(
    "poll_interval_seconds",
    [0.0, -1.0, float("inf"), float("-inf"), float("nan")],
)
def test_service_rejects_invalid_poll_interval(poll_interval_seconds: float) -> None:
    with pytest.raises(ValueError, match="finite positive"):
        PorterService(
            CountingRunner(),
            poll_interval_seconds=poll_interval_seconds,
        )


@pytest.mark.asyncio
async def test_lightweight_bootstrap_runs_due_reminder_without_provider_graph(
    tmp_path: Path,
) -> None:
    stop_event = asyncio.Event()
    delivery = StoppingDelivery(stop_event)
    database_path = tmp_path / "service.db"
    runtime = build_service_runtime(
        delivery,
        env={
            "PORTER_DB_PATH": str(database_path),
            "PORTER_OLLAMA_TIMEOUT_SECONDS": "never",
            "PORTER_SYNOPIC_STATION_LIMIT": "1",
        },
        home=tmp_path,
        poll_interval_seconds=60.0,
    )
    reminder = runtime.reminder_service.create_reminder(
        "alice",
        "Service mode reminder",
        datetime.now(UTC) - timedelta(seconds=1),
    )

    await runtime.service.run(stop_event)

    loaded = runtime.reminder_service.get_reminder("alice", reminder.id)
    assert database_path.exists()
    assert runtime.storage_config.database_path == database_path
    assert not hasattr(runtime, "config")
    assert not hasattr(runtime, "provider_registry")
    assert [item.id for item in delivery.reminders] == [reminder.id]
    assert loaded.status is ReminderStatus.DELIVERED


@pytest.mark.resilience
def test_shutdown_signal_handlers_set_event_and_restore_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop_event = asyncio.Event()
    loop = FakeSignalLoop()
    monkeypatch.setattr(
        "porter.service.signals.asyncio.get_running_loop",
        lambda: loop,
    )

    with shutdown_signal_handlers(stop_event):
        assert set(loop.handlers) == {signal.SIGINT, signal.SIGTERM}
        callback, args = loop.handlers[signal.SIGTERM]
        callback(*args)
        assert stop_event.is_set()

    assert set(loop.removed) == {signal.SIGINT, signal.SIGTERM}
    assert loop.handlers == {}


def test_shutdown_signal_handlers_tolerate_unsupported_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop_event = asyncio.Event()
    loop = FakeSignalLoop(supported=False)
    monkeypatch.setattr(
        "porter.service.signals.asyncio.get_running_loop",
        lambda: loop,
    )

    with shutdown_signal_handlers(stop_event):
        assert loop.handlers == {}

    assert loop.removed == []
