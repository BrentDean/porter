from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from porter.weather.composite import (
    CompositeWeatherError,
    CompositeWeatherService,
    WeatherAgreement,
    WeatherSourceError,
)
from porter.weather.models import WeatherForecast, WeatherPeriod


@dataclass
class FakeWeatherProvider:
    source: str
    period: WeatherPeriod

    async def forecast(
        self,
        *,
        latitude: float,
        longitude: float,
    ) -> WeatherForecast:
        return WeatherForecast(
            latitude=latitude,
            longitude=longitude,
            source=self.source,
            periods=(self.period,),
        )


@dataclass
class FailingWeatherProvider:
    source: str

    async def forecast(
        self,
        *,
        latitude: float,
        longitude: float,
    ) -> WeatherForecast:
        raise WeatherSourceError("temporary source failure")


class CoordinatedWeatherProvider(FakeWeatherProvider):
    def __init__(
        self,
        *,
        source: str,
        period: WeatherPeriod,
        started: list[str],
        all_started: asyncio.Event,
    ) -> None:
        super().__init__(source=source, period=period)
        self._started = started
        self._all_started = all_started

    async def forecast(
        self,
        *,
        latitude: float,
        longitude: float,
    ) -> WeatherForecast:
        self._started.append(self.source)
        if len(self._started) == 2:
            self._all_started.set()
        await asyncio.wait_for(self._all_started.wait(), timeout=1)
        return await super().forecast(
            latitude=latitude,
            longitude=longitude,
        )


def period(
    *,
    temperature: float | None = None,
    high: float | None = None,
    low: float | None = None,
    rain: float = 20,
    condition: str = "Sunny",
    is_daytime: bool = True,
    start_time: str = "2026-08-13",
) -> WeatherPeriod:
    return WeatherPeriod(
        name="Today",
        start_time=start_time,
        end_time=start_time,
        is_daytime=is_daytime,
        temperature_f=temperature,
        temperature_high_f=high,
        temperature_low_f=low,
        precipitation_probability=rain,
        wind_speed="10 mph",
        short_forecast=condition,
        detailed_forecast=None,
    )


def provider(
    source: str,
    temperature: float,
    rain: float,
    condition: str,
) -> FakeWeatherProvider:
    return FakeWeatherProvider(
        source=source,
        period=period(
            temperature=temperature,
            rain=rain,
            condition=condition,
        ),
    )


def test_composite_requires_multiple_providers() -> None:
    with pytest.raises(ValueError, match="at least two providers"):
        CompositeWeatherService(
            (provider("one", 80, 20, "Sunny"),)
        )


def test_composite_rejects_duplicate_sources() -> None:
    with pytest.raises(ValueError, match="sources must be unique"):
        CompositeWeatherService(
            (
                provider("weather", 80, 20, "Sunny"),
                provider("weather", 81, 25, "Mostly sunny"),
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "first",
        "second",
        "temperature_spread",
        "rain_spread",
        "agreement",
    ),
    [
        (
            (81, 20, "Mostly Sunny"),
            (83, 24, "Clear"),
            2.0,
            4.0,
            WeatherAgreement.HIGH,
        ),
        (
            (80, 20, "Sunny"),
            (85, 40, "Rain"),
            5.0,
            20.0,
            WeatherAgreement.MODERATE,
        ),
        (
            (78, 10, "Sunny"),
            (88, 70, "Thunderstorms"),
            10.0,
            60.0,
            WeatherAgreement.LOW,
        ),
    ],
)
async def test_composite_rates_matching_periods(
    first: tuple[float, float, str],
    second: tuple[float, float, str],
    temperature_spread: float,
    rain_spread: float,
    agreement: WeatherAgreement,
) -> None:
    service = CompositeWeatherService(
        (
            provider("nws", *first),
            provider("open-meteo", *second),
        )
    )

    result = await service.forecast(
        latitude=40.0,
        longitude=-74.0,
    )

    assert result.temperature_spread_f == temperature_spread
    assert (
        result.precipitation_spread_percentage_points
        == rain_spread
    )
    assert result.agreement is agreement


@pytest.mark.asyncio
async def test_composite_runs_sources_concurrently_and_preserves_order() -> None:
    started: list[str] = []
    all_started = asyncio.Event()
    service = CompositeWeatherService(
        (
            CoordinatedWeatherProvider(
                source="first",
                period=period(temperature=80),
                started=started,
                all_started=all_started,
            ),
            CoordinatedWeatherProvider(
                source="second",
                period=period(temperature=81),
                started=started,
                all_started=all_started,
            ),
        )
    )

    result = await service.forecast(latitude=40.0, longitude=-74.0)

    assert started == ["first", "second"]
    assert [forecast.source for forecast in result.forecasts] == [
        "first",
        "second",
    ]


@pytest.mark.asyncio
async def test_composite_keeps_healthy_forecast_when_one_source_fails() -> None:
    service = CompositeWeatherService(
        (
            FailingWeatherProvider("nws"),
            provider("open-meteo", 82, 30, "Partly cloudy"),
        )
    )

    result = await service.forecast(latitude=40.0, longitude=-74.0)

    assert [forecast.source for forecast in result.forecasts] == ["open-meteo"]
    assert result.temperature_spread_f is None
    assert result.precipitation_spread_percentage_points is None
    assert result.agreement is WeatherAgreement.LOW


@pytest.mark.asyncio
async def test_composite_fails_when_all_forecast_sources_fail() -> None:
    service = CompositeWeatherService(
        (
            FailingWeatherProvider("nws"),
            FailingWeatherProvider("open-meteo"),
        )
    )

    with pytest.raises(
        CompositeWeatherError,
        match="weather forecast sources unavailable",
    ):
        await service.forecast(latitude=40.0, longitude=-74.0)


@pytest.mark.asyncio
async def test_composite_compares_nws_nighttime_to_daily_low() -> None:
    nws = FakeWeatherProvider(
        source="nws",
        period=period(
            temperature=70,
            rain=20,
            condition="Partly Cloudy",
            is_daytime=False,
            start_time="2026-08-13T18:00:00-04:00",
        ),
    )
    open_meteo = FakeWeatherProvider(
        source="open-meteo",
        period=period(
            high=86.8,
            low=71.2,
            rain=44,
            condition="Rain showers",
            start_time="2026-08-13",
        ),
    )

    result = await CompositeWeatherService(
        (nws, open_meteo)
    ).forecast(
        latitude=40.0,
        longitude=-74.0,
    )

    assert result.temperature_spread_f == pytest.approx(1.2)
    assert result.precipitation_spread_percentage_points is None
    assert result.agreement is WeatherAgreement.HIGH


@pytest.mark.asyncio
async def test_composite_aligns_periods_by_calendar_date() -> None:
    nws = FakeWeatherProvider(
        source="nws",
        period=period(
            temperature=70,
            is_daytime=False,
            start_time="2026-08-14T00:00:00-04:00",
        ),
    )
    open_meteo = FakeWeatherProvider(
        source="open-meteo",
        period=period(
            high=82,
            low=69,
            start_time="2026-08-13",
        ),
    )

    result = await CompositeWeatherService(
        (nws, open_meteo)
    ).forecast(
        latitude=40.0,
        longitude=-74.0,
    )

    assert result.temperature_spread_f is None
    assert result.precipitation_spread_percentage_points is None
    assert result.agreement is WeatherAgreement.LOW
