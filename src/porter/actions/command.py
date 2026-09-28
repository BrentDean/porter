from __future__ import annotations

import asyncio
import math
from asyncio.subprocess import PIPE
from dataclasses import dataclass

_DEFAULT_TIMEOUT_SECONDS = 30.0
_MAX_ERROR_DETAIL_LENGTH = 500


class CommandExecutionError(RuntimeError):
    """A known local command could not be executed successfully."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class CommandRunner:
    """Execute an explicit argv without invoking a shell."""

    def __init__(self, *, timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a finite positive number")
        self._timeout_seconds = float(timeout_seconds)

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

    async def run(
        self,
        argv: tuple[str, ...],
        *,
        check: bool = True,
    ) -> CommandResult:
        if not argv or not argv[0].strip():
            raise ValueError("command argv must include a non-empty executable")

        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdout=PIPE,
                stderr=PIPE,
            )
        except OSError as exc:
            raise CommandExecutionError(
                f"could not launch {argv[0]}: {exc}"
            ) from exc

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=self._timeout_seconds,
            )
        except TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.communicate()
            raise CommandExecutionError(
                f"{argv[0]} timed out after {self._timeout_seconds:g} seconds"
            ) from None

        result = CommandResult(
            argv=argv,
            returncode=process.returncode,
            stdout=stdout_bytes.decode(errors="replace").strip(),
            stderr=stderr_bytes.decode(errors="replace").strip(),
        )

        if check and result.returncode != 0:
            detail = _error_detail(result)
            raise CommandExecutionError(
                f"{argv[0]} failed with exit status {result.returncode}: {detail}"
            )

        return result


def _error_detail(result: CommandResult) -> str:
    detail = result.stderr or result.stdout or "no error detail"
    if len(detail) > _MAX_ERROR_DETAIL_LENGTH:
        return f"{detail[:_MAX_ERROR_DETAIL_LENGTH]}..."
    return detail
