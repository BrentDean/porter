from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from porter.config.models import (
    OllamaConfig,
    OpenAIConfig,
    PorterConfig,
    StorageConfig,
    WeatherConfig,
)
from porter.config.store import ConfigStore


class ConfigLoader:
    """Builds Porter configuration from durable settings, environment, and defaults."""

    def __init__(
        self,
        env: Mapping[str, str] | None = None,
        home: Path | None = None,
    ) -> None:
        self._env = dict(os.environ if env is None else env)
        self._home = Path.home() if home is None else home
        self._store = ConfigStore(env=self._env, home=self._home)

    @property
    def config_path(self) -> Path:
        return self._store.path

    def load_storage(self) -> StorageConfig:
        """Load only the storage settings required by lightweight runtimes."""
        data_dir = self._data_dir()
        return StorageConfig(
            data_dir=data_dir,
            database_path=self._database_path(data_dir),
        )

    def load(self) -> PorterConfig:
        return PorterConfig(
            storage=self.load_storage(),
            ollama=OllamaConfig(
                model=self._optional("PORTER_OLLAMA_MODEL")
                or self._store.ollama_model(),
                base_url=self._env.get(
                    "PORTER_OLLAMA_URL",
                    "http://127.0.0.1:11434",
                ),
                timeout_seconds=self._positive_float(
                    "PORTER_OLLAMA_TIMEOUT_SECONDS",
                    default=120.0,
                ),
                keep_alive=self._optional("PORTER_OLLAMA_KEEP_ALIVE"),
            ),
            openai=OpenAIConfig(
                api_key=self._optional("OPENAI_API_KEY"),
                model=self._optional("PORTER_OPENAI_MODEL")
                or self._store.openai_model(),
                timeout_seconds=self._positive_float(
                    "PORTER_OPENAI_TIMEOUT_SECONDS",
                    default=120.0,
                ),
            ),
            weather=WeatherConfig(
                synoptic_token=self._optional("PORTER_SYNOPIC_TOKEN"),
                synoptic_radius_miles=self._positive_float(
                    "PORTER_SYNOPIC_RADIUS_MILES",
                    default=5.0,
                ),
                synoptic_station_limit=self._positive_int(
                    "PORTER_SYNOPIC_STATION_LIMIT",
                    default=12,
                ),
                synoptic_within_minutes=self._positive_int(
                    "PORTER_SYNOPIC_WITHIN_MINUTES",
                    default=30,
                ),
            ),
        )

    def _data_dir(self) -> Path:
        if configured := self._env.get("PORTER_DATA_DIR"):
            return Path(configured).expanduser()

        if xdg_data_home := self._env.get("XDG_DATA_HOME"):
            return Path(xdg_data_home).expanduser() / "porter"

        return self._home / ".local" / "share" / "porter"

    def _database_path(self, data_dir: Path) -> Path:
        if configured := self._env.get("PORTER_DB_PATH"):
            return Path(configured).expanduser()

        return data_dir / "porter.db"

    def _optional(self, name: str) -> str | None:
        value = self._env.get(name)
        if value is None or not value.strip():
            return None
        return value.strip()

    def _positive_float(self, name: str, *, default: float) -> float:
        raw = self._env.get(name)
        if raw is None:
            return default

        try:
            value = float(raw)
        except ValueError as exc:
            raise ValueError(f"{name} must be a number") from exc

        if value <= 0:
            raise ValueError(f"{name} must be positive")
        return value

    def _positive_int(self, name: str, *, default: int) -> int:
        raw = self._env.get(name)
        if raw is None:
            return default

        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError(f"{name} must be an integer") from exc

        if value <= 0:
            raise ValueError(f"{name} must be positive")
        return value
