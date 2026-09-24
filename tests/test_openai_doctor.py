import asyncio
from pathlib import Path

from porter.cli.commands.doctor import _run_doctor
from porter.config.loader import ConfigLoader


def test_doctor_reports_openai_ready_without_exposing_key(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    class FakeOllamaClient:
        def __init__(self, config) -> None:
            pass

        async def list_models(self) -> dict[str, object]:
            return {"models": []}

    monkeypatch.setattr("porter.cli.commands.doctor.OllamaClient", FakeOllamaClient)
    monkeypatch.setattr("porter.cli.commands.doctor.which", lambda name: None)

    result = asyncio.run(
        _run_doctor(
            ConfigLoader(
                env={
                    "PORTER_DATA_DIR": str(tmp_path / "data"),
                    "PORTER_OPENAI_MODEL": "gpt-5.4-mini",
                    "OPENAI_API_KEY": "super-secret-key",
                },
                home=tmp_path,
            )
        )
    )

    output = capsys.readouterr().out
    assert result == 0
    assert "OpenAI cloud fallback" in output
    assert "model: gpt-5.4-mini" in output
    assert "API key: configured" in output
    assert "status: ready (explicit --allow-cloud required)" in output
    assert "super-secret-key" not in output
