from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from porter.weather.open_meteo import (
    OpenMeteoClient,
    OpenMeteoClientError,
    OpenMeteoWeatherProvider,
)


class FakeOpenMeteoApi:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[str] = []

    async def get_json(self, url: str) -> dict[str, Any]:
        self.calls.append(url)
        return self.response


def test_open_meteo_client_builds_forecast_url() -> None:
    client = OpenMeteoClient()
    url = client.forecast_url(
        latitude=40.7357,
        longitude=-74.0301,
    )

    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.netloc == "api.open-meteo.com"
    assert query["latitude"] == ["40.7357"]
    assert query["longitude"] == ["-74.0301"]
    assert query["temperature_unit"] == ["fahrenheit"]
    assert query["wind_speed_unit"] == ["mph"]
    assert query["timezone"] == ["auto"]


@pytest.mark.asyncio
async def test_open_meteo_provider_normalizes_daily_forecast() -> None:
    client = FakeOpenMeteoApi(
        {
            "daily": {
                "time": ["2026-08-13"],
                "temperature_2m_max": [82.0],
                "temperature_2m_min": [70.0],
                "precipitation_probability_max": [25.0],
                "weather_code": [2],
                "wind_speed_10m_max": [12.0],
            }
        }
    )

    result = await OpenMeteoWeatherProvider(
        client=client
    ).forecast(
        latitude=40.7357,
        longitude=-74.0301,
    )

    assert len(client.calls) == 1
    assert result.source == "open-meteo"
    assert len(result.periods) == 1

    period = result.periods[0]
    assert period.name == "2026-08-13"
    assert period.temperature_f is None
    assert period.temperature_high_f == 82.0
    assert period.temperature_low_f == 70.0
    assert period.precipitation_probability == 25.0
    assert period.wind_speed == "12 mph"
    assert period.short_forecast == "Partly cloudy"
    assert "high 82°F" in (period.detailed_forecast or "")
    assert "low 70°F" in (period.detailed_forecast or "")


@pytest.mark.asyncio
async def test_open_meteo_provider_rejects_inconsistent_arrays() -> None:
    client = FakeOpenMeteoApi(
        {
            "daily": {
                "time": ["2026-08-13"],
                "temperature_2m_max": [82.0, 83.0],
                "temperature_2m_min": [70.0],
                "precipitation_probability_max": [25.0],
                "weather_code": [2],
                "wind_speed_10m_max": [12.0],
            }
        }
    )

    with pytest.raises(
        OpenMeteoClientError,
        match="inconsistent",
    ):
        await OpenMeteoWeatherProvider(
            client=client
        ).forecast(
            latitude=40.7357,
            longitude=-74.0301,
        )


@pytest.mark.asyncio
async def test_open_meteo_provider_rejects_invalid_coordinates() -> None:
    provider = OpenMeteoWeatherProvider(
        client=FakeOpenMeteoApi({})
    )

    with pytest.raises(
        ValueError,
        match="longitude",
    ):
        await provider.forecast(
            latitude=40.0,
            longitude=-200.0,
        )
