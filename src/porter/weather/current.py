from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urlencode

from porter.core.clock import utc_now
from porter.weather.composite import WeatherAgreement
from porter.weather.errors import WeatherSourceError
from porter.weather.geo import distance_miles, validate_coordinates
from porter.weather.nws import NwsClient
from porter.weather.open_meteo import OpenMeteoClient
from porter.weather.wmo import condition_from_wmo_code


class CurrentWeatherError(Exception):
    """Raised when current conditions cannot be resolved."""


class JsonApi(Protocol):
    async def get_json(self, url: str) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class CurrentConditions:
    source: str
    observed_at: str | None
    temperature_f: float | None
    humidity_percent: float | None
    wind_speed_mph: float | None
    wind_direction_degrees: float | None
    condition: str | None
    station_id: str | None = None
    apparent_temperature_f: float | None = None
    distance_miles: float | None = None
    age_minutes: float | None = None


@dataclass(frozen=True, slots=True)
class CurrentWeatherComparison:
    conditions: tuple[CurrentConditions, ...]
    temperature_spread_f: float | None
    agreement: WeatherAgreement


class CurrentWeatherProvider(Protocol):
    source: str

    async def current(
        self,
        *,
        latitude: float,
        longitude: float,
    ) -> CurrentConditions | tuple[CurrentConditions, ...]: ...


@dataclass(frozen=True, slots=True)
class _NwsStationCandidate:
    station_id: str | None
    station_url: str
    distance_miles: float | None


