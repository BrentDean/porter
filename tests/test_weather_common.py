from __future__ import annotations

import pytest

from porter.weather.geo import distance_miles, validate_coordinates
from porter.weather.wmo import condition_from_wmo_code


def test_validate_coordinates_rejects_out_of_range_values() -> None:
    with pytest.raises(ValueError, match="latitude"):
        validate_coordinates(91.0, 0.0)

    with pytest.raises(ValueError, match="longitude"):
        validate_coordinates(0.0, 181.0)


def test_distance_miles_is_zero_for_same_point() -> None:
    assert distance_miles(40.0, -74.0, 40.0, -74.0) == pytest.approx(0.0)


def test_wmo_condition_mapping_preserves_caller_fallbacks() -> None:
    assert condition_from_wmo_code(0) == "Clear"
    assert condition_from_wmo_code(63) == "Rain"
    assert condition_from_wmo_code("bad") is None
    assert condition_from_wmo_code("bad", unknown="Unknown") == "Unknown"
    assert condition_from_wmo_code(123, mixed="Mixed") == "Mixed"
