from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from porter.weather.composite import WeatherAgreement
from porter.weather.current import (
    CurrentConditions,
    CurrentWeatherError,
    CurrentWeatherService,
    NwsObservationProvider,
    OpenMeteoCurrentProvider,
)
from porter.weather.nws import NwsClientError


class FakeJsonApi:
    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    async def get_json(self, url: str) -> dict[str, Any]:
        self.calls.append(url)
        return self.responses[url]


class CoordinatedJsonApi(FakeJsonApi):
    def __init__(
        self,
        responses: dict[str, dict[str, Any]],
        *,
        coordinated_urls: set[str],
    ) -> None:
        super().__init__(responses)
        self._coordinated_urls = coordinated_urls
        self._started: set[str] = set()
        self._all_started = asyncio.Event()

    async def get_json(self, url: str) -> dict[str, Any]:
        self.calls.append(url)
        if url in self._coordinated_urls:
            self._started.add(url)
            if self._started == self._coordinated_urls:
                self._all_started.set()
            await asyncio.wait_for(self._all_started.wait(), timeout=1)
        return self.responses[url]


class FailingStationJsonApi(FakeJsonApi):
    def __init__(
        self,
        responses: dict[str, dict[str, Any]],
        *,
        failing_url: str,
    ) -> None:
        super().__init__(responses)
        self._failing_url = failing_url

    async def get_json(self, url: str) -> dict[str, Any]:
        self.calls.append(url)
        if url == self._failing_url:
            raise NwsClientError("temporary station failure")
        return self.responses[url]


def _station(
    station_id: str,
    *,
    latitude: float,
    longitude: float,
) -> dict[str, Any]:
    return {
        "id": f"https://api.weather.gov/stations/{station_id}",
        "geometry": {
            "type": "Point",
            "coordinates": [longitude, latitude],
        },
        "properties": {"stationIdentifier": station_id},
    }


def _observation(
    *,
    timestamp: str,
    temperature_c: float,
    condition: str,
) -> dict[str, Any]:
    return {
        "properties": {
            "timestamp": timestamp,
            "textDescription": condition,
            "temperature": {
                "unitCode": "wmoUnit:degC",
                "value": temperature_c,
            },
            "relativeHumidity": {
                "unitCode": "wmoUnit:percent",
                "value": 67,
            },
            "windSpeed": {
                "unitCode": "wmoUnit:km_h-1",
                "value": 12.96,
            },
            "windDirection": {
                "unitCode": "wmoUnit:degree_(angle)",
                "value": 315,
            },
        }
    }


@pytest.mark.asyncio
async def test_nws_provider_collects_nearest_station_observations() -> None:
    points_url = "https://api.weather.gov/points/37.7,-122.44"
    stations_url = "https://api.weather.gov/gridpoints/MTR/37,37/stations"
    station_urls = {
        station_id: f"https://api.weather.gov/stations/{station_id}"
        for station_id in ("KAAA", "KBBB", "KCCC", "KDDD")
    }
    latest_urls = {
        station_id: f"{url}/observations/latest?require_qc=true"
        for station_id, url in station_urls.items()
    }
    client = FakeJsonApi(
        {
            points_url: {"properties": {"observationStations": stations_url}},
            stations_url: {
                "features": [
                    _station("KDDD", latitude=37.80, longitude=-122.52),
                    _station("KBBB", latitude=37.71, longitude=-122.45),
                    _station("KAAA", latitude=37.70, longitude=-122.44),
                    _station("KCCC", latitude=37.72, longitude=-122.47),
                ]
            },
            latest_urls["KAAA"]: _observation(
                timestamp="2026-08-14T00:01:00+00:00",
                temperature_c=27.2,
                condition="Mostly Cloudy",
            ),
            latest_urls["KBBB"]: _observation(
                timestamp="2026-08-13T23:58:00+00:00",
                temperature_c=27.0,
                condition="Partly Cloudy",
            ),
            latest_urls["KCCC"]: _observation(
                timestamp="2026-08-13T23:55:00+00:00",
                temperature_c=26.8,
                condition="Partly Cloudy",
            ),
        }
    )

    provider = NwsObservationProvider(
        client=client,
        station_limit=3,
        now=lambda: datetime(2026, 8, 14, 0, 10, tzinfo=UTC),
    )
    result = await provider.current(latitude=37.7, longitude=-122.44)

    assert client.calls[:2] == [points_url, stations_url]
    assert set(client.calls[2:]) == {
        latest_urls["KAAA"],
        latest_urls["KBBB"],
        latest_urls["KCCC"],
    }
    assert [item.station_id for item in result] == ["KAAA", "KBBB", "KCCC"]
    assert result[0].source == "nws-observation"
    assert result[0].temperature_f == pytest.approx(80.96)
    assert result[0].humidity_percent == 67.0
    assert result[0].wind_speed_mph == pytest.approx(8.05, abs=0.01)
    assert result[0].wind_direction_degrees == 315.0
    assert result[0].condition == "Mostly Cloudy"
    assert result[0].distance_miles == pytest.approx(0.0)
    assert result[0].age_minutes == pytest.approx(9.0)
    assert result[1].distance_miles is not None
    assert result[2].distance_miles is not None
    assert result[1].distance_miles < result[2].distance_miles


