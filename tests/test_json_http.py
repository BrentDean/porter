from __future__ import annotations

from urllib.error import HTTPError

import pytest

from porter.net import JsonHttpError, JsonHttpTransport


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


@pytest.mark.asyncio
async def test_json_http_transport_returns_object_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        "porter.net.http.urlopen",
        lambda request, timeout: FakeResponse(b'{"ok": true}'),
    )

    result = await JsonHttpTransport(timeout_seconds=1).request_json(
        "https://example.test/data"
    )

    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_json_http_transport_rejects_non_object_json(monkeypatch) -> None:
    monkeypatch.setattr(
        "porter.net.http.urlopen",
        lambda request, timeout: FakeResponse(b"[]"),
    )

    with pytest.raises(JsonHttpError, match="invalid response"):
        await JsonHttpTransport(timeout_seconds=1).request_json(
            "https://example.test/data"
        )


@pytest.mark.asyncio
async def test_json_http_transport_preserves_http_status(monkeypatch) -> None:
    def fail(request: object, timeout: float) -> object:
        raise HTTPError(
            "https://example.test/data",
            503,
            "unavailable",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr("porter.net.http.urlopen", fail)

    with pytest.raises(JsonHttpError, match="HTTP error: 503"):
        await JsonHttpTransport(timeout_seconds=1).request_json(
            "https://example.test/data"
        )
