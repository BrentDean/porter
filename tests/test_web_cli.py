from __future__ import annotations

from types import SimpleNamespace

import pytest

from porter.cli.commands import web


def test_web_cli_defaults_to_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = object()
    captured: dict[str, object] = {}

    monkeypatch.setattr(web, "create_web_app", lambda: application)
    monkeypatch.setattr(
        web,
        "uvicorn",
        SimpleNamespace(
            run=lambda app, *, host, port: captured.update(
                app=app,
                host=host,
                port=port,
            )
        ),
    )

    result = web.run([], env={})

    assert result == 0
    assert captured == {
        "app": application,
        "host": "127.0.0.1",
        "port": 8000,
    }


def test_web_cli_uses_explicit_container_bind_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(web, "create_web_app", lambda: object())
    monkeypatch.setattr(
        web,
        "uvicorn",
        SimpleNamespace(
            run=lambda app, *, host, port: captured.update(
                host=host,
                port=port,
            )
        ),
    )

    result = web.run(
        ["--port", "9000"],
        env={"PORTER_WEB_HOST": "0.0.0.0"},
    )

    assert result == 0
    assert captured == {
        "host": "0.0.0.0",
        "port": 9000,
    }


def test_web_cli_rejects_empty_bind_host() -> None:
    with pytest.raises(
        ValueError,
        match="PORTER_WEB_HOST must not be empty",
    ):
        web.run([], env={"PORTER_WEB_HOST": "   "})
