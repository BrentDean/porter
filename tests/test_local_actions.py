from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from porter.actions import (
    CommandResult,
    CommandRunner,
    PlexRestartHandler,
    PlexServiceController,
)
from porter.actions.plex import PlexServiceControlError
from porter.intents import DeterministicIntentExecutor, IntentHandlerRegistry, IntentResult
from tests.fakes import make_request


class FakeCommandRunner:
    def __init__(self, results: list[CommandResult]) -> None:
        self._results = list(results)
        self.calls: list[tuple[tuple[str, ...], bool]] = []

    async def run(
        self,
        argv: tuple[str, ...],
        *,
        check: bool = True,
    ) -> CommandResult:
        self.calls.append((argv, check))
        return self._results.pop(0)


def _result(*, returncode: int = 0, stdout: str = "", stderr: str = "") -> CommandResult:
    return CommandResult(
        argv=("fake",),
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _write_executable(path: Path, body: str) -> Path:
    path.write_text(f"#!/usr/bin/env python3\n{body}", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.mark.asyncio
async def test_command_runner_passes_arguments_without_a_shell(tmp_path: Path) -> None:
    arguments_path = tmp_path / "arguments.json"
    executable = _write_executable(
        tmp_path / "capture-args",
        (
            "import json\n"
            "import sys\n"
            "from pathlib import Path\n"
            f"Path({str(arguments_path)!r}).write_text("
            "json.dumps(sys.argv[1:]), encoding='utf-8')\n"
        ),
    )
    suspicious = "; touch /tmp/porter-should-not-exist"

    result = await CommandRunner().run((str(executable), suspicious))

    assert result.returncode == 0
    assert json.loads(arguments_path.read_text(encoding="utf-8")) == [suspicious]


@pytest.mark.parametrize(
    ("method_name", "systemctl_action", "status_returncode", "status_text", "state"),
    [
        ("start", "start", 0, "active", "active"),
        ("stop", "stop", 3, "inactive", "inactive"),
        ("restart", "restart", 0, "active", "active"),
    ],
)
@pytest.mark.asyncio
async def test_plex_service_actions_use_fixed_systemctl_commands(
    method_name: str,
    systemctl_action: str,
    status_returncode: int,
    status_text: str,
    state: str,
) -> None:
    runner = FakeCommandRunner(
        [
            _result(),
            _result(returncode=status_returncode, stdout=status_text),
        ]
    )
    controller = PlexServiceController(runner=runner)  # type: ignore[arg-type]

    observed_state = await getattr(controller, method_name)()

    assert observed_state == state
    assert runner.calls == [
        (
            (
                "/usr/bin/sudo",
                "-n",
                "/usr/bin/systemctl",
                systemctl_action,
                "plexmediaserver.service",
            ),
            True,
        ),
        (
            (
                "/usr/bin/systemctl",
                "is-active",
                "plexmediaserver.service",
            ),
            False,
        ),
    ]


@pytest.mark.asyncio
async def test_plex_restart_rejects_failed_postcondition() -> None:
    runner = FakeCommandRunner(
        [
            _result(),
            _result(returncode=3, stdout="failed"),
        ]
    )
    controller = PlexServiceController(runner=runner)  # type: ignore[arg-type]

    with pytest.raises(PlexServiceControlError, match="expected state active"):
        await controller.restart()


@pytest.mark.asyncio
async def test_restart_plex_is_a_deterministic_intent() -> None:
    runner = FakeCommandRunner(
        [
            _result(),
            _result(returncode=0, stdout="active"),
        ]
    )
    controller = PlexServiceController(runner=runner)  # type: ignore[arg-type]
    executor = DeterministicIntentExecutor(
        IntentHandlerRegistry((PlexRestartHandler(controller),))
    )

    result = await executor.execute(make_request(content="restart plex"))

    assert result == IntentResult(
        text="Plex restarted.",
        data={
            "action": "plex.restart",
            "service": "plexmediaserver.service",
            "state": "active",
        },
    )
