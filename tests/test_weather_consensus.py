from __future__ import annotations

import pytest

from porter.weather.composite import WeatherAgreement
from porter.weather.consensus import CurrentConsensusEngine
from porter.weather.current import CurrentConditions, CurrentWeatherComparison


def _conditions(
    source: str,
    temperature_f: float,
    *,
    station_id: str | None = None,
    distance_miles: float | None = None,
    age_minutes: float | None = None,
    humidity_percent: float | None = None,
    wind_speed_mph: float | None = None,
) -> CurrentConditions:
    return CurrentConditions(
        source=source,
        observed_at=None,
        temperature_f=temperature_f,
        humidity_percent=humidity_percent,
        wind_speed_mph=wind_speed_mph,
        wind_direction_degrees=None,
        condition=None,
        station_id=station_id,
        distance_miles=distance_miles,
        age_minutes=age_minutes,
    )


def _comparison(*conditions: CurrentConditions) -> CurrentWeatherComparison:
    temperatures = [item.temperature_f for item in conditions]
    spread = max(temperatures) - min(temperatures)
    return CurrentWeatherComparison(
        conditions=conditions,
        temperature_spread_f=spread,
        agreement=WeatherAgreement.LOW,
    )


def test_consensus_drops_isolated_temperature_outlier() -> None:
    result = CurrentConsensusEngine().estimate(
        _comparison(
            _conditions("source-a", 81.0),
            _conditions("source-b", 82.0),
            _conditions("source-c", 94.0),
        )
    )

    assert result.temperature_f == pytest.approx(81.5)
    assert result.accepted_source_count == 2
    assert result.accepted_family_count == 2
    assert result.rejected_source_count == 1
    assert result.accepted_temperature_spread_f == 1.0
    assert result.confidence is WeatherAgreement.HIGH
    rejected = next(item for item in result.evidence if not item.accepted)
    assert rejected.source == "source-c"
    assert rejected.rejection_reason == "temperature outlier"


def test_consensus_does_not_count_three_nws_stations_as_three_families() -> None:
    result = CurrentConsensusEngine().estimate(
        _comparison(
            _conditions("nws-observation", 81.0, station_id="KNYC"),
            _conditions("nws-observation", 82.0, station_id="KLGA"),
            _conditions("nws-observation", 84.0, station_id="KJFK"),
            _conditions("open-meteo-current", 76.0),
        )
    )

    assert result.accepted_source_count == 4
    assert result.accepted_family_count == 2
    assert result.rejected_source_count == 0
    assert result.confidence is WeatherAgreement.LOW


def test_consensus_drops_family_outlier_with_three_independent_families() -> None:
    result = CurrentConsensusEngine().estimate(
        _comparison(
            _conditions("nws-observation", 81.0, station_id="KNYC"),
            _conditions("nws-observation", 82.0, station_id="KLGA"),
            _conditions("nws-observation", 84.0, station_id="KJFK"),
            _conditions("local-observation", 82.0),
            _conditions("open-meteo-current", 76.0),
        )
    )

    assert result.accepted_family_count == 2
    assert result.rejected_source_count == 1
    rejected = next(item for item in result.evidence if not item.accepted)
    assert rejected.source == "open-meteo-current"


def test_consensus_keeps_three_sources_without_clear_outlier() -> None:
    result = CurrentConsensusEngine().estimate(
        _comparison(
            _conditions("source-a", 78.0),
            _conditions("source-b", 81.0),
            _conditions("source-c", 84.0),
        )
    )

    assert result.temperature_f == pytest.approx(81.0)
    assert result.accepted_source_count == 3
    assert result.accepted_family_count == 3
    assert result.rejected_source_count == 0
    assert result.accepted_temperature_spread_f == 6.0
    assert result.confidence is WeatherAgreement.LOW


def test_consensus_keeps_ambiguous_split_without_majority_cluster() -> None:
    result = CurrentConsensusEngine().estimate(
        _comparison(
            _conditions("source-a", 78.0),
            _conditions("source-b", 81.0),
            _conditions("source-c", 84.0),
            _conditions("source-d", 87.0),
        )
    )

    assert result.accepted_source_count == 4
    assert result.rejected_source_count == 0
    assert result.confidence is WeatherAgreement.LOW


def test_consensus_uses_source_weights_when_only_two_sources_exist() -> None:
    result = CurrentConsensusEngine().estimate(
        _comparison(
            _conditions("nws-observation", 84.0),
            _conditions("open-meteo-current", 77.5),
        )
    )

    assert result.temperature_f == pytest.approx(81.4394, abs=0.0001)
    assert result.accepted_source_count == 2
    assert result.accepted_family_count == 2
    assert result.rejected_source_count == 0
    assert result.raw_temperature_spread_f == 6.5
    assert result.confidence is WeatherAgreement.LOW