@pytest.mark.asyncio
async def test_nws_provider_fetches_station_observations_concurrently() -> None:
    points_url = "https://api.weather.gov/points/37.7,-122.44"
    stations_url = "https://api.weather.gov/gridpoints/MTR/37,37/stations"
    latest_urls = {
        station_id: (
            f"https://api.weather.gov/stations/{station_id}"
            "/observations/latest?require_qc=true"
        )
        for station_id in ("KAAA", "KBBB")
    }
    responses = {
        points_url: {"properties": {"observationStations": stations_url}},
        stations_url: {
            "features": [
                _station("KAAA", latitude=37.70, longitude=-122.44),
                _station("KBBB", latitude=37.71, longitude=-122.45),
            ]
        },
        latest_urls["KAAA"]: _observation(
            timestamp="2026-08-14T00:01:00+00:00",
            temperature_c=27.2,
            condition="Mostly Cloudy",
        ),
        latest_urls["KBBB"]: _observation(
            timestamp="2026-08-13T23:58:00+00:00",
            temperature_c=27.0,
            condition="Partly Cloudy",
        ),
    }
    client = CoordinatedJsonApi(
        responses,
        coordinated_urls=set(latest_urls.values()),
    )

    result = await NwsObservationProvider(
        client=client,
        station_limit=2,
    ).current(latitude=37.7, longitude=-122.44)

    assert [item.station_id for item in result] == ["KAAA", "KBBB"]


@pytest.mark.asyncio
async def test_nws_provider_keeps_healthy_station_when_one_fails() -> None:
    points_url = "https://api.weather.gov/points/37.7,-122.44"
    stations_url = "https://api.weather.gov/gridpoints/MTR/37,37/stations"
    first_url = (
        "https://api.weather.gov/stations/KAAA"
        "/observations/latest?require_qc=true"
    )
    second_url = (
        "https://api.weather.gov/stations/KBBB"
        "/observations/latest?require_qc=true"
    )
    client = FailingStationJsonApi(
        {
            points_url: {"properties": {"observationStations": stations_url}},
            stations_url: {
                "features": [
                    _station("KAAA", latitude=37.70, longitude=-122.44),
                    _station("KBBB", latitude=37.71, longitude=-122.45),
                ]
            },
            second_url: _observation(
                timestamp="2026-08-13T23:58:00+00:00",
                temperature_c=27.0,
                condition="Partly Cloudy",
            ),
        },
        failing_url=first_url,
    )

    result = await NwsObservationProvider(
        client=client,
        station_limit=2,
    ).current(latitude=37.7, longitude=-122.44)

    assert [item.station_id for item in result] == ["KBBB"]


