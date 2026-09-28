from typing import Any

import pytest

from porter.config.models import OllamaConfig
from porter.core.exceptions import ProviderError
from porter.core.models import Message, RequestContext, RequestSource
from porter.providers.ollama import OllamaClientError, OllamaProvider
from porter.providers.registry import ProviderHealth


class FakeOllamaApi:
    def __init__(
        self,
        *,
        chat_response: dict[str, Any] | None = None,
        models_response: dict[str, Any] | None = None,
        chat_error: Exception | None = None,
        models_error: Exception | None = None,
    ) -> None:
        self.chat_response = chat_response or {
            "message": {"role": "assistant", "content": "local answer"}
        }
        self.models_response = models_response or {"models": []}
        self.chat_error = chat_error
        self.models_error = models_error
        self.chat_calls: list[dict[str, Any]] = []

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        keep_alive: str | None,
    ) -> dict[str, Any]:
        self.chat_calls.append(
            {
                "model": model,
                "messages": messages,
                "keep_alive": keep_alive,
            }
        )
        if self.chat_error is not None:
            raise self.chat_error
        return self.chat_response

    async def list_models(self) -> dict[str, Any]:
        if self.models_error is not None:
            raise self.models_error
        return self.models_response


def make_provider(
    client: FakeOllamaApi,
    *,
    model: str = "qwen3:8b",
    keep_alive: str | None = None,
) -> OllamaProvider:
    return OllamaProvider(
        OllamaConfig(model=model, keep_alive=keep_alive),
        client=client,
    )


@pytest.mark.asyncio
async def test_ollama_provider_translates_chat_request_and_response() -> None:
    client = FakeOllamaApi(
        chat_response={
            "message": {"role": "assistant", "content": "local answer"},
            "prompt_eval_count": 17,
            "eval_count": 5,
        }
    )
    provider = make_provider(client, keep_alive="2m")
    request = RequestContext(
        messages=(
            Message(role="system", content="Be concise."),
            Message(role="user", content="Hello"),
        ),
        principal_id="local-user",
        source=RequestSource.CLI,
    )

    result = await provider.generate(request)

    assert result.text == "local answer"
    assert result.provider == "ollama"
    assert result.model == "qwen3:8b"
    assert result.input_tokens == 17
    assert result.output_tokens == 5
    assert result.estimated_cost_microusd == 0
    assert client.chat_calls == [
        {
            "model": "qwen3:8b",
            "messages": [
                {"role": "system", "content": "Be concise."},
                {"role": "user", "content": "Hello"},
            ],
            "keep_alive": "2m",
        }
    ]


@pytest.mark.asyncio
async def test_ollama_provider_allows_missing_usage_metrics() -> None:
    provider = make_provider(FakeOllamaApi())
    request = RequestContext(
        messages=(Message(role="user", content="Hello"),),
        principal_id="local-user",
        source=RequestSource.CLI,
    )

    result = await provider.generate(request)

    assert result.input_tokens is None
    assert result.output_tokens is None
    assert result.estimated_cost_microusd == 0


@pytest.mark.asyncio
async def test_ollama_provider_translates_client_failure() -> None:
    provider = make_provider(
        FakeOllamaApi(chat_error=OllamaClientError("offline"))
    )

    request = RequestContext(
        messages=(Message(role="user", content="Hello"),),
        principal_id="local-user",
        source=RequestSource.CLI,
    )

    with pytest.raises(ProviderError, match="Ollama inference failed"):
        await provider.generate(request)


@pytest.mark.asyncio
async def test_ollama_provider_rejects_malformed_chat_response() -> None:
    provider = make_provider(FakeOllamaApi(chat_response={"message": {}}))
    request = RequestContext(
        messages=(Message(role="user", content="Hello"),),
        principal_id="local-user",
        source=RequestSource.CLI,
    )

    with pytest.raises(ProviderError, match="malformed"):
        await provider.generate(request)


@pytest.mark.asyncio
async def test_ollama_health_is_healthy_when_configured_model_exists() -> None:
    provider = make_provider(
        FakeOllamaApi(
            models_response={
                "models": [
                    {"name": "qwen3:8b", "model": "qwen3:8b"},
                ]
            }
        )
    )

    assert await provider.check_health() is ProviderHealth.HEALTHY


