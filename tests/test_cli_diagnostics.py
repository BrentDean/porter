import asyncio
from pathlib import Path
from types import SimpleNamespace

from porter.cli import (
    _provider_unavailable_message,
    _run_doctor,
    _set_config,
)
from porter.config.loader import ConfigLoader
from porter.config.models import OllamaConfig
from porter.config.store import ConfigStore
from porter.core.exceptions import NoProviderAvailable


def test_no_provider_message_explains_missing_local_model() -> None:
    application = SimpleNamespace(
        provider_registry=SimpleNamespace(all=lambda: ()),
        config=SimpleNamespace(ollama=OllamaConfig()),
    )

    message = _provider_unavailable_message(  # type: ignore[arg-type]
        application,
        NoProviderAvailable("route contains no eligible providers"),
    )

    assert "no local AI model is configured" in message
    assert "porter config set ollama.model <model>" in message


def test_missing_local_model_is_explained_even_with_cloud_configured() -> None:
    application = SimpleNamespace(
        provider_registry=SimpleNamespace(
            all=lambda: (SimpleNamespace(is_cloud=True),)
        ),
        config=SimpleNamespace(ollama=OllamaConfig()),
    )

    message = _provider_unavailable_message(  # type: ignore[arg-type]
        application,
        NoProviderAvailable("route contains no eligible providers"),
    )

    assert "no local AI model is configured" in message


def test_doctor_reports_healthy_configured_ollama(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    ConfigStore(env={}, home=tmp_path).set_ollama_model("qwen2.5:7b")

    class FakeOllamaClient:
        def __init__(self, config: OllamaConfig) -> None:
            assert config.model == "qwen2.5:7b"

        async def list_models(self) -> dict[str, object]:
            return {"models": [{"name": "qwen2.5:7b"}]}

    monkeypatch.setattr(
        "porter.cli.commands.doctor.OllamaClient",
        FakeOllamaClient,
    )
    monkeypatch.setattr(
        "porter.cli.commands.doctor.which",
        lambda name: f"/usr/bin/{name}",
    )

    result = asyncio.run(
        _run_doctor(ConfigLoader(env={}, home=tmp_path))
    )

    captured = capsys.readouterr()
    assert result == 0
    assert "configured: yes" in captured.out
    assert "model: qwen2.5:7b" in captured.out
    assert "server: available" in captured.out
    assert "model installed: yes" in captured.out
    assert "status: healthy" in captured.out


def test_config_set_persists_ollama_model(monkeypatch, capsys) -> None:
    saved: list[str] = []

    class FakeConfigStore:
        path = Path("/tmp/porter-config.json")

        def set_ollama_model(self, model: str) -> None:
            saved.append(model)

    monkeypatch.setattr(
        "porter.cli.commands.config.ConfigStore",
        FakeConfigStore,
    )

    result = _set_config(
        ["config", "set", "ollama.model", "qwen2.5:7b"]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert saved == ["qwen2.5:7b"]
    assert "Saved ollama.model=qwen2.5:7b" in captured.out
