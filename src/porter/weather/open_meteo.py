from __future__ import annotations

from typing import Any, Protocol
from urllib.parse import urlencode

from porter.net import JsonHttpError, JsonHttpTransport
from porter.weather.errors import WeatherSourceError
from porter.weather.geo import validate_coordinates
from porter.weather.models import WeatherForecast, WeatherPeriod
from porter.weather.wmo import condition_from_wmo_code


class OpenMeteoClientError(WeatherSourceError):
    """Raised when Open-Meteo cannot satisfy a request."""


class OpenMeteoApi(Protocol):
    async def get_json(self, url: str) -> dict[str, Any]: ...


class OpenMeteoClient:
    """Minimal async facade over the Open-Meteo forecast API."""

    def __init__(
        self,
        *,
        base_url: str = "https://api.open-meteo.com/v1/forecast",
        timeout_seconds: float = 10.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Open-Meteo timeout_seconds must be positive")

        self._base_url = base_url
        self._transport = JsonHttpTransport(timeout_seconds=timeout_seconds)

    def forecast_url(
        self,
        *,
        latitude: float,
        longitude: float,
    ) -> str:
        query = urlencode(
            {
                "latitude": latitude,
                "longitude": longitude,
                "daily": ",".join(
                    (
                        "temperature_2m_max",
                        "temperature_2m_min",
                        "precipitation_probability_max",
                        "weather_code",
                        "wind_speed_10m_max",
                    )
                ),
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "timezone": "auto",
                "forecast_days": 7,
            }
        )
        return f"{self._base_url}?{query}"

    async def get_json(self, url: str) -> dict[str, Any]:
        try:
            return await self._transport.request_json(
                url,
                headers={"Accept": "application/json"},
            )
        except JsonHttpError as exc:
            raise OpenMeteoClientError(f"Open-Meteo {exc}") from exc


class OpenMeteoWeatherProvider:
    source = "open-meteo"

    def __init__(
        self,
        *,
        client: OpenMeteoApi | None = None,
        base_url: str = "https://api.open-meteo.com/v1/forecast",
        timeout_seconds: float = 10.0,
    ) -> None:
        self._client_impl = OpenMeteoClient(
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )
        self._client = client or self._client_impl

    async def forecast(
        self,
        *,
        latitude: float,
        longitude: float,
    ) -> WeatherForecast:
        validate_coordinates(latitude, longitude)
        url = self._client_impl.forecast_url(
            latitude=latitude,
            longitude=longitude,
        )
        payload = await self._client.get_json(url)
        daily = payload.get("daily")
        if not isinstance(daily, dict):
            raise OpenMeteoClientError(
                "Open-Meteo response is missing daily forecast"
            )

        times = self._list(daily, "time")
        highs = self._list(daily, "temperature_2m_max")
        lows = self._list(daily, "temperature_2m_min")
        precip = self._list(
            daily,
            "precipitation_probability_max",
        )
        codes = self._list(daily, "weather_code")
        winds = self._list(daily, "wind_speed_10m_max")

        lengths = {
            len(times),
            len(highs),
            len(lows),
            len(precip),
            len(codes),
            len(winds),
        }
        if len(lengths) != 1 or not times:
            raise OpenMeteoClientError(
                "Open-Meteo daily forecast arrays are inconsistent"
            )

        periods = tuple(
            WeatherPeriod(
                name=str(day),
                start_time=str(day),
                end_time=str(day),
                is_daytime=True,
                temperature_f=None,
                temperature_high_f=self._number(high),
                temperature_low_f=self._number(low),
                precipitation_probability=self._number(probability),
                wind_speed=self._wind(wind),
                short_forecast=self._condition(code),
                detailed_forecast=self._daily_summary(
                    high,
                    low,
                    probability,
                    code,
                    wind,
                ),
            )
            for day, high, low, probability, code, wind in zip(
                times,
                highs,
                lows,
                precip,
                codes,
                winds,
                strict=True,
            )
        )

        return WeatherForecast(
            latitude=latitude,
            longitude=longitude,
            source=self.source,
            periods=periods,
            narrative=periods[0].detailed_forecast,
        )

    @staticmethod
    def _list(
        daily: dict[str, Any],
        key: str,
    ) -> list[Any]:
        value = daily.get(key)
        if not isinstance(value, list):
            raise OpenMeteoClientError(
                f"Open-Meteo daily forecast is missing {key}"
            )
        return value

    @staticmethod
    def _number(value: object) -> float | None:
        if isinstance(value, int | float):
            return float(value)
        return None

    @classmethod
    def _wind(cls, value: object) -> str | None:
        number = cls._number(value)
        if number is None:
            return None
        return f"{number:g} mph"

    @classmethod
    def _daily_summary(
        cls,
        high: object,
        low: object,
        probability: object,
        code: object,
        wind: object,
    ) -> str:
        parts = [cls._condition(code)]
        high_value = cls._number(high)
        low_value = cls._number(low)
        precip_value = cls._number(probability)
        wind_value = cls._number(wind)

        if high_value is not None and low_value is not None:
            parts.append(
                f"high {high_value:g}°F, low {low_value:g}°F"
            )
        if precip_value is not None:
            parts.append(f"rain chance {precip_value:g}%")
        if wind_value is not None:
            parts.append(f"wind up to {wind_value:g} mph")

        return "; ".join(part for part in parts if part)

    @staticmethod
    def _condition(code: object) -> str:
        return condition_from_wmo_code(
            code,
            unknown="Unknown conditions",
        ) or "Unknown conditions"
