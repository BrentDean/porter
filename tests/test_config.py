from pathlib import Path

import pytest

from porter.config.loader import ConfigLoader


def test_config_uses_local_user_data_directory_by_default(tmp_path: Path) -> None:
    config = ConfigLoader(env={}, home=tmp_path).load()

    expected_data_dir = tmp_path / ".local" / "share" / "porter"
    assert config.storage.data_dir == expected_data_dir
    assert config.storage.database_path == expected_data_dir / "porter.db"
    assert config.ollama.model is None
    assert config.ollama.base_url == "http://127.0.0.1:11434"
    assert config.weather.synoptic_token is None
    assert config.weather.synoptic_radius_miles == 5.0
    assert config.weather.synoptic_station_limit == 12
    assert config.weather.synoptic_within_minutes == 30


def test_config_honors_storage_environment_overrides(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    database_path = tmp_path / "db" / "custom.sqlite"

    config = ConfigLoader(
        env={
            "PORTER_DATA_DIR": str(data_dir),
            "PORTER_DB_PATH": str(database_path),
        },
        home=tmp_path,
    ).load()

    assert config.storage.data_dir == data_dir
    assert config.storage.database_path == database_path


def test_storage_config_ignores_unrelated_invalid_settings(tmp_path: Path) -> None:
    database_path = tmp_path / "service.db"
    storage = ConfigLoader(
        env={
            "PORTER_DB_PATH": str(database_path),
            "PORTER_OLLAMA_TIMEOUT_SECONDS": "never",
            "PORTER_SYNOPIC_STATION_LIMIT": "1",
        },
        home=tmp_path,
    ).load_storage()

    assert storage.database_path == database_path
    assert storage.data_dir == tmp_path / ".local" / "share" / "porter"


def test_config_honors_xdg_data_home(tmp_path: Path) -> None:
    config = ConfigLoader(
        env={"XDG_DATA_HOME": str(tmp_path / "xdg")},
        home=tmp_path,
    ).load()

    assert config.storage.data_dir == tmp_path / "xdg" / "porter"


def test_config_loads_ollama_settings(tmp_path: Path) -> None:
    config = ConfigLoader(
        env={
            "PORTER_OLLAMA_MODEL": "qwen3:8b",
            "PORTER_OLLAMA_URL": "http://localhost:11434",
            "PORTER_OLLAMA_TIMEOUT_SECONDS": "12.5",
            "PORTER_OLLAMA_KEEP_ALIVE": "2m",
        },
        home=tmp_path,
    ).load()

    assert config.ollama.model == "qwen3:8b"
    assert config.ollama.base_url == "http://localhost:11434"
    assert config.ollama.timeout_seconds == 12.5
    assert config.ollama.keep_alive == "2m"


def test_config_loads_synoptic_weather_settings(tmp_path: Path) -> None:
    config = ConfigLoader(
        env={
            "PORTER_SYNOPIC_TOKEN": "public-token",
            "PORTER_SYNOPIC_RADIUS_MILES": "4.5",
            "PORTER_SYNOPIC_STATION_LIMIT": "10",
            "PORTER_SYNOPIC_WITHIN_MINUTES": "20",
        },
        home=tmp_path,
    ).load()

    assert config.weather.synoptic_token == "public-token"
    assert config.weather.synoptic_radius_miles == 4.5
    assert config.weather.synoptic_station_limit == 10
    assert config.weather.synoptic_within_minutes == 20


def test_config_rejects_non_loopback_ollama_url(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="loopback"):
        ConfigLoader(
            env={
                "PORTER_OLLAMA_MODEL": "qwen3:8b",
                "PORTER_OLLAMA_URL": "https://ollama.com",
            },
            home=tmp_path,
        ).load()


def test_config_rejects_invalid_ollama_timeout(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="PORTER_OLLAMA_TIMEOUT_SECONDS"):
        ConfigLoader(
            env={"PORTER_OLLAMA_TIMEOUT_SECONDS": "never"},
            home=tmp_path,
        ).load()


def test_config_rejects_ollama_cloud_model(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cloud models"):
        ConfigLoader(
            env={
                "PORTER_OLLAMA_MODEL": "gpt-oss:120b-cloud",
            },
            home=tmp_path,
        ).load()


def test_config_rejects_invalid_synoptic_station_limit(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="station limit"):
        ConfigLoader(
            env={"PORTER_SYNOPIC_STATION_LIMIT": "1"},
            home=tmp_path,
        ).load()