class NwsObservationProvider:
    source = "nws-observation"

    def __init__(
        self,
        *,
        client: JsonApi | None = None,
        base_url: str = "https://api.weather.gov",
        user_agent: str = "porter-ai/0.1",
        timeout_seconds: float = 10.0,
        station_limit: int = 3,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if station_limit <= 0:
            raise ValueError("NWS station_limit must be positive")
        self._base_url = base_url.rstrip("/")
        self._client = client or NwsClient(
            base_url=base_url,
            user_agent=user_agent,
            timeout_seconds=timeout_seconds,
        )
        self._station_limit = station_limit
        self._now = now or utc_now

    async def current(
        self,
        *,
        latitude: float,
        longitude: float,
    ) -> tuple[CurrentConditions, ...]:
        validate_coordinates(latitude, longitude)
        points = await self._client.get_json(
            f"{self._base_url}/points/{latitude},{longitude}"
        )
        point_properties = self._properties(points)
        stations_url = point_properties.get("observationStations")
        if not isinstance(stations_url, str):
            raise CurrentWeatherError(
                "NWS point response is missing observation stations URL"
            )

        stations = await self._client.get_json(stations_url)
        candidates = self._station_candidates(
            stations,
            latitude=latitude,
            longitude=longitude,
        )[: self._station_limit]
        if not candidates:
            raise CurrentWeatherError("NWS returned no observation stations")

        results = await asyncio.gather(
            *(self._latest_observation(candidate) for candidate in candidates),
            return_exceptions=True,
        )
        observations: list[CurrentConditions] = []
        failures: list[str] = []
        for candidate, result in zip(candidates, results, strict=True):
            if isinstance(result, CurrentWeatherError | WeatherSourceError):
                station = candidate.station_id or candidate.station_url
                failures.append(f"{station}: {result}")
                continue
            if isinstance(result, BaseException):
                raise result
            observations.append(result)

        available = tuple(
            item for item in observations if item.temperature_f is not None
        )
        if not available:
            detail = f": {'; '.join(failures)}" if failures else ""
            raise CurrentWeatherError(
                "NWS nearby stations returned no usable temperatures"
                f"{detail}"
            )
        return available

    async def _latest_observation(
        self,
        candidate: _NwsStationCandidate,
    ) -> CurrentConditions:
        observation = await self._client.get_json(
            f"{candidate.station_url.rstrip('/')}/observations/latest?require_qc=true"
        )
        properties = self._properties(observation)
        observed_at = self._string(properties.get("timestamp"))

        return CurrentConditions(
            source=self.source,
            observed_at=observed_at,
            temperature_f=self._temperature_f(properties.get("temperature")),
            humidity_percent=self._quantity_value(
                properties.get("relativeHumidity")
            ),
            wind_speed_mph=self._wind_mph(properties.get("windSpeed")),
            wind_direction_degrees=self._quantity_value(
                properties.get("windDirection")
            ),
            condition=self._string(properties.get("textDescription")),
            station_id=candidate.station_id,
            distance_miles=candidate.distance_miles,
            age_minutes=self._age_minutes(observed_at),
        )

    def _station_candidates(
        self,
        payload: dict[str, Any],
        *,
        latitude: float,
        longitude: float,
    ) -> tuple[_NwsStationCandidate, ...]:
        features = payload.get("features")
        if not isinstance(features, list):
            raise CurrentWeatherError("NWS returned malformed observation stations")

        candidates: list[_NwsStationCandidate] = []
        for feature in features:
            if not isinstance(feature, dict):
                continue
            properties = feature.get("properties")
            if not isinstance(properties, dict):
                continue
            station_id = self._string(properties.get("stationIdentifier"))
            station_url = self._string(feature.get("id"))
            if station_url is None and station_id is not None:
                station_url = f"{self._base_url}/stations/{station_id}"
            if station_url is None:
                continue
            station_coordinates = self._coordinates(feature.get("geometry"))
            distance = None
            if station_coordinates is not None:
                station_latitude, station_longitude = station_coordinates
                distance = distance_miles(
                    latitude,
                    longitude,
                    station_latitude,
                    station_longitude,
                )
            candidates.append(
                _NwsStationCandidate(
                    station_id=station_id,
                    station_url=station_url,
                    distance_miles=distance,
                )
            )

        candidates.sort(
            key=lambda item: (
                item.distance_miles is None,
                item.distance_miles if item.distance_miles is not None else 0.0,
            )
        )
        return tuple(candidates)

    def _age_minutes(self, observed_at: str | None) -> float | None:
        if not observed_at:
            return None
        try:
            observed = datetime.fromisoformat(observed_at)
        except ValueError:
            return None
        if observed.tzinfo is None:
            return None
        age = (
            self._now().astimezone(UTC)
            - observed.astimezone(UTC)
        ).total_seconds() / 60
        return max(0.0, age)

    @staticmethod
    def _coordinates(geometry: object) -> tuple[float, float] | None:
        if not isinstance(geometry, dict):
            return None
        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            return None
        longitude, latitude = coordinates[0], coordinates[1]
        if not isinstance(latitude, int | float):
            return None
        if not isinstance(longitude, int | float):
            return None
        return float(latitude), float(longitude)

    @staticmethod
    def _properties(payload: dict[str, Any]) -> dict[str, Any]:
        properties = payload.get("properties")
        if not isinstance(properties, dict):
            raise CurrentWeatherError("weather source returned malformed properties")
        return properties

    @classmethod
    def _temperature_f(cls, quantity: object) -> float | None:
        value, unit = cls._quantity(quantity)
        if value is None:
            return None
        if unit in {"wmoUnit:degC", "unit:degC"}:
            return (value * 9 / 5) + 32
        if unit in {"wmoUnit:degF", "unit:degF"}:
            return value
        return None

    @classmethod
    def _wind_mph(cls, quantity: object) -> float | None:
        value, unit = cls._quantity(quantity)
        if value is None:
            return None
        if unit in {"wmoUnit:km_h-1", "unit:km_h-1"}:
            return value * 0.621371
        if unit in {"wmoUnit:m_s-1", "unit:m_s-1"}:
            return value * 2.23694
        if unit in {"wmoUnit:mi_h-1", "unit:mi_h-1"}:
            return value
        return None

    @classmethod
    def _quantity_value(cls, quantity: object) -> float | None:
        value, _ = cls._quantity(quantity)
        return value

    @staticmethod
    def _quantity(quantity: object) -> tuple[float | None, str | None]:
        if not isinstance(quantity, dict):
            return None, None
        value = quantity.get("value")
        unit = quantity.get("unitCode")
        if not isinstance(value, int | float):
            return None, unit if isinstance(unit, str) else None
        return float(value), unit if isinstance(unit, str) else None

    @staticmethod
    def _string(value: object) -> str | None:
        if isinstance(value, str) and value:
            return value
        return None


class OpenMeteoCurrentProvider:
    source = "open-meteo-current"

    def __init__(
        self,
        *,
        client: JsonApi | None = None,
        base_url: str = "https://api.open-meteo.com/v1/forecast",
        timeout_seconds: float = 10.0,
    ) -> None:
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
                        "apparent_temperature",
                        "weather_code",
                        "wind_speed_10m",
                        "wind_direction_10m",
                    )
                ),
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "timezone": "auto",
            }
        )
        payload = await self._client.get_json(f"{self._base_url}?{query}")
        current = payload.get("current")
        if not isinstance(current, dict):
            raise CurrentWeatherError(
                "Open-Meteo response is missing current conditions"
            )

        return CurrentConditions(
            source=self.source,
            observed_at=self._string(current.get("time")),
            temperature_f=self._number(current.get("temperature_2m")),
            humidity_percent=self._number(current.get("relative_humidity_2m")),
            apparent_temperature_f=self._number(
                current.get("apparent_temperature")
            ),
            wind_speed_mph=self._number(current.get("wind_speed_10m")),
            wind_direction_degrees=self._number(
                current.get("wind_direction_10m")
            ),
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


class CurrentWeatherService:
    def __init__(
        self,
        providers: tuple[CurrentWeatherProvider, ...],
    ) -> None:
        if len(providers) < 2:
            raise ValueError("current weather requires at least two providers")
        sources = [provider.source for provider in providers]
        if len(sources) != len(set(sources)):
            raise ValueError("current weather provider sources must be unique")
        self._providers = providers

    async def current(
        self,
        *,
        latitude: float,
        longitude: float,
    ) -> CurrentWeatherComparison:
        results = await asyncio.gather(
            *(
                provider.current(
                    latitude=latitude,
                    longitude=longitude,
                )
                for provider in self._providers
            ),
            return_exceptions=True,
        )

        collected: list[CurrentConditions] = []
        failures: list[str] = []
        for provider, result in zip(self._providers, results, strict=True):
            if isinstance(result, CurrentWeatherError | WeatherSourceError):
                failures.append(f"{provider.source}: {result}")
                continue
            if isinstance(result, BaseException):
                raise result
            if isinstance(result, CurrentConditions):
                collected.append(result)
            else:
                collected.extend(result)

        conditions = tuple(
            item for item in collected if item.temperature_f is not None
        )
        if not conditions:
            detail = "; ".join(failures) if failures else "no usable temperatures"
            raise CurrentWeatherError(f"current weather sources unavailable: {detail}")

        temperatures = [
            item.temperature_f
            for item in conditions
            if item.temperature_f is not None
        ]
        spread = None
        if len(temperatures) >= 2:
            spread = max(temperatures) - min(temperatures)

        return CurrentWeatherComparison(
            conditions=conditions,
            temperature_spread_f=spread,
            agreement=self._agreement(spread),
        )

    @staticmethod
    def _agreement(spread: float | None) -> WeatherAgreement:
        if spread is None:
            return WeatherAgreement.LOW
        if spread <= 2:
            return WeatherAgreement.HIGH
        if spread <= 5:
            return WeatherAgreement.MODERATE
        return WeatherAgreement.LOW
