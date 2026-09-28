from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urlencode

from porter.core.clock import utc_now
from porter.net import JsonHttpError, JsonHttpTransport
from porter.weather.current import CurrentConditions, CurrentWeatherError
from porter.weather.geo import distance_miles, validate_coordinates


class SynopticClientError(Exception):
    """Raised when Synoptic cannot satisfy an observation request."""


class SynopticApi(Protocol):
    async def get_json(self, url: str) -> dict[str, Any]: ...


class SynopticClient:
    """Minimal async facade over Synoptic Data's Weather API."""

    def __init__(self, *, timeout_seconds: float = 10.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Synoptic timeout_seconds must be positive")
        self._transport = JsonHttpTransport(timeout_seconds=timeout_seconds)

    async def get_json(self, url: str) -> dict[str, Any]:
        try:
            return await self._transport.request_json(
                url,
                headers={"Accept": "application/json"},
            )
        except JsonHttpError as exc:
            raise SynopticClientError(f"Synoptic {exc}") from exc


class SynopticObservationProvider:
    """Build one local-observation family from nearby non-METAR stations."""

    source = "synoptic-local-observation"

    def __init__(
        self,
        *,
        token: str,
        client: SynopticApi | None = None,
        base_url: str = "https://api.synopticdata.com/v2/stations/latest",
        radius_miles: float = 5.0,
        station_limit: int = 12,
        within_minutes: int = 30,
        minimum_stations: int = 2,
        timeout_seconds: float = 10.0,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not token.strip():
            raise ValueError("Synoptic token must not be empty")
        if radius_miles <= 0:
            raise ValueError("Synoptic radius_miles must be positive")
        if station_limit <= 0:
            raise ValueError("Synoptic station_limit must be positive")
        if within_minutes <= 0:
            raise ValueError("Synoptic within_minutes must be positive")
        if minimum_stations <= 0:
            raise ValueError("Synoptic minimum_stations must be positive")
        if minimum_stations > station_limit:
            raise ValueError("Synoptic minimum_stations cannot exceed station_limit")

        self._token = token.strip()
        self._client = client or SynopticClient(timeout_seconds=timeout_seconds)
        self._base_url = base_url
        self._radius_miles = radius_miles
        self._station_limit = station_limit
        self._within_minutes = within_minutes
        self._minimum_stations = minimum_stations
        self._now = now or utc_now

    async def current(
        self,
        *,
        latitude: float,
        longitude: float,
    ) -> tuple[CurrentConditions, ...]:
        validate_coordinates(latitude, longitude)
        query = urlencode(
            {
                "token": self._token,
                "radius": f"{latitude},{longitude},{self._radius_miles:g}",
                "limit": self._station_limit,
                "within": self._within_minutes,
                "vars": ",".join(
                    (
                        "air_temp",
                        "relative_humidity",
                        "wind_speed",
                        "wind_direction",
                    )
                ),
                "units": "english,speed|mph,temp|F",
                "qc": "on",
                "qc_remove_data": "on",
                "hfmetars": 0,
            }
        )
        try:
            payload = await self._client.get_json(f"{self._base_url}?{query}")
        except SynopticClientError as exc:
            raise CurrentWeatherError(str(exc)) from exc
        self._validate_response(payload)

        stations = payload.get("STATION")
        if not isinstance(stations, list):
            raise CurrentWeatherError("Synoptic response is missing stations")

        conditions = tuple(
            condition
            for station in stations
            if isinstance(station, dict)
            if (condition := self._station_conditions(station, latitude, longitude))
            is not None
        )
        if len(conditions) < self._minimum_stations:
            raise CurrentWeatherError(
                "Synoptic returned too few usable local stations for a cluster"
            )
        return conditions

    def _station_conditions(
        self,
        station: dict[str, Any],
        latitude: float,
        longitude: float,
    ) -> CurrentConditions | None:
        if self._is_restricted(station.get("RESTRICTED")):
            return None
        if self._string(station.get("MNET_ID")) == "1":
            return None

        observations = station.get("OBSERVATIONS")
        if not isinstance(observations, dict):
            return None

        temperature, observed_at = self._latest_value(observations, "air_temp")
        if temperature is None or observed_at is None:
            return None

        humidity, _ = self._latest_value(observations, "relative_humidity")
        wind_speed, _ = self._latest_value(observations, "wind_speed")
        wind_direction, _ = self._latest_value(observations, "wind_direction")
        station_id = self._string(station.get("STID"))
        distance = self._number(station.get("DISTANCE"))
        if distance is None:
            station_latitude = self._number(station.get("LATITUDE"))
            station_longitude = self._number(station.get("LONGITUDE"))
            if station_latitude is not None and station_longitude is not None:
                distance = distance_miles(
                    latitude,
                    longitude,
                    station_latitude,
                    station_longitude,
                )

        return CurrentConditions(
            source=self.source,
            observed_at=observed_at,
            temperature_f=temperature,
            humidity_percent=humidity,
            wind_speed_mph=wind_speed,
            wind_direction_degrees=wind_direction,
            condition=None,
            station_id=station_id,
            distance_miles=distance,
            age_minutes=self._age_minutes(observed_at),
        )

    @staticmethod
    def _validate_response(payload: dict[str, Any]) -> None:
        summary = payload.get("SUMMARY")
        if not isinstance(summary, dict):
            raise CurrentWeatherError("Synoptic response is missing summary")
        code = summary.get("RESPONSE_CODE")
        if code != 1:
            message = summary.get("RESPONSE_MESSAGE")
            if isinstance(message, str) and message:
                raise CurrentWeatherError(f"Synoptic request failed: {message}")
            raise CurrentWeatherError("Synoptic request failed")

    @classmethod
    def _latest_value(
        cls,
        observations: dict[str, Any],
        variable: str,
    ) -> tuple[float | None, str | None]:
        prefix = f"{variable}_value_"
        candidates: list[tuple[str, float]] = []
        for key, raw in observations.items():
            if not isinstance(key, str) or not key.startswith(prefix):
                continue
            if not isinstance(raw, dict):
                continue
            value = cls._number(raw.get("value"))
            observed_at = cls._string(raw.get("date_time"))
            if value is None or observed_at is None:
                continue
            candidates.append((observed_at, value))
        if not candidates:
            return None, None
        observed_at, value = max(candidates, key=lambda item: item[0])
        return value, observed_at

    def _age_minutes(self, observed_at: str) -> float | None:
        try:
            observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        except ValueError:
            return None
        if observed.tzinfo is None:
            return None
        age = (
            self._now().astimezone(UTC) - observed.astimezone(UTC)
        ).total_seconds() / 60
        return max(0.0, age)

    @staticmethod
    def _is_restricted(value: object) -> bool:
        if value is True:
            return True
        if isinstance(value, str):
            return value.strip().casefold() not in {"", "0", "false", "no"}
        if isinstance(value, int | float):
            return value != 0
        return False

    @staticmethod
    def _number(value: object) -> float | None:
        if isinstance(value, int | float):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
        return None

    @staticmethod
    def _string(value: object) -> str | None:
        if isinstance(value, str) and value:
            return value
        if isinstance(value, int):
            return str(value)
        return None
