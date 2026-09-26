from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class JsonHttpError(Exception):
    """Raised when a JSON HTTP request fails at the transport boundary."""


class JsonHttpTransport:
    """Small stdlib JSON-over-HTTP transport shared by Porter adapters."""

    def __init__(self, *, timeout_seconds: float = 10.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._timeout_seconds = timeout_seconds

    async def request_json(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: Mapping[str, str] | None = None,
        payload: object | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._request_json,
            url,
            method,
            headers,
            payload,
        )

    def _request_json(
        self,
        url: str,
        method: str,
        headers: Mapping[str, str] | None,
        payload: object | None,
    ) -> dict[str, Any]:
        request_headers = dict(headers or {})
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")

        request = Request(
            url,
            data=data,
            headers=request_headers,
            method=method,
        )

        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            raise JsonHttpError(f"HTTP error: {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise JsonHttpError("request failed") from exc

        try:
            decoded = json.loads(body)
        except json.JSONDecodeError as exc:
            raise JsonHttpError("returned invalid JSON") from exc

        if not isinstance(decoded, dict):
            raise JsonHttpError("returned an invalid response")
        return decoded


# Keep monkeypatch paths such as ``porter.net.http.urlopen`` working while
# ``porter.net`` is a single module rather than a package.
http = sys.modules[__name__]

__all__ = ["JsonHttpError", "JsonHttpTransport"]
