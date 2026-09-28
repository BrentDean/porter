from __future__ import annotations

from dataclasses import dataclass

import pytest

from porter.tools.weather import WeatherTool
from porter.weather.composite import WeatherAgreement, WeatherComparison
from porter.weather.current import CurrentConditions, CurrentWeatherComparison
from porter.weather.geocoding import GeocodedLocation
from porter.weather.models import WeatherForecast, WeatherPeriod
from tests.fakes import make_request


@dataclass
class FakeGeocoder:
    async def resolve(self, query: str) -> GeocodedLocation:
        assert query == "Hoboken"
        return GeocodedLocation(
            name="Hoboken",
            latitude=40.7357,
            longitude=-74.0301,
            country_code="US",
            admin1="New Jersey",
            timezone="America/New_York",
        )


@dataclass
class FakeWeatherService:
    async def forecast(
        self,
        *,
        latitude: float,
        longitude: float,
    ) -> WeatherComparison:
        assert latitude == 40.7357
        assert longitude == -74.0301

        nws = WeatherForecast(
            latitude=latitude,
            longitude=longitude,
            source="nws",
            periods=(
                WeatherPeriod(
                    name="Tonight",
                    start_time="start",
                    end_time="end",
                    is_daytime=False,
                    temperature_f=72.0,
                    precipitation_probability=20.0,
                    wind_speed="5 mph",
                    short_forecast="Partly Cloudy",
                    detailed_forecast="Partly cloudy, with a low around 72.",
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
            temperature_spread_f=2.0,
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
                    periods=(
                        WeatherPeriod(
                            name="Today",
                            start_time="2026-08-16",
                            end_time="2026-08-16",
                            is_daytime=True,
                            temperature_f=None,
                            temperature_high_f=84.0,
                            temperature_low_f=70.0,
                            precipitation_probability=30.0,
                            wind_speed="10 mph",
                            short_forecast="Partly cloudy",
                            detailed_forecast="Open-Meteo daily summary",
                        ),
                    ),
                ),
            ),
            temperature_spread_f=None,
            precipitation_spread_percentage_points=None,
            agreement=WeatherAgreement.LOW,
        )


@dataclass
class FakeCurrentWeatherService:
    async def current(
        self,
        *,
        latitude: float,
        longitude: float,
    ) -> CurrentWeatherComparison:
        assert latitude == 40.7357
        assert longitude == -74.0301
        return CurrentWeatherComparison(
            conditions=(
                CurrentConditions(
                    source="nws-observation",
                    observed_at="2026-08-13T23:51:00+00:00",
                    temperature_f=81.0,
                    humidity_percent=67.0,
                    wind_speed_mph=8.0,
                    wind_direction_degrees=315.0,
                    condition="Mostly Cloudy",
                    station_id="KTEB",
                ),
                CurrentConditions(
                    source="open-meteo-current",
                    observed_at="2026-08-13T20:00",
                    temperature_f=82.0,
                    humidity_percent=65.0,
                    wind_speed_mph=7.0,
                    wind_direction_degrees=310.0,
                    condition="Partly cloudy",
                ),
            ),
            temperature_spread_f=1.0,
            agreement=WeatherAgreement.HIGH,
        )


@pytest.mark.parametrize(
    "text",
    [
        "weather in Hoboken",
        "weather for Hoboken",
        "weather Hoboken --brief",
        "weather Hoboken --detailed",
        "what is the weather in Hoboken?",
        "what's the forecast for Hoboken?",
    ],
)
def test_weather_tool_supports_weather_requests(text: str) -> None:
    tool = WeatherTool(
        geocoder=FakeGeocoder(),
        service=FakeWeatherService(),
        current_service=FakeCurrentWeatherService(),
    )
    assert tool.supports(make_request(content=text))


def test_weather_tool_rejects_unrelated_request() -> None:
    tool = WeatherTool(
        geocoder=FakeGeocoder(),
        service=FakeWeatherService(),
        current_service=FakeCurrentWeatherService(),
    )
    assert not tool.supports(make_request(content="explain ARP"))


