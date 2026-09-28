from __future__ import annotations

import pytest

from porter.weather.composite import WeatherAgreement
from porter.weather.consensus import CurrentConsensusEngine
from porter.weather.current import CurrentConditions, CurrentWeatherComparison


def _local(
    station_id: str,
    temperature_f: float,
    *,
    distance_miles: float,
    age_minutes: float,
) -> CurrentConditions:
    return CurrentConditions(
        source="synoptic-local-observation",
        observed_at=None,
        temperature_f=temperature_f,
        humidity_percent=60.0,
        wind_speed_mph=5.0,
        wind_direction_degrees=270.0,
        condition=None,
        station_id=station_id,
        distance_miles=distance_miles,
        age_minutes=age_minutes,
    )


def test_synoptic_stations_form_one_distance_and_freshness_weighted_family() -> None:
    conditions = (
        _local("PWS1", 79.0, distance_miles=0.5, age_minutes=5.0),
        _local("PWS2", 80.0, distance_miles=1.0, age_minutes=10.0),
        _local("PWS3", 80.5, distance_miles=2.0, age_minutes=20.0),
        CurrentConditions(
            source="open-meteo-ecmwf-current",
            observed_at=None,
            temperature_f=79.5,
            humidity_percent=58.0,
            wind_speed_mph=6.0,
            wind_direction_degrees=280.0,
            condition="Partly cloudy",
        ),
    )
    result = CurrentConsensusEngine().estimate(
        CurrentWeatherComparison(
            conditions=conditions,
            temperature_spread_f=1.5,
            agreement=WeatherAgreement.HIGH,
        )
    )

    local = [item for item in result.evidence if item.family == "local-observation"]
    assert len(local) == 3
    assert {item.kind for item in local} == {"observation"}
    assert sum(item.weight for item in local) == pytest.approx(0.95)
    assert local[0].distance_factor > local[1].distance_factor > local[2].distance_factor
    assert local[2].freshness_factor == 0.9
    assert result.accepted_family_count == 2
    assert result.confidence is WeatherAgreement.HIGH


def test_synoptic_family_rejects_isolated_bad_pws_before_family_consensus() -> None:
    conditions = (
        _local("PWS1", 79.0, distance_miles=0.5, age_minutes=5.0),
        _local("PWS2", 80.0, distance_miles=1.0, age_minutes=5.0),
        _local("BAD", 94.0, distance_miles=0.3, age_minutes=5.0),
        CurrentConditions(
            source="open-meteo-ecmwf-current",
            observed_at=None,
            temperature_f=79.5,
            humidity_percent=None,
            wind_speed_mph=None,
            wind_direction_degrees=None,
            condition=None,
        ),
    )
    result = CurrentConsensusEngine().estimate(
        CurrentWeatherComparison(
            conditions=conditions,
            temperature_spread_f=15.0,
            agreement=WeatherAgreement.LOW,
        )
    )

    rejected = next(item for item in result.evidence if not item.accepted)
    assert rejected.station_id == "BAD"
    assert rejected.family == "local-observation"
    assert result.accepted_temperature_spread_f == 1.0
    assert result.confidence is WeatherAgreement.HIGH
