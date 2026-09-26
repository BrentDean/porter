from __future__ import annotations

from dataclasses import dataclass

import pytest

from porter.tools.weather import WeatherTool
from porter.weather.composite import WeatherAgreement, WeatherComparison
from porter.weather.extended import DailyForecast
from porter.weather.geocoding import GeocodedLocation
from porter.weather.models import WeatherForecast, WeatherPeriod
from tests.fakes import make_request


@dataclass
class FakeGeocoder:
    async def resolve(self, query: str) -> GeocodedLocation:
        assert query == "19103"
        return GeocodedLocation(
            name="Philadelphia",
            latitude=39.9526,
            longitude=-75.1652,
            country_code="US",
            admin1="Pennsylvania",
        )


@dataclass
class FakeWeatherService:
    async def forecast(
        self,
        *,
        latitude: float,
        longitude: float,
    ) -> WeatherComparison:
        nws = WeatherForecast(
            latitude=latitude,
            longitude=longitude,
            source="nws",
            periods=(
                WeatherPeriod(
                    name="Friday",
                    start_time="2026-08-14T06:00:00-04:00",
                    end_time="2026-08-14T18:00:00-04:00",
                    is_daytime=True,
                    temperature_f=84.0,
                    precipitation_probability=20.0,
                    wind_speed="5 to 10 mph",
                    short_forecast="Mostly Sunny",
                    detailed_forecast=None,
                ),
                WeatherPeriod(
                    name="Friday Night",
                    start_time="2026-08-14T18:00:00-04:00",
                    end_time="2026-08-15T06:00:00-04:00",
                    is_daytime=False,
                    temperature_f=70.0,
                    precipitation_probability=10.0,
                    wind_speed="5 mph",
                    short_forecast="Partly Cloudy",
                    detailed_forecast=None,
                ),
            ),
        )
        open_meteo = WeatherForecast(
            latitude=latitude,
            longitude=longitude,
            source="open-meteo",
            periods=(),
        )
        return WeatherComparison(
            forecasts=(nws, open_meteo),
            temperature_spread_f=1.0,
            precipitation_spread_percentage_points=5.0,
            agreement=WeatherAgreement.HIGH,
        )


@dataclass
class OpenMeteoOnlyWeatherService:
    async def forecast(
        self,
        *,
        latitude: float,
        longitude: float,
    ) -> WeatherComparison:
        return WeatherComparison(
            forecasts=(
                WeatherForecast(
                    latitude=latitude,
                    longitude=longitude,
                    source="open-meteo",
                    periods=(),
                ),
            ),
            temperature_spread_f=None,
            precipitation_spread_percentage_points=None,
            agreement=WeatherAgreement.LOW,
        )


class FakeExtendedProvider:
    def __init__(self) -> None:
        self.days: int | None = None

    async def forecast(
        self,
        *,
        latitude: float,
        longitude: float,
        days: int,
    ) -> tuple[DailyForecast, ...]:
        self.days = days
        return tuple(
            DailyForecast(
                date=f"2026-08-{14 + index:02d}",
                high_f=82.0 + index,
                low_f=69.0 + index,
                precipitation_probability=25.0,
                humidity_mean_percent=65.0,
                wind_speed_mph=12.0,
                condition="Partly cloudy",
            )
            for index in range(days)
        )


@pytest.mark.asyncio
async def test_forecast_days_renders_table() -> None:
    extended = FakeExtendedProvider()
    tool = WeatherTool(
        geocoder=FakeGeocoder(),
        service=FakeWeatherService(),
        extended_provider=extended,
    )

    result = await tool.execute(
        make_request(content="forecast 19103 --days 5")
    )

    assert extended.days == 5
    assert "Philadelphia, Pennsylvania" in result.text
    assert "5-Day Forecast" in result.text
    assert "Conditions" in result.text
    assert "High" in result.text
    assert "Low" in result.text
    assert "Rain" in result.text
    assert "Hum" in result.text
    assert "NWS+OM" in result.text
    assert "65%" in result.text
    assert result.data["days"] == 5


@pytest.mark.asyncio
async def test_forecast_days_uses_open_meteo_when_nws_is_unavailable() -> None:
    extended = FakeExtendedProvider()
    tool = WeatherTool(
        geocoder=FakeGeocoder(),
        service=OpenMeteoOnlyWeatherService(),
        extended_provider=extended,
    )

    result = await tool.execute(
        make_request(content="forecast 19103 --days 5")
    )

    assert "5-Day Forecast" in result.text
    assert "NWS+OM" not in result.text
    assert "| OM" in result.text
    assert result.data["sources"] == ("open-meteo",)


@pytest.mark.asyncio
async def test_forecast_defaults_to_seven_days() -> None:
    extended = FakeExtendedProvider()
    tool = WeatherTool(
        geocoder=FakeGeocoder(),
        service=FakeWeatherService(),
        extended_provider=extended,
    )

    result = await tool.execute(
        make_request(content="forecast 19103")
    )

    assert extended.days == 7
    assert "7-Day Forecast" in result.text


def test_forecast_rejects_unsupported_days() -> None:
    tool = WeatherTool(
        geocoder=FakeGeocoder(),
        service=FakeWeatherService(),
        extended_provider=FakeExtendedProvider(),
    )

    assert not tool.supports(
        make_request(content="forecast 19103 --days 9")
    )


@pytest.mark.asyncio
async def test_thirty_day_uses_outlook_message() -> None:
    extended = FakeExtendedProvider()
    tool = WeatherTool(
        geocoder=FakeGeocoder(),
        service=FakeWeatherService(),
        extended_provider=extended,
    )

    result = await tool.execute(
        make_request(content="forecast 19103 --days 30")
    )

    assert extended.days is None
    assert "30-Day Outlook" in result.text
    assert "not enabled yet" in result.text
    assert result.data["days"] == 30
