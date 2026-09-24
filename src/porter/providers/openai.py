from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from porter.config.models import OpenAIConfig
from porter.core.exceptions import ProviderError
from porter.core.models import Capability, InferenceResult, RequestContext
from porter.net import JsonHttpError, JsonHttpTransport
from porter.providers.base import InferenceProvider

_RESPONSES_URL = "https://api.openai.com/v1/responses"


class OpenAIClientError(Exception):
    """Raised when the OpenAI API cannot satisfy a request."""


class OpenAIApi(Protocol):
    async def create_response(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
    ) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class _TokenPricing:
    input_per_million_microusd: int
    cached_input_per_million_microusd: int
    output_per_million_microusd: int


_PRICING = {
    "gpt-5.4-mini": _TokenPricing(
        input_per_million_microusd=750_000,
        cached_input_per_million_microusd=75_000,
        output_per_million_microusd=4_500_000,
    ),
    "gpt-5.4-nano": _TokenPricing(
        input_per_million_microusd=200_000,
        cached_input_per_million_microusd=20_000,
        output_per_million_microusd=1_250_000,
    ),
}


class OpenAIClient:
    """Minimal Responses API client using Porter's shared HTTP transport."""

    def __init__(self, config: OpenAIConfig) -> None:
        if config.api_key is None:
            raise ValueError("OpenAI API key must be configured")
        self._api_key = config.api_key
        self._transport = JsonHttpTransport(timeout_seconds=config.timeout_seconds)

    async def create_response(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
    ) -> dict[str, Any]:
        try:
            return await self._transport.request_json(
                _RESPONSES_URL,
                method="POST",
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self._api_key}",
                },
                payload={
                    "model": model,
                    "input": messages,
                    "store": False,
                },
            )
        except JsonHttpError as exc:
            raise OpenAIClientError(f"OpenAI {exc}") from exc


class OpenAIProvider(InferenceProvider):
    """Explicitly configured cloud text-inference adapter."""

    name = "openai"
    is_cloud = True
    capabilities = frozenset({Capability.TEXT})

    def __init__(
        self,
        config: OpenAIConfig,
        *,
        client: OpenAIApi | None = None,
    ) -> None:
        if config.model is None:
            raise ValueError("OpenAI model must be configured")
        if config.api_key is None:
            raise ValueError("OpenAI API key must be configured")

        self.model = config.model
        self._client = client or OpenAIClient(config)

    async def generate(self, request: RequestContext) -> InferenceResult:
        messages = [
            {"role": message.role, "content": message.content}
            for message in request.messages
        ]

        try:
            response = await self._client.create_response(
                model=self.model,
                messages=messages,
            )
        except OpenAIClientError as exc:
            raise ProviderError("OpenAI inference failed") from exc

        text = self._output_text(response)
        input_tokens, output_tokens, cached_tokens = self._usage(response)

        return InferenceResult(
            text=text,
            provider=self.name,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_microusd=self._estimated_cost_microusd(
                model=self.model,
                input_tokens=input_tokens,
                cached_input_tokens=cached_tokens,
                output_tokens=output_tokens,
            ),
        )

    @staticmethod
    def _output_text(response: dict[str, Any]) -> str:
        output = response.get("output")
        if not isinstance(output, list):
            raise ProviderError("OpenAI returned a malformed response")

        parts: list[str] = []
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict) or part.get("type") != "output_text":
                    continue
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)

        combined = "".join(parts).strip()
        if not combined:
            raise ProviderError("OpenAI returned no text output")
        return combined

    @staticmethod
    def _usage(response: dict[str, Any]) -> tuple[int | None, int | None, int]:
        usage = response.get("usage")
        if not isinstance(usage, dict):
            return None, None, 0

        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        input_details = usage.get("input_tokens_details")
        cached_tokens = 0
        if isinstance(input_details, dict):
            candidate = input_details.get("cached_tokens")
            if isinstance(candidate, int) and candidate >= 0:
                cached_tokens = candidate

        return (
            input_tokens if isinstance(input_tokens, int) and input_tokens >= 0 else None,
            output_tokens if isinstance(output_tokens, int) and output_tokens >= 0 else None,
            cached_tokens,
        )

    @staticmethod
    def _estimated_cost_microusd(
        *,
        model: str,
        input_tokens: int | None,
        cached_input_tokens: int,
        output_tokens: int | None,
    ) -> int | None:
        if input_tokens is None or output_tokens is None:
            return None

        pricing = OpenAIProvider._pricing_for_model(model)
        if pricing is None:
            return None

        cached = min(max(cached_input_tokens, 0), input_tokens)
        uncached = input_tokens - cached
        numerator = (
            uncached * pricing.input_per_million_microusd
            + cached * pricing.cached_input_per_million_microusd
            + output_tokens * pricing.output_per_million_microusd
        )
        return (numerator + 500_000) // 1_000_000

    @staticmethod
    def _pricing_for_model(model: str) -> _TokenPricing | None:
        if model in _PRICING:
            return _PRICING[model]
        for alias, pricing in _PRICING.items():
            if model.startswith(f"{alias}-"):
                return pricing
        return None


__all__ = ["OpenAIClient", "OpenAIClientError", "OpenAIProvider"]
