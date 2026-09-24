from __future__ import annotations

from typing import Any, Protocol

from porter.config.models import OllamaConfig
from porter.core.exceptions import ProviderError
from porter.core.models import Capability, InferenceResult, RequestContext
from porter.net import JsonHttpError, JsonHttpTransport
from porter.providers.base import InferenceProvider
from porter.providers.registry import ProviderHealth


class OllamaClientError(Exception):
    """Raised when the local Ollama API cannot satisfy a request."""


class OllamaApi(Protocol):
    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        keep_alive: str | None,
    ) -> dict[str, Any]: ...

    async def list_models(self) -> dict[str, Any]: ...


class OllamaClient:
    """Minimal async facade over Ollama's local HTTP API."""

    def __init__(self, config: OllamaConfig) -> None:
        self._base_url = config.base_url.rstrip("/")
        self._transport = JsonHttpTransport(
            timeout_seconds=config.timeout_seconds
        )

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        keep_alive: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive

        return await self._request_json(
            "POST",
            "/api/chat",
            payload,
        )

    async def list_models(self) -> dict[str, Any]:
        return await self._request_json(
            "GET",
            "/api/tags",
            None,
        )

    async def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        try:
            return await self._transport.request_json(
                f"{self._base_url}{path}",
                method=method,
                headers={"Accept": "application/json"},
                payload=payload,
            )
        except JsonHttpError as exc:
            raise OllamaClientError(f"Ollama {exc}") from exc


class OllamaProvider(InferenceProvider):
    """Text inference adapter for a loopback Ollama server."""

    name = "ollama"
    is_cloud = False
    capabilities = frozenset({Capability.TEXT})

    def __init__(
        self,
        config: OllamaConfig,
        *,
        client: OllamaApi | None = None,
    ) -> None:
        if config.model is None:
            raise ValueError("Ollama model must be configured")

        self.model = config.model
        self._keep_alive = config.keep_alive
        self._client = client or OllamaClient(config)

    async def generate(self, request: RequestContext) -> InferenceResult:
        messages = [
            {"role": message.role, "content": message.content}
            for message in request.messages
        ]

        try:
            response = await self._client.chat(
                model=self.model,
                messages=messages,
                keep_alive=self._keep_alive,
            )
        except OllamaClientError as exc:
            raise ProviderError("Ollama inference failed") from exc

        message = response.get("message")
        if not isinstance(message, dict):
            raise ProviderError("Ollama returned a malformed chat response")

        content = message.get("content")
        if not isinstance(content, str):
            raise ProviderError("Ollama returned a malformed chat response")

        input_tokens = response.get("prompt_eval_count")
        output_tokens = response.get("eval_count")

        return InferenceResult(
            text=content,
            provider=self.name,
            model=self.model,
            input_tokens=input_tokens if isinstance(input_tokens, int) else None,
            output_tokens=output_tokens if isinstance(output_tokens, int) else None,
            estimated_cost_microusd=0,
        )

    async def check_health(self) -> ProviderHealth:
        try:
            response = await self._client.list_models()
        except OllamaClientError:
            return ProviderHealth.UNAVAILABLE

        models = response.get("models")
        if not isinstance(models, list):
            return ProviderHealth.UNAVAILABLE

        configured = self._normalize_model(self.model)
        for entry in models:
            if not isinstance(entry, dict):
                continue
            for key in ("name", "model"):
                candidate = entry.get(key)
                if isinstance(candidate, str) and self._normalize_model(candidate) == configured:
                    return ProviderHealth.HEALTHY

        return ProviderHealth.UNAVAILABLE

    @staticmethod
    def _normalize_model(model: str) -> str:
        return model.removesuffix(":latest")
