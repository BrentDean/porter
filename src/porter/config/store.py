from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any


class ConfigFileError(ValueError):
    """Raised when Porter's durable configuration file is malformed."""


class ConfigStore:
    """Owns Porter's small durable user-configuration file."""

    def __init__(
        self,
        env: Mapping[str, str] | None = None,
        home: Path | None = None,
    ) -> None:
        self._env = dict(os.environ if env is None else env)
        self._home = Path.home() if home is None else home

    @property
    def path(self) -> Path:
        if configured := self._env.get("PORTER_CONFIG_FILE"):
            return Path(configured).expanduser()
        if xdg_config_home := self._env.get("XDG_CONFIG_HOME"):
            return Path(xdg_config_home).expanduser() / "porter" / "config.json"
        return self._home / ".config" / "porter" / "config.json"

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigFileError(f"invalid Porter config file: {self.path}") from exc
        if not isinstance(payload, dict):
            raise ConfigFileError(
                f"Porter config file must contain a JSON object: {self.path}"
            )
        return payload

    def ollama_model(self) -> str | None:
        return self._model("ollama")

    def openai_model(self) -> str | None:
        return self._model("openai")

    def set_ollama_model(self, model: str) -> None:
        self._set_model("ollama", model)

    def set_openai_model(self, model: str) -> None:
        self._set_model("openai", model)

    def _model(self, section: str) -> str | None:
        payload = self.load()
        value = payload.get(section)
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ConfigFileError(f"Porter config '{section}' value must be an object")
        model = value.get("model")
        if model is None:
            return None
        if not isinstance(model, str):
            raise ConfigFileError(f"Porter config '{section}.model' must be a string")
        return model

    def _set_model(self, section: str, model: str) -> None:
        normalized = model.strip()
        if not normalized:
            raise ValueError(f"{section} model must not be empty")
        payload = self.load()
        value = payload.setdefault(section, {})
        if not isinstance(value, dict):
            raise ConfigFileError(f"Porter config '{section}' value must be an object")
        value["model"] = normalized
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary_path, 0o600)
        temporary_path.replace(self.path)