def test_consensus_downweights_distant_older_nws_observation() -> None:
    result = CurrentConsensusEngine().estimate(
        _comparison(
            _conditions(
                "nws-observation",
                84.0,
                station_id="KJFK",
                distance_miles=6.0,
                age_minutes=25.0,
            ),
            _conditions("open-meteo-current", 78.0),
        )
    )

    nws = next(item for item in result.evidence if item.station_id == "KJFK")
    model = next(
        item for item in result.evidence if item.source == "open-meteo-current"
    )
    assert nws.base_weight == 1.0
    assert nws.distance_factor == pytest.approx(0.625)
    assert nws.freshness_factor == 0.9
    assert nws.weight == pytest.approx(0.5625)
    assert model.weight == 0.65
    assert result.temperature_f < 81.0


def test_consensus_caps_multiple_nws_stations_as_one_family() -> None:
    result = CurrentConsensusEngine().estimate(
        _comparison(
            _conditions("nws-observation", 81.0, station_id="ONE"),
            _conditions("nws-observation", 82.0, station_id="TWO"),
            _conditions("nws-observation", 83.0, station_id="THREE"),
            _conditions("open-meteo-current", 80.0),
        )
    )

    nws_weight = sum(
        item.weight
        for item in result.evidence
        if item.source == "nws-observation" and item.accepted
    )
    assert nws_weight == pytest.approx(1.0)
    assert result.accepted_family_count == 2


def test_consensus_can_reject_one_nws_station_without_rejecting_all_nws() -> None:
    result = CurrentConsensusEngine().estimate(
        _comparison(
            _conditions("nws-observation", 81.0, station_id="ONE"),
            _conditions("nws-observation", 82.0, station_id="TWO"),
            _conditions("nws-observation", 94.0, station_id="THREE"),
        )
    )

    accepted_ids = {
        item.station_id for item in result.evidence if item.accepted
    }
    rejected_ids = {
        item.station_id for item in result.evidence if not item.accepted
    }
    assert accepted_ids == {"ONE", "TWO"}
    assert rejected_ids == {"THREE"}
    assert result.accepted_family_count == 1
    assert result.confidence is WeatherAgreement.LOW


def test_hrrr_and_nbm_share_noaa_model_family() -> None:
    result = CurrentConsensusEngine().estimate(
        _comparison(
            _conditions("open-meteo-hrrr-current", 80.0),
            _conditions("open-meteo-nbm-current", 81.0),
            _conditions("open-meteo-ecmwf-current", 80.5),
        )
    )

    families = {item.source: item.family for item in result.evidence}
    kinds = {item.source: item.kind for item in result.evidence}
    assert families["open-meteo-hrrr-current"] == "noaa-model"
    assert families["open-meteo-nbm-current"] == "noaa-model"
    assert families["open-meteo-ecmwf-current"] == "ecmwf-model"
    assert set(kinds.values()) == {"model"}
    assert result.accepted_family_count == 2

    noaa_weight = sum(
        item.weight for item in result.evidence if item.family == "noaa-model"
    )
    assert noaa_weight == pytest.approx(0.9)


def test_porter_derives_heat_index_from_consensus_weather() -> None:
    result = CurrentConsensusEngine().estimate(
        _comparison(
            _conditions(
                "source-a",
                90.0,
                humidity_percent=70.0,
                wind_speed_mph=5.0,
            ),
            _conditions(
                "source-b",
                90.0,
                humidity_percent=70.0,
                wind_speed_mph=5.0,
            ),
        )
    )

    assert result.apparent_temperature_f is not None
    assert result.apparent_temperature_f > result.temperature_f
    assert result.apparent_temperature_f == pytest.approx(105.9, abs=0.5)


def test_porter_derives_wind_chill_from_consensus_weather() -> None:
    result = CurrentConsensusEngine().estimate(
        _comparison(
            _conditions(
                "source-a",
                30.0,
                humidity_percent=50.0,
                wind_speed_mph=15.0,
            ),
            _conditions(
                "source-b",
                30.0,
                humidity_percent=50.0,
                wind_speed_mph=15.0,
            ),
        )
    )

    assert result.apparent_temperature_f is not None
    assert result.apparent_temperature_f < result.temperature_f
    assert result.apparent_temperature_f == pytest.approx(19.0, abs=0.5)
