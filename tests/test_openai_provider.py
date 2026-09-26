from typing import Any

import pytest

from porter.config.models import OpenAIConfig
from porter.core.exceptions import ProviderError
from porter.core.models import Message, RequestContext, RequestSource
from porter.providers.openai import OpenAIClient, OpenAIProvider


class FakeOpenAIApi:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    async def create_response(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
    ) -> dict[str, Any]:
        self.calls.append({"model": model, "messages": messages})
        return self.response


def _request() -> RequestContext:
    return RequestContext(
        messages=(Message(role="user", content="Hello"),),
        principal_id="local-user",
        source=RequestSource.CLI,
    )


@pytest.mark.asyncio
async def test_openai_provider_parses_text_usage_and_cost() -> None:
    client = FakeOpenAIApi(
        {
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "cloud answer"}],
                }
            ],
            "usage": {
                "input_tokens": 100,
                "input_tokens_details": {"cached_tokens": 40},
                "output_tokens": 20,
            },
        }
    )
    provider = OpenAIProvider(
        OpenAIConfig(api_key="secret", model="gpt-5.4-mini"),
        client=client,
    )

    result = await provider.generate(_request())

    assert result.text == "cloud answer"
    assert result.provider == "openai"
    assert result.model == "gpt-5.4-mini"
    assert result.input_tokens == 100
    assert result.output_tokens == 20
    assert result.estimated_cost_microusd == 138
    assert client.calls == [
        {
            "model": "gpt-5.4-mini",
            "messages": [{"role": "user", "content": "Hello"}],
        }
    ]


@pytest.mark.asyncio
async def test_openai_provider_unknown_model_leaves_cost_unknown() -> None:
    client = FakeOpenAIApi(
        {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "answer"}],
                }
            ],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
    )
    provider = OpenAIProvider(
        OpenAIConfig(api_key="secret", model="future-model"),
        client=client,
    )

    result = await provider.generate(_request())

    assert result.estimated_cost_microusd is None


@pytest.mark.asyncio
async def test_openai_provider_rejects_missing_text_output() -> None:
    provider = OpenAIProvider(
        OpenAIConfig(api_key="secret", model="gpt-5.4-mini"),
        client=FakeOpenAIApi({"output": []}),
    )

    with pytest.raises(ProviderError, match="no text output"):
        await provider.generate(_request())


@pytest.mark.asyncio
async def test_openai_client_uses_responses_api_without_storage(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_request_json(url, *, method, headers, payload):
        captured.update(
            {"url": url, "method": method, "headers": headers, "payload": payload}
        )
        return {"output": []}

    client = OpenAIClient(OpenAIConfig(api_key="top-secret", model="gpt-5.4-mini"))
    monkeypatch.setattr(client._transport, "request_json", fake_request_json)

    await client.create_response(
        model="gpt-5.4-mini",
        messages=[{"role": "user", "content": "Hello"}],
    )

    assert captured["url"] == "https://api.openai.com/v1/responses"
    assert captured["method"] == "POST"
    assert captured["headers"] == {
        "Accept": "application/json",
        "Authorization": "Bearer top-secret",
    }
    assert captured["payload"] == {
        "model": "gpt-5.4-mini",
        "input": [{"role": "user", "content": "Hello"}],
        "store": False,
    }
