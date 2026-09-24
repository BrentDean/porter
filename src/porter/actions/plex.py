from __future__ import annotations

from porter.actions.command import CommandRunner
from porter.core.models import RequestContext
from porter.intents.handlers import IntentHandler
from porter.intents.models import IntentResult, RecognizedIntent

_DEFAULT_SUDO = "/usr/bin/sudo"
_DEFAULT_SYSTEMCTL = "/usr/bin/systemctl"
_DEFAULT_UNIT = "plexmediaserver.service"


class PlexServiceControlError(RuntimeError):
    """Plex service control completed without reaching the expected state."""


class PlexServiceController:
    def __init__(
        self,
        runner: CommandRunner | None = None,
        *,
        sudo_executable: str = _DEFAULT_SUDO,
        systemctl_executable: str = _DEFAULT_SYSTEMCTL,
        unit: str = _DEFAULT_UNIT,
    ) -> None:
        self._runner = runner or CommandRunner()
        self._sudo_executable = sudo_executable
        self._systemctl_executable = systemctl_executable
        self._unit = unit

    @property
    def unit(self) -> str:
        return self._unit

    async def start(self) -> str:
        await self._change_state("start", expected_active=True)
        return "active"

    async def stop(self) -> str:
        await self._change_state("stop", expected_active=False)
        return "inactive"

    async def restart(self) -> str:
        await self._change_state("restart", expected_active=True)
        return "active"

    async def _change_state(self, action: str, *, expected_active: bool) -> None:
        await self._runner.run(
            (
                self._sudo_executable,
                "-n",
                self._systemctl_executable,
                action,
                self._unit,
            )
        )

        status = await self._runner.run(
            (
                self._systemctl_executable,
                "is-active",
                self._unit,
            ),
            check=False,
        )
        active = status.returncode == 0 and status.stdout == "active"
        if active is not expected_active:
            expected = "active" if expected_active else "inactive"
            observed = status.stdout or f"exit-{status.returncode}"
            raise PlexServiceControlError(
                f"Plex did not reach expected state {expected}: {observed}"
            )


class PlexStartHandler(IntentHandler):
    intent_name = "PorterPlexStart"

    def __init__(self, controller: PlexServiceController) -> None:
        self._controller = controller

    async def handle(
        self,
        request: RequestContext,
        intent: RecognizedIntent,
    ) -> IntentResult:
        state = await self._controller.start()
        return IntentResult(
            text="Plex started.",
            data={
                "action": "plex.start",
                "service": self._controller.unit,
                "state": state,
            },
        )


class PlexStopHandler(IntentHandler):
    intent_name = "PorterPlexStop"

    def __init__(self, controller: PlexServiceController) -> None:
        self._controller = controller

    async def handle(
        self,
        request: RequestContext,
        intent: RecognizedIntent,
    ) -> IntentResult:
        state = await self._controller.stop()
        return IntentResult(
            text="Plex stopped.",
            data={
                "action": "plex.stop",
                "service": self._controller.unit,
                "state": state,
            },
        )


class PlexRestartHandler(IntentHandler):
    intent_name = "PorterPlexRestart"

    def __init__(self, controller: PlexServiceController) -> None:
        self._controller = controller

    async def handle(
        self,
        request: RequestContext,
        intent: RecognizedIntent,
    ) -> IntentResult:
        state = await self._controller.restart()
        return IntentResult(
            text="Plex restarted.",
            data={
                "action": "plex.restart",
                "service": self._controller.unit,
                "state": state,
            },
        )
