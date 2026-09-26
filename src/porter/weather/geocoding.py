from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode

from porter.net import JsonHttpError, JsonHttpTransport


class GeocodingError(Exception):
    """Raised when a weather location cannot be resolved."""


@dataclass(frozen=True, slots=True)
class GeocodedLocation:
    name: str
    latitude: float
    longitude: float
    country_code: str
    admin1: str | None = None
    timezone: str | None = None

    @property
    def display_name(self) -> str:
        if self.admin1:
            return f"{self.name}, {self.admin1}"
        return self.name


class GeocodingApi(Protocol):
    async def get_json(self, url: str) -> dict[str, Any]: ...


class OpenMeteoGeocodingClient:
    def __init__(
        self,
        *,
        base_url: str = "https://geocoding-api.open-meteo.com/v1/search",
        timeout_seconds: float = 10.0,
        country_code: str | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("geocoding timeout_seconds must be positive")
        self._base_url = base_url
        self._transport = JsonHttpTransport(timeout_seconds=timeout_seconds)
        self._country_code = self._normalize_country_code(country_code)

    @staticmethod
    def _normalize_country_code(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if len(normalized) != 2 or not normalized.isalpha():
            raise ValueError("geocoding country_code must be a two-letter code")
        return normalized

    def search_url(self, query: str) -> str:
        params: dict[str, object] = {
            "name": query,
            "count": 1,
            "language": "en",
            "format": "json",
        }
        if self._country_code is not None:
            params["countryCode"] = self._country_code
        return f"{self._base_url}?{urlencode(params)}"

    async def get_json(self, url: str) -> dict[str, Any]:
        try:
            return await self._transport.request_json(
                url,
                headers={"Accept": "application/json"},
            )
        except JsonHttpError as exc:
            raise GeocodingError(f"geocoding {exc}") from exc


class OpenMeteoGeocoder:
    def __init__(
        self,
        *,
        client: GeocodingApi | None = None,
        country_code: str | None = None,
    ) -> None:
        self._client_impl = OpenMeteoGeocodingClient(
            country_code=country_code
        )
        self._client = client or self._client_impl

    async def resolve(self, query: str) -> GeocodedLocation:
        normalized = query.strip()
        if len(normalized) < 2:
            raise GeocodingError("weather location is too short")

        payload = await self._client.get_json(
            self._client_impl.search_url(normalized)
        )
        results = payload.get("results")
        if not isinstance(results, list) or not results:
            raise GeocodingError(f"weather location not found: {normalized}")

        result = results[0]
        if not isinstance(result, dict):
            raise GeocodingError("geocoding returned malformed location")

        name = result.get("name")
        latitude = result.get("latitude")
        longitude = result.get("longitude")
        country_code = result.get("country_code")
        admin1 = result.get("admin1")
        timezone = result.get("timezone")

        if not isinstance(name, str):
            raise GeocodingError("geocoding location is missing name")
        if not isinstance(latitude, int | float):
            raise GeocodingError("geocoding location is missing latitude")
        if not isinstance(longitude, int | float):
            raise GeocodingError("geocoding location is missing longitude")
        if not isinstance(country_code, str):
            raise GeocodingError("geocoding location is missing country code")

        return GeocodedLocation(
            name=name,
            latitude=float(latitude),
            longitude=float(longitude),
            country_code=country_code,
            admin1=admin1 if isinstance(admin1, str) else None,
            timezone=timezone if isinstance(timezone, str) else None,
        )
