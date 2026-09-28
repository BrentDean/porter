from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from porter.net import JsonHttpError, JsonHttpTransport
from porter.weather.wmo import condition_from_wmo_code


class ExtendedForecastError(Exception):
    """Raised when an extended forecast cannot be loaded."""


@dataclass(frozen=True, slots=True)
class DailyForecast:
    date: str
    high_f: float | None
    low_f: float | None
    precipitation_probability: float | None
    humidity_mean_percent: float | None
    wind_speed_mph: float | None
    condition: str


class OpenMeteoExtendedProvider:
    source = "open-meteo"

    def __init__(self, *, timeout_seconds: float = 10.0) -> None:
        self._transport = JsonHttpTransport(timeout_seconds=timeout_seconds)

    async def forecast(
        self,
        *,
        latitude: float,
        longitude: float,
        days: int,
    ) -> tuple[DailyForecast, ...]:
        if not 1 <= days <= 16:
            raise ValueError("extended forecast days must be between 1 and 16")
        try:
            payload = await self._transport.request_json(
                self._url(latitude, longitude, days),
                headers={"Accept": "application/json"},
            )
        except JsonHttpError as exc:
            raise ExtendedForecastError(f"extended forecast {exc}") from exc
        return self._parse(payload)

    def _url(self, latitude: float, longitude: float, days: int) -> str:
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
                "hourly": "relative_humidity_2m",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "timezone": "auto",
                "forecast_days": days,
            }
        )
        return f"https://api.open-meteo.com/v1/forecast?{query}"

    @classmethod
    def _parse(cls, payload: dict[str, Any]) -> tuple[DailyForecast, ...]:
        daily = payload.get("daily")
        if not isinstance(daily, dict):
            raise ExtendedForecastError("extended forecast is missing daily data")

        keys = (
            "time",
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_probability_max",
            "weather_code",
            "wind_speed_10m_max",
        )
        arrays = [daily.get(key) for key in keys]
        if not all(isinstance(value, list) for value in arrays):
            raise ExtendedForecastError("extended forecast daily data is incomplete")
        lengths = {len(value) for value in arrays if isinstance(value, list)}
        if len(lengths) != 1:
            raise ExtendedForecastError("extended forecast daily arrays are inconsistent")

        humidity = cls._humidity_by_day(payload.get("hourly"))
        times, highs, lows, rain, codes, winds = arrays
        return tuple(
            DailyForecast(
                date=str(day),
                high_f=cls._number(high),
                low_f=cls._number(low),
                precipitation_probability=cls._number(pop),
                humidity_mean_percent=humidity.get(str(day)),
                wind_speed_mph=cls._number(wind),
                condition=cls._condition(code),
            )
            for day, high, low, pop, code, wind in zip(
                times, highs, lows, rain, codes, winds, strict=True
            )
        )

    @classmethod
    def _humidity_by_day(cls, hourly: object) -> dict[str, float]:
        if not isinstance(hourly, dict):
            return {}
        times = hourly.get("time")
        values = hourly.get("relative_humidity_2m")
        if not isinstance(times, list) or not isinstance(values, list):
            return {}
        if len(times) != len(values):
            raise ExtendedForecastError("extended forecast humidity arrays are inconsistent")

        grouped: defaultdict[str, list[float]] = defaultdict(list)
        for timestamp, value in zip(times, values, strict=True):
            number = cls._number(value)
            if isinstance(timestamp, str) and number is not None:
                grouped[timestamp[:10]].append(number)
        return {
            day: round(sum(day_values) / len(day_values), 1)
            for day, day_values in grouped.items()
            if day_values
        }

    @staticmethod
    def _number(value: object) -> float | None:
        if isinstance(value, int | float):
            return float(value)
        return None

    @staticmethod
    def _condition(code: object) -> str:
        return condition_from_wmo_code(
            code,
            unknown="Unknown",
            mixed="Mixed",
        ) or "Unknown"