@pytest.mark.asyncio
async def test_ollama_health_accepts_latest_alias() -> None:
    provider = make_provider(
        FakeOllamaApi(
            models_response={"models": [{"name": "gemma3:latest"}]}
        ),
        model="gemma3",
    )

    assert await provider.check_health() is ProviderHealth.HEALTHY


@pytest.mark.asyncio
async def test_ollama_health_is_unavailable_when_model_is_missing() -> None:
    provider = make_provider(
        FakeOllamaApi(models_response={"models": [{"name": "other:latest"}]})
    )

    assert await provider.check_health() is ProviderHealth.UNAVAILABLE


@pytest.mark.asyncio
async def test_ollama_health_is_unavailable_when_api_is_offline() -> None:
    provider = make_provider(
        FakeOllamaApi(models_error=OllamaClientError("offline"))
    )

    assert await provider.check_health() is ProviderHealth.UNAVAILABLE


def test_ollama_provider_requires_configured_model() -> None:
    with pytest.raises(ValueError, match="model must be configured"):
        OllamaProvider(OllamaConfig())


class FakeHttpResponse:
    def __init__(self, body: str) -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return self._body.encode("utf-8")


@pytest.mark.asyncio
async def test_ollama_client_posts_chat_payload(monkeypatch) -> None:
    from porter.providers.ollama import OllamaClient

    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["timeout"] = timeout
        captured["body"] = request.data.decode("utf-8")
        return FakeHttpResponse(
            '{"message":{"role":"assistant","content":"ok"}}'
        )

    monkeypatch.setattr(
        "porter.net.http.urlopen",
        fake_urlopen,
    )

    client = OllamaClient(
        OllamaConfig(
            model="qwen3:8b",
            timeout_seconds=12.5,
        )
    )

    result = await client.chat(
        model="qwen3:8b",
        messages=[{"role": "user", "content": "hello"}],
        keep_alive="2m",
    )

    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    assert captured["method"] == "POST"
    assert captured["timeout"] == 12.5

    payload = __import__("json").loads(captured["body"])
    assert payload == {
        "model": "qwen3:8b",
        "messages": [{"role": "user", "content": "hello"}],
        "stream": False,
        "keep_alive": "2m",
    }

    assert result["message"]["content"] == "ok"


@pytest.mark.asyncio
async def test_ollama_client_gets_model_list(monkeypatch) -> None:
    from porter.providers.ollama import OllamaClient

    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["timeout"] = timeout
        return FakeHttpResponse(
            '{"models":[{"name":"qwen3:8b"}]}'
        )

    monkeypatch.setattr(
        "porter.net.http.urlopen",
        fake_urlopen,
    )

    client = OllamaClient(
        OllamaConfig(
            model="qwen3:8b",
            timeout_seconds=4.0,
        )
    )

    result = await client.list_models()

    assert captured["url"] == "http://127.0.0.1:11434/api/tags"
    assert captured["method"] == "GET"
    assert captured["timeout"] == 4.0
    assert result == {"models": [{"name": "qwen3:8b"}]}


@pytest.mark.asyncio
async def test_ollama_client_rejects_invalid_json(monkeypatch) -> None:
    from porter.providers.ollama import OllamaClient

    monkeypatch.setattr(
        "porter.net.http.urlopen",
        lambda request, timeout: FakeHttpResponse("not-json"),
    )

    client = OllamaClient(OllamaConfig(model="qwen3:8b"))

    with pytest.raises(OllamaClientError, match="invalid JSON"):
        await client.list_models()


@pytest.mark.asyncio
async def test_ollama_client_translates_network_failure(monkeypatch) -> None:
    from urllib.error import URLError

    from porter.providers.ollama import OllamaClient

    def fail_urlopen(request, timeout):
        raise URLError("offline")

    monkeypatch.setattr(
        "porter.net.http.urlopen",
        fail_urlopen,
    )

    client = OllamaClient(OllamaConfig(model="qwen3:8b"))

    with pytest.raises(OllamaClientError, match="request failed"):
        await client.list_models()
