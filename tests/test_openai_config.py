from pathlib import Path

from porter.app.bootstrap import build_application
from porter.cli.commands.ask import _build_request
from porter.config.loader import ConfigLoader
from porter.config.store import ConfigStore
from porter.core.models import PrivacyClass


def test_openai_is_disabled_by_default(tmp_path: Path) -> None:
    config = ConfigLoader(env={}, home=tmp_path).load()

    assert config.openai.api_key is None
    assert config.openai.model is None
    assert not config.openai.configured


def test_openai_config_loads_key_model_and_timeout(tmp_path: Path) -> None:
    config = ConfigLoader(
        env={
            "OPENAI_API_KEY": "secret-key",
            "PORTER_OPENAI_MODEL": "gpt-5.4-mini",
            "PORTER_OPENAI_TIMEOUT_SECONDS": "30",
        },
        home=tmp_path,
    ).load()

    assert config.openai.api_key == "secret-key"
    assert config.openai.model == "gpt-5.4-mini"
    assert config.openai.timeout_seconds == 30.0
    assert config.openai.configured


def test_openai_model_can_be_stored_without_api_key(tmp_path: Path) -> None:
    store = ConfigStore(env={}, home=tmp_path)
    store.set_openai_model("gpt-5.4-mini")

    config = ConfigLoader(env={}, home=tmp_path).load()

    assert store.path.stat().st_mode & 0o777 == 0o600
    assert config.openai.model == "gpt-5.4-mini"
    assert config.openai.api_key is None
    assert not config.openai.configured


def test_application_registers_openai_only_when_fully_configured(tmp_path: Path) -> None:
    without_key = build_application(
        env={
            "PORTER_DATA_DIR": str(tmp_path / "without-key"),
            "PORTER_OPENAI_MODEL": "gpt-5.4-mini",
        },
        home=tmp_path,
    )
    with_key = build_application(
        env={
            "PORTER_DATA_DIR": str(tmp_path / "with-key"),
            "PORTER_OPENAI_MODEL": "gpt-5.4-mini",
            "OPENAI_API_KEY": "secret-key",
        },
        home=tmp_path,
    )

    assert "openai" not in {provider.name for provider in without_key.provider_registry.all()}
    assert "openai" in {provider.name for provider in with_key.provider_registry.all()}


def test_cli_requests_remain_local_only_without_explicit_cloud_flag() -> None:
    request = _build_request("question")

    assert request.privacy_class is PrivacyClass.LOCAL_ONLY
    assert not request.allow_cloud


def test_cli_allow_cloud_is_explicit_per_request() -> None:
    request = _build_request("question", allow_cloud=True)

    assert request.privacy_class is PrivacyClass.CLOUD_ALLOWED
    assert request.allow_cloud
