from __future__ import annotations

from typing import Any

import pytest

from porter.weather import NwsClientError, NwsWeatherProvider


class FakeNwsApi:
    def __init__(
        self,
        responses: dict[str, dict[str, Any]],
    ) -> None:
        self.responses = responses
        self.calls: list[str] = []

    async def get_json(
        self,
        url: str,
    ) -> dict[str, Any]:
        self.calls.append(url)
        return self.responses[url]


@pytest.mark.asyncio
async def test_nws_provider_discovers_forecast_and_preserves_narrative() -> None:
    points_url = "https://api.weather.gov/points/40.7357,-74.0301"
    forecast_url = "https://api.weather.gov/gridpoints/OKX/32,35/forecast"

    client = FakeNwsApi(
        {
            points_url: {
                "properties": {
                    "forecast": forecast_url,
                }
            },
            forecast_url: {
                "properties": {
                    "periods": [
                        {
                            "name": "Tonight",
                            "startTime": "2026-08-13T18:00:00-04:00",
                            "endTime": "2026-08-14T06:00:00-04:00",
                            "isDaytime": False,
                            "temperature": 72,
                            "temperatureUnit": "F",
                            "probabilityOfPrecipitation": {
                                "unitCode": "wmoUnit:percent",
                                "value": 20,
                            },
                            "windSpeed": "5 mph",
                            "shortForecast": "Partly Cloudy",
                            "detailedForecast": "Partly cloudy, with a low around 72.",
                        }
                    ]
                }
            },
        }
    )

    provider = NwsWeatherProvider(client=client)
    result = await provider.forecast(
        latitude=40.7357,
        longitude=-74.0301,
    )

    assert client.calls == [points_url, forecast_url]
    assert result.source == "nws"
    assert result.narrative == "Partly cloudy, with a low around 72."
    assert len(result.periods) == 1

    period = result.periods[0]
    assert period.name == "Tonight"
    assert period.temperature_f == 72.0
    assert period.precipitation_probability == 20.0
    assert period.wind_speed == "5 mph"
    assert period.short_forecast == "Partly Cloudy"


@pytest.mark.asyncio
async def test_nws_provider_converts_celsius_temperature() -> None:
    points_url = "https://api.weather.gov/points/40.0,-74.0"
    forecast_url = "https://example.test/forecast"

    client = FakeNwsApi(
        {
            points_url: {
                "properties": {
                    "forecast": forecast_url,
                }
            },
            forecast_url: {
                "properties": {
                    "periods": [
                        {
                            "name": "Today",
                            "startTime": "start",
                            "endTime": "end",
                            "isDaytime": True,
                            "temperature": 20,
                            "temperatureUnit": "C",
                        }
                    ]
                }
            },
        }
    )

    result = await NwsWeatherProvider(client=client).forecast(
        latitude=40.0,
        longitude=-74.0,
    )

    assert result.periods[0].temperature_f == 68.0


@pytest.mark.asyncio
async def test_nws_provider_rejects_missing_forecast_url() -> None:
    client = FakeNwsApi(
        {
            "https://api.weather.gov/points/40.0,-74.0": {
                "properties": {}
            }
        }
    )

    with pytest.raises(
        NwsClientError,
        match="missing forecast URL",
    ):
        await NwsWeatherProvider(client=client).forecast(
            latitude=40.0,
            longitude=-74.0,
        )


@pytest.mark.asyncio
async def test_nws_provider_rejects_missing_periods() -> None:
    points_url = "https://api.weather.gov/points/40.0,-74.0"
    forecast_url = "https://example.test/forecast"

    client = FakeNwsApi(
        {
            points_url: {
                "properties": {
                    "forecast": forecast_url,
                }
            },
            forecast_url: {
                "properties": {}
            },
        }
    )

    with pytest.raises(
        NwsClientError,
        match="missing periods",
    ):
        await NwsWeatherProvider(client=client).forecast(
            latitude=40.0,
            longitude=-74.0,
        )


@pytest.mark.asyncio
async def test_nws_provider_rejects_invalid_coordinates() -> None:
    provider = NwsWeatherProvider(
        client=FakeNwsApi({})
    )

    with pytest.raises(
        ValueError,
        match="latitude",
    ):
        await provider.forecast(
            latitude=100.0,
            longitude=-74.0,
        )
