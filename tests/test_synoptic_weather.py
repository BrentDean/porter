from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from porter.weather.current import CurrentWeatherError
from porter.weather.synoptic import SynopticObservationProvider


class FakeJsonApi:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[str] = []

    async def get_json(self, url: str) -> dict[str, Any]:
        self.calls.append(url)
        return self.payload


def _station(
    station_id: str,
    *,
    temperature_f: float,
    distance_miles: float,
    observed_at: str,
    network_id: str = "999",
    restricted: bool = False,
) -> dict[str, Any]:
    return {
        "STID": station_id,
        "MNET_ID": network_id,
        "RESTRICTED": restricted,
        "DISTANCE": str(distance_miles),
        "LATITUDE": "37.77",
        "LONGITUDE": "-122.42",
        "OBSERVATIONS": {
            "air_temp_value_1": {
                "date_time": observed_at,
                "value": temperature_f,
            },
            "relative_humidity_value_1": {
                "date_time": observed_at,
                "value": 61.0,
            },
            "wind_speed_value_1": {
                "date_time": observed_at,
                "value": 6.5,
            },
            "wind_direction_value_1": {
                "date_time": observed_at,
                "value": 300.0,
            },
        },
    }


@pytest.mark.asyncio
async def test_synoptic_provider_builds_local_non_metar_cluster() -> None:
    client = FakeJsonApi(
        {
            "SUMMARY": {"RESPONSE_CODE": 1, "RESPONSE_MESSAGE": "OK"},
            "STATION": [
                _station(
                    "PWS1",
                    temperature_f=79.5,
                    distance_miles=0.8,
                    observed_at="2026-08-14T01:20:00Z",
                ),
                _station(
                    "PWS2",
                    temperature_f=80.0,
                    distance_miles=1.4,
                    observed_at="2026-08-14T01:18:00Z",
                ),
                _station(
                    "KSFO",
                    temperature_f=84.0,
                    distance_miles=9.8,
                    observed_at="2026-08-14T01:15:00Z",
                    network_id="1",
                ),
                _station(
                    "PRIVATE",
                    temperature_f=81.0,
                    distance_miles=1.0,
                    observed_at="2026-08-14T01:19:00Z",
                    restricted=True,
                ),
            ],
        }
    )
    provider = SynopticObservationProvider(
        token="public-token",
        client=client,
        now=lambda: datetime(2026, 8, 14, 1, 25, tzinfo=UTC),
    )

    result = await provider.current(latitude=37.76, longitude=-122.41)

    assert [item.station_id for item in result] == ["PWS1", "PWS2"]
    assert result[0].source == "synoptic-local-observation"
    assert result[0].temperature_f == 79.5
    assert result[0].humidity_percent == 61.0
    assert result[0].wind_speed_mph == 6.5
    assert result[0].wind_direction_degrees == 300.0
    assert result[0].distance_miles == 0.8
    assert result[0].age_minutes == pytest.approx(5.0)
    assert "radius=37.76%2C-122.41%2C5" in client.calls[0]
    assert "within=30" in client.calls[0]
    assert "units=english%2Cspeed%7Cmph%2Ctemp%7CF" in client.calls[0]
    assert "hfmetars=0" in client.calls[0]


@pytest.mark.asyncio
async def test_synoptic_provider_requires_cluster_not_single_pws() -> None:
    client = FakeJsonApi(
        {
            "SUMMARY": {"RESPONSE_CODE": 1, "RESPONSE_MESSAGE": "OK"},
            "STATION": [
                _station(
                    "PWS1",
                    temperature_f=79.5,
                    distance_miles=0.8,
                    observed_at="2026-08-14T01:20:00Z",
                )
            ],
        }
    )
    provider = SynopticObservationProvider(token="public-token", client=client)

    with pytest.raises(CurrentWeatherError, match="too few usable local stations"):
        await provider.current(latitude=37.76, longitude=-122.41)
