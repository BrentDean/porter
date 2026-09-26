from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class StorageConfig:
    """Filesystem locations owned by Porter's persistence layer."""

    data_dir: Path
    database_path: Path


@dataclass(frozen=True, slots=True)
class OllamaConfig:
    """Configuration for Porter's loopback-only Ollama adapter."""

    model: str | None = None
    base_url: str = "http://127.0.0.1:11434"
    timeout_seconds: float = 120.0
    keep_alive: str | None = None

    def __post_init__(self) -> None:
        if self.model is not None and not self.model.strip():
            raise ValueError("Ollama model must not be empty")
        if self.model is not None and self.model.endswith((":cloud", "-cloud")):
            raise ValueError(
                "Porter's local Ollama provider does not allow Ollama cloud models"
            )
        if self.timeout_seconds <= 0:
            raise ValueError("Ollama timeout_seconds must be positive")
        if self.keep_alive is not None and not self.keep_alive.strip():
            raise ValueError("Ollama keep_alive must not be empty when provided")

        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("Ollama base_url must use http or https")
        if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Ollama base_url must use a loopback host")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("Ollama base_url must not contain credentials")
        if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
            raise ValueError("Ollama base_url must not include a path, query, or fragment")


@dataclass(frozen=True, slots=True)
class OpenAIConfig:
    """Configuration for Porter's explicit OpenAI cloud fallback."""

    api_key: str | None = None
    model: str | None = None
    timeout_seconds: float = 120.0

    def __post_init__(self) -> None:
        if self.api_key is not None and not self.api_key.strip():
            raise ValueError("OpenAI API key must not be empty")
        if self.model is not None and not self.model.strip():
            raise ValueError("OpenAI model must not be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("OpenAI timeout_seconds must be positive")

    @property
    def configured(self) -> bool:
        return self.api_key is not None and self.model is not None


@dataclass(frozen=True, slots=True)
class WeatherConfig:
    """Optional weather-source credentials and local-observation search settings."""

    synoptic_token: str | None = None
    synoptic_radius_miles: float = 5.0
    synoptic_station_limit: int = 12
    synoptic_within_minutes: int = 30

    def __post_init__(self) -> None:
        if self.synoptic_token is not None and not self.synoptic_token.strip():
            raise ValueError("Synoptic token must not be empty")
        if self.synoptic_radius_miles <= 0:
            raise ValueError("Synoptic radius must be positive")
        if self.synoptic_station_limit < 2:
            raise ValueError("Synoptic station limit must be at least 2")
        if self.synoptic_within_minutes <= 0:
            raise ValueError("Synoptic freshness window must be positive")


@dataclass(frozen=True, slots=True)
class PorterConfig:
    """Validated application configuration."""

    storage: StorageConfig
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)
    weather: WeatherConfig = field(default_factory=WeatherConfig)
