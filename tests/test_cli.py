import asyncio
from types import SimpleNamespace

import pytest

from porter.cli import _build_request, _route_label, _run_repl, _suggest_command
from porter.cli.main import _default_log_level, _main
from porter.cli.main import main as cli_main
from porter.core.models import (
    ExecutionPath,
    RequestContext,
    RequestResult,
    RequestSource,
)


def test_build_request_creates_cli_request() -> None:
    request = _build_request("hello")

    assert request.source is RequestSource.CLI
    assert request.principal_id == "local-user"
    assert request.messages[-1].role == "user"
    assert request.messages[-1].content == "hello"


def test_route_label_for_deterministic_result() -> None:
    result = RequestResult(
        text="done",
        path=ExecutionPath.DETERMINISTIC,
    )

    assert _route_label(result) == "deterministic"


def test_route_label_for_inference_result() -> None:
    result = RequestResult(
        text="done",
        path=ExecutionPath.INFERENCE,
        provider="ollama",
        model="qwen3:8b",
    )

    assert _route_label(result) == "inference: ollama/qwen3:8b"


def test_close_local_command_gets_one_suggestion() -> None:
    assert _suggest_command("which drives are mountd") == "which drives are mounted"


def test_unrelated_request_does_not_get_command_suggestion() -> None:
    assert _suggest_command("explain why the sky is blue") is None


def test_config_subcommand_dispatches(monkeypatch) -> None:
    calls: list[list[str]] = []

    monkeypatch.setattr(
        "porter.cli.commands.config.run",
        lambda args: calls.append(args) or 0,
    )

    result = _main(["config", "set", "ollama.model", "qwen2.5:7b"])

    assert result == 0
    assert calls == [["set", "ollama.model", "qwen2.5:7b"]]


@pytest.mark.parametrize(
    "command",
    [
        "exit",
        "quit",
        "exit()",
        "quit()",
    ],
)
def test_repl_exit_commands(command: str, monkeypatch) -> None:
    class FakeApplication:
        pass

    responses = iter([command])

    monkeypatch.setattr(
        "builtins.input",
        lambda _: next(responses),
    )

    result = asyncio.run(
        _run_repl(FakeApplication())  # type: ignore[arg-type]
    )

    assert result == 0


def test_repl_help_is_handled_locally(monkeypatch, capsys) -> None:
    responses = iter(("help", "quit"))
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    class FailingDispatcher:
        async def execute(self, request: RequestContext) -> None:
            raise AssertionError("help must not reach the request dispatcher")

    application = SimpleNamespace(dispatcher=FailingDispatcher())

    result = asyncio.run(
        _run_repl(application)  # type: ignore[arg-type]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert "Porter command examples" in captured.out
    assert "which drives are mounted" in captured.out
    assert "restart plex" in captured.out
    assert captured.err == ""


def test_repl_suggests_typo_without_dispatching(monkeypatch, capsys) -> None:
    responses = iter(("which drives are mountd", "quit"))
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    class FailingDispatcher:
        def __init__(self) -> None:
            self.calls = 0

        async def execute(self, request: RequestContext) -> None:
            self.calls += 1
            raise AssertionError("a suggested typo must not reach the dispatcher")

    dispatcher = FailingDispatcher()
    application = SimpleNamespace(dispatcher=dispatcher)

    result = asyncio.run(
        _run_repl(application)  # type: ignore[arg-type]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert dispatcher.calls == 0
    assert captured.out == ""
    assert (
        "porter: command not recognized. Did you mean: which drives are mounted"
        in captured.err
    )


def test_cli_entrypoint_defaults_structured_logging_to_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setitem(
        cli_main.__globals__,
        "configure_structured_logging",
        lambda **kwargs: captured.update(kwargs),
    )
    monkeypatch.setitem(cli_main.__globals__, "_main", lambda _args: 0)
    monkeypatch.setattr(cli_main.__globals__["sys"], "argv", ["porter"])

    with pytest.raises(SystemExit) as exc_info:
        cli_main()

    assert exc_info.value.code == 0
    assert captured == {"default_level": "WARNING"}


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ([], "WARNING"),
        (["what", "time", "is", "it"], "WARNING"),
        (["ask", "hello"], "WARNING"),
        (["tray"], "WARNING"),
        (["service"], "INFO"),
        (["web"], "INFO"),
    ],
)
def test_default_log_level_matches_command_mode(
    args: list[str],
    expected: str,
) -> None:
    assert _default_log_level(args) == expected
