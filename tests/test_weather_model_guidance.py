from __future__ import annotations

from typing import Any

import pytest

from porter.weather.model_guidance import OpenMeteoModelCurrentProvider


class FakeJsonApi:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get_json(self, url: str) -> dict[str, Any]:
        self.calls.append(url)
        return {
            "current": {
                "time": "2026-08-14T01:15",
                "temperature_2m": 79.4,
                "relative_humidity_2m": 61,
                "weather_code": 2,
                "wind_speed_10m": 6.5,
                "wind_direction_10m": 285,
            }
        }


@pytest.mark.asyncio
async def test_open_meteo_named_model_current_guidance() -> None:
    client = FakeJsonApi()
    provider = OpenMeteoModelCurrentProvider(
        source="open-meteo-hrrr-current",
        model="ncep_hrrr_conus",
        client=client,
    )

    result = await provider.current(latitude=40.61, longitude=-73.91)

    assert result.source == "open-meteo-hrrr-current"
    assert result.temperature_f == 79.4
    assert result.humidity_percent == 61.0
    assert result.wind_speed_mph == 6.5
    assert result.wind_direction_degrees == 285.0
    assert result.condition == "Partly cloudy"
    assert "models=ncep_hrrr_conus" in client.calls[0]
    assert "current=temperature_2m" in client.calls[0]


def test_model_guidance_requires_source_and_model() -> None:
    with pytest.raises(ValueError, match="source"):
        OpenMeteoModelCurrentProvider(source="", model="ncep_hrrr_conus")
    with pytest.raises(ValueError, match="model"):
        OpenMeteoModelCurrentProvider(source="x", model="")