@pytest.mark.asyncio
async def test_open_meteo_current_provider_reads_current_values() -> None:
    client = FakeJsonApi({"unused": {}})

    async def get_json(url: str) -> dict[str, Any]:
        client.calls.append(url)
        return {
            "current": {
                "time": "2026-08-13T20:00",
                "temperature_2m": 81.6,
                "relative_humidity_2m": 65,
                "apparent_temperature": 84.1,
                "weather_code": 2,
                "wind_speed_10m": 7.4,
                "wind_direction_10m": 310,
            }
        }

    client.get_json = get_json  # type: ignore[method-assign]
    result = await OpenMeteoCurrentProvider(client=client).current(
        latitude=37.7,
        longitude=-122.44,
    )

    assert result.source == "open-meteo-current"
    assert result.temperature_f == 81.6
    assert result.humidity_percent == 65.0
    assert result.apparent_temperature_f == 84.1
    assert result.wind_speed_mph == 7.4
    assert result.condition == "Partly cloudy"
    assert "current=temperature_2m" in client.calls[0]


@pytest.mark.asyncio
async def test_current_weather_service_flattens_station_batches() -> None:
    class BatchProvider:
        source = "batch"

        async def current(self, *, latitude: float, longitude: float):
            return (
                CurrentConditions(
                    source="nws-observation",
                    observed_at=None,
                    temperature_f=81.0,
                    humidity_percent=None,
                    wind_speed_mph=None,
                    wind_direction_degrees=None,
                    condition=None,
                    station_id="ONE",
                ),
                CurrentConditions(
                    source="nws-observation",
                    observed_at=None,
                    temperature_f=82.0,
                    humidity_percent=None,
                    wind_speed_mph=None,
                    wind_direction_degrees=None,
                    condition=None,
                    station_id="TWO",
                ),
            )

    class SingleProvider:
        source = "single"

        async def current(self, *, latitude: float, longitude: float):
            return CurrentConditions(
                source="open-meteo-current",
                observed_at=None,
                temperature_f=82.5,
                humidity_percent=None,
                wind_speed_mph=None,
                wind_direction_degrees=None,
                condition=None,
            )

    service = CurrentWeatherService((BatchProvider(), SingleProvider()))
    result = await service.current(latitude=37.7, longitude=-122.44)

    assert len(result.conditions) == 3
    assert result.temperature_spread_f == 1.5
    assert result.agreement is WeatherAgreement.HIGH


@pytest.mark.asyncio
async def test_current_weather_service_runs_sources_concurrently_in_order() -> None:
    started: list[str] = []
    all_started = asyncio.Event()

    class CoordinatedProvider:
        def __init__(self, source: str, temperature_f: float) -> None:
            self.source = source
            self.temperature_f = temperature_f

        async def current(self, *, latitude: float, longitude: float):
            started.append(self.source)
            if len(started) == 2:
                all_started.set()
            await asyncio.wait_for(all_started.wait(), timeout=1)
            return CurrentConditions(
                source=self.source,
                observed_at=None,
                temperature_f=self.temperature_f,
                humidity_percent=None,
                wind_speed_mph=None,
                wind_direction_degrees=None,
                condition=None,
            )

    service = CurrentWeatherService(
        (
            CoordinatedProvider("first", 80.0),
            CoordinatedProvider("second", 81.0),
        )
    )

    result = await service.current(latitude=37.7, longitude=-122.44)

    assert started == ["first", "second"]
    assert [item.source for item in result.conditions] == ["first", "second"]


@pytest.mark.asyncio
async def test_current_weather_service_keeps_healthy_sources_when_one_fails() -> None:
    class FailingProvider:
        source = "failing"

        async def current(self, *, latitude: float, longitude: float):
            raise CurrentWeatherError("temporary source failure")

    class HealthyProvider:
        def __init__(self, source: str, temperature_f: float) -> None:
            self.source = source
            self.temperature_f = temperature_f

        async def current(self, *, latitude: float, longitude: float):
            return CurrentConditions(
                source=self.source,
                observed_at=None,
                temperature_f=self.temperature_f,
                humidity_percent=None,
                wind_speed_mph=None,
                wind_direction_degrees=None,
                condition=None,
            )

    service = CurrentWeatherService(
        (
            FailingProvider(),
            HealthyProvider("source-a", 80.0),
            HealthyProvider("source-b", 81.0),
        )
    )
    result = await service.current(latitude=37.7, longitude=-122.44)

    assert [item.source for item in result.conditions] == ["source-a", "source-b"]
    assert result.temperature_spread_f == 1.0
    assert result.agreement is WeatherAgreement.HIGH