@pytest.mark.asyncio
async def test_weather_tool_reports_porter_consensus() -> None:
    tool = WeatherTool(
        geocoder=FakeGeocoder(),
        service=FakeWeatherService(),
        current_service=FakeCurrentWeatherService(),
    )
    result = await tool.execute(make_request(content="weather in Hoboken"))

    assert "Hoboken, New Jersey" in result.text
    assert "┌ Now — Porter estimate " in result.text
    assert "81°F  Mostly Cloudy" in result.text
    assert "Humidity 66%" in result.text
    assert "Wind NW 8 mph" in result.text
    assert "Confidence HIGH" in result.text
    assert "2 inputs" in result.text
    assert "2 source families" in result.text
    assert "Evidence spread  1°F" in result.text
    assert "┌ Tonight " in result.text
    assert "Low 72°F  Partly Cloudy" in result.text
    assert "Rain 20%" in result.text
    assert "Forecast check" in result.text
    assert "Δ low 2°F" in result.text
    assert "confidence HIGH" in result.text
    assert "┌ Official NWS outlook " in result.text

    assert result.data["schema_version"] == 1
    current = result.data["current"]
    assert isinstance(current, dict)
    assert current["temperature_f"] == pytest.approx(81.3939, abs=0.001)
    assert current["confidence"] == "high"
    assert current["accepted_source_count"] == 2
    assert current["accepted_family_count"] == 2


@pytest.mark.asyncio
async def test_weather_tool_uses_surviving_forecast_when_nws_is_unavailable() -> None:
    tool = WeatherTool(
        geocoder=FakeGeocoder(),
        service=OpenMeteoOnlyWeatherService(),
        current_service=FakeCurrentWeatherService(),
    )

    result = await tool.execute(make_request(content="weather in Hoboken"))

    assert "High 84°F  Partly cloudy" in result.text
    assert "Forecast check  Open-Meteo" in result.text
    assert "confidence LOW" in result.text
    assert "Official NWS outlook" not in result.text
    near_term = result.data["near_term"]
    assert isinstance(near_term, dict)
    assert near_term["temperature_f"] == 84.0
    assert near_term["sources"] == ["open-meteo"]


@pytest.mark.asyncio
async def test_weather_detailed_exposes_source_weighting() -> None:
    tool = WeatherTool(
        geocoder=FakeGeocoder(),
        service=FakeWeatherService(),
        current_service=FakeCurrentWeatherService(),
    )
    result = await tool.execute(
        make_request(content="weather Hoboken --detailed")
    )

    assert "Current consensus details" in result.text
    assert "NWS KTEB" in result.text
    assert "Open-Meteo" in result.text
    assert "Dist" in result.text
    assert "Age" in result.text
    assert "Base" in result.text
    assert "Eff" in result.text
    assert "Weighted temperature  81.4°F" in result.text
    assert "Source families        2" in result.text

    current = result.data["current"]
    assert isinstance(current, dict)
    evidence = current["evidence"]
    assert isinstance(evidence, list)
    assert evidence[0]["family"] == "nws-observation"
    assert evidence[0]["base_weight"] == 1.0
    assert evidence[0]["distance_factor"] == 1.0
    assert evidence[0]["freshness_factor"] == 1.0


@pytest.mark.asyncio
async def test_weather_brief_is_compact() -> None:
    tool = WeatherTool(
        geocoder=FakeGeocoder(),
        service=FakeWeatherService(),
        current_service=FakeCurrentWeatherService(),
    )
    result = await tool.execute(make_request(content="weather Hoboken --brief"))

    assert "Hoboken, New Jersey" in result.text
    assert "81°F Mostly Cloudy" in result.text
    assert "confidence HIGH" in result.text
    assert "Tonight: low 72°F" in result.text
    assert "┌" not in result.text
