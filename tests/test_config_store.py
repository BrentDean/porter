import json
from pathlib import Path

import pytest

from porter.config.loader import ConfigLoader
from porter.config.store import ConfigFileError, ConfigStore


def test_config_store_uses_xdg_config_home(tmp_path: Path) -> None:
    store = ConfigStore(
        env={"XDG_CONFIG_HOME": str(tmp_path / "xdg")},
        home=tmp_path,
    )

    assert store.path == tmp_path / "xdg" / "porter" / "config.json"


def test_config_store_persists_ollama_model(tmp_path: Path) -> None:
    store = ConfigStore(env={}, home=tmp_path)

    store.set_ollama_model("qwen2.5:7b")

    assert store.ollama_model() == "qwen2.5:7b"
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert payload == {"ollama": {"model": "qwen2.5:7b"}}


def test_config_loader_uses_durable_ollama_model(tmp_path: Path) -> None:
    ConfigStore(env={}, home=tmp_path).set_ollama_model("qwen2.5:7b")

    config = ConfigLoader(env={}, home=tmp_path).load()

    assert config.ollama.model == "qwen2.5:7b"


def test_environment_ollama_model_overrides_durable_config(tmp_path: Path) -> None:
    ConfigStore(env={}, home=tmp_path).set_ollama_model("qwen2.5:7b")

    config = ConfigLoader(
        env={"PORTER_OLLAMA_MODEL": "llama3.2:3b"},
        home=tmp_path,
    ).load()

    assert config.ollama.model == "llama3.2:3b"


def test_storage_only_load_ignores_malformed_durable_config(tmp_path: Path) -> None:
    store = ConfigStore(env={}, home=tmp_path)
    store.path.parent.mkdir(parents=True)
    store.path.write_text("not-json", encoding="utf-8")

    storage = ConfigLoader(env={}, home=tmp_path).load_storage()

    assert storage.database_path == tmp_path / ".local" / "share" / "porter" / "porter.db"


def test_full_config_rejects_malformed_durable_config(tmp_path: Path) -> None:
    store = ConfigStore(env={}, home=tmp_path)
    store.path.parent.mkdir(parents=True)
    store.path.write_text("not-json", encoding="utf-8")

    with pytest.raises(ConfigFileError, match="invalid Porter config file"):
        ConfigLoader(env={}, home=tmp_path).load()
