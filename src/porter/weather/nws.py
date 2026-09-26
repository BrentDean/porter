from __future__ import annotations

from typing import Any, Protocol

from porter.net import JsonHttpError, JsonHttpTransport
from porter.weather.errors import WeatherSourceError
from porter.weather.geo import validate_coordinates
from porter.weather.models import WeatherForecast, WeatherPeriod


class NwsClientError(WeatherSourceError):
    """Raised when the NWS API cannot satisfy a request."""


class NwsApi(Protocol):
    async def get_json(self, url: str) -> dict[str, Any]: ...


class NwsClient:
    """Minimal async facade over api.weather.gov."""

    def __init__(
        self,
        *,
        base_url: str = "https://api.weather.gov",
        user_agent: str = "porter-ai/0.1",
        timeout_seconds: float = 10.0,
    ) -> None:
        if not user_agent.strip():
            raise ValueError("NWS user_agent must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("NWS timeout_seconds must be positive")
        self._base_url = base_url.rstrip("/")
        self._user_agent = user_agent
        self._transport = JsonHttpTransport(timeout_seconds=timeout_seconds)

    async def get_json(self, url: str) -> dict[str, Any]:
        try:
            return await self._transport.request_json(
                url,
                headers={
                    "Accept": "application/geo+json",
                    "User-Agent": self._user_agent,
                },
            )
        except JsonHttpError as exc:
            raise NwsClientError(f"NWS {exc}") from exc


class NwsWeatherProvider:
    source = "nws"

    def __init__(
        self,
        *,
        client: NwsApi | None = None,
        base_url: str = "https://api.weather.gov",
        user_agent: str = "porter-ai/0.1",
        timeout_seconds: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or NwsClient(
            base_url=base_url,
            user_agent=user_agent,
            timeout_seconds=timeout_seconds,
        )

    async def forecast(
        self,
        *,
        latitude: float,
        longitude: float,
    ) -> WeatherForecast:
        validate_coordinates(latitude, longitude)
        points = await self._client.get_json(
            f"{self._base_url}/points/{latitude},{longitude}"
        )
        point_properties = self._properties(points)
        forecast_url = point_properties.get("forecast")
        if not isinstance(forecast_url, str):
            raise NwsClientError(
                "NWS point response is missing forecast URL"
            )
        forecast = await self._client.get_json(forecast_url)
        forecast_properties = self._properties(forecast)
        raw_periods = forecast_properties.get("periods")
        if not isinstance(raw_periods, list):
            raise NwsClientError(
                "NWS forecast response is missing periods"
            )
        periods = tuple(
            self._parse_period(period)
            for period in raw_periods
            if isinstance(period, dict)
        )
        if not periods:
            raise NwsClientError(
                "NWS forecast response contains no periods"
            )
        narrative = next(
            (
                period.detailed_forecast
                for period in periods
                if period.detailed_forecast
            ),
            None,
        )
        return WeatherForecast(
            latitude=latitude,
            longitude=longitude,
            source=self.source,
            periods=periods,
            narrative=narrative,
        )

    @staticmethod
    def _properties(payload: dict[str, Any]) -> dict[str, Any]:
        properties = payload.get("properties")
        if not isinstance(properties, dict):
            raise NwsClientError("NWS returned malformed properties")
        return properties

    @classmethod
    def _parse_period(cls, period: dict[str, Any]) -> WeatherPeriod:
        return WeatherPeriod(
            name=cls._string(period.get("name")) or "",
            start_time=cls._string(period.get("startTime")) or "",
            end_time=cls._string(period.get("endTime")) or "",
            is_daytime=period.get("isDaytime") is True,
            temperature_f=cls._temperature_f(period),
            precipitation_probability=(
                cls._precipitation_probability(period)
            ),
            wind_speed=cls._string(period.get("windSpeed")),
            short_forecast=cls._string(
                period.get("shortForecast")
            ),
            detailed_forecast=cls._string(
                period.get("detailedForecast")
            ),
        )

    @staticmethod
    def _temperature_f(period: dict[str, Any]) -> float | None:
        value = period.get("temperature")
        if not isinstance(value, int | float):
            return None
        unit = period.get("temperatureUnit")
        if unit == "F":
            return float(value)
        if unit == "C":
            return (float(value) * 9 / 5) + 32
        return None

    @staticmethod
    def _precipitation_probability(
        period: dict[str, Any],
    ) -> float | None:
        probability = period.get("probabilityOfPrecipitation")
        if not isinstance(probability, dict):
            return None
        value = probability.get("value")
        if not isinstance(value, int | float):
            return None
        return float(value)

    @staticmethod
    def _string(value: object) -> str | None:
        if isinstance(value, str) and value:
            return value
        return None
