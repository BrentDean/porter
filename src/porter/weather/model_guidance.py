from __future__ import annotations

from urllib.parse import urlencode

from porter.weather.current import CurrentConditions, CurrentWeatherError, JsonApi
from porter.weather.geo import validate_coordinates
from porter.weather.open_meteo import OpenMeteoClient
from porter.weather.wmo import condition_from_wmo_code


class OpenMeteoModelCurrentProvider:
    """Read a named numerical weather model at the requested point."""

    def __init__(
        self,
        *,
        source: str,
        model: str,
        client: JsonApi | None = None,
        base_url: str = "https://api.open-meteo.com/v1/forecast",
        timeout_seconds: float = 10.0,
    ) -> None:
        if not source.strip():
            raise ValueError("model guidance source must not be empty")
        if not model.strip():
            raise ValueError("model guidance model must not be empty")
        self.source = source
        self.model = model
        self._base_url = base_url
        self._client = client or OpenMeteoClient(
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )

    async def current(
        self,
        *,
        latitude: float,
        longitude: float,
    ) -> CurrentConditions:
        validate_coordinates(latitude, longitude)
        query = urlencode(
            {
                "latitude": latitude,
                "longitude": longitude,
                "current": ",".join(
                    (
                        "temperature_2m",
                        "relative_humidity_2m",
                        "weather_code",
                        "wind_speed_10m",
                        "wind_direction_10m",
                    )
                ),
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "timezone": "auto",
                "models": self.model,
            }
        )
        payload = await self._client.get_json(f"{self._base_url}?{query}")
        current = payload.get("current")
        if not isinstance(current, dict):
            raise CurrentWeatherError(
                f"Open-Meteo model {self.model} is missing current guidance"
            )

        return CurrentConditions(
            source=self.source,
            observed_at=self._string(current.get("time")),
            temperature_f=self._number(current.get("temperature_2m")),
            humidity_percent=self._number(current.get("relative_humidity_2m")),
            wind_speed_mph=self._number(current.get("wind_speed_10m")),
            wind_direction_degrees=self._number(current.get("wind_direction_10m")),
            condition=condition_from_wmo_code(current.get("weather_code")),
        )

    @staticmethod
    def _number(value: object) -> float | None:
        if isinstance(value, int | float):
            return float(value)
        return None

    @staticmethod
    def _string(value: object) -> str | None:
        if isinstance(value, str) and value:
            return value
        return None
