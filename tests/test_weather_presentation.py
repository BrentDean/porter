from porter.weather.composite import WeatherAgreement
from porter.weather.consensus import CurrentSourceEvidence, CurrentWeatherEstimate
from porter.weather.presentation import WeatherDetail, render_weather_report
from porter.weather.report import NearTermForecastReport, PorterWeatherReport


def _evidence(source: str, temperature_f: float, weight: float) -> CurrentSourceEvidence:
    return CurrentSourceEvidence(
        source=source,
        family=source,
        kind="source",
        temperature_f=temperature_f,
        humidity_percent=None,
        apparent_temperature_f=None,
        wind_speed_mph=None,
        wind_direction_degrees=None,
        condition=None,
        observed_at=None,
        station_id=None,
        distance_miles=None,
        age_minutes=None,
        accepted=True,
        base_weight=weight,
        distance_factor=1.0,
        freshness_factor=1.0,
        weight=weight,
    )


def _report() -> PorterWeatherReport:
    return PorterWeatherReport(
        schema_version=1,
        location="Philadelphia, Pennsylvania",
        latitude=39.9526,
        longitude=-75.1652,
        timezone="America/New_York",
        current=CurrentWeatherEstimate(
            temperature_f=81.4,
            humidity_percent=54.0,
            apparent_temperature_f=83.0,
            wind_speed_mph=8.0,
            wind_direction_degrees=270.0,
            condition="Mostly Cloudy",
            confidence=WeatherAgreement.LOW,
            raw_temperature_spread_f=7.0,
            accepted_temperature_spread_f=7.0,
            evidence=(
                _evidence("nws-observation", 84.0, 1.0),
                _evidence("open-meteo-current", 77.0, 0.65),
            ),
        ),
        near_term=NearTermForecastReport(
            name="Tonight",
            is_daytime=False,
            temperature_f=71.0,
            precipitation_probability=20.0,
            wind_speed="5 mph",
            short_forecast="Partly Cloudy",
            official_outlook=None,
            confidence="high",
            temperature_spread_f=1.0,
            sources=("nws", "open-meteo"),
        ),
    )


def test_brief_marks_low_confidence_estimate_as_approximate() -> None:
    text = render_weather_report(_report(), WeatherDetail.BRIEF)

    assert "~81°F Mostly Cloudy" in text
    assert "evidence range 77–84°F" in text
    assert "confidence LOW" in text


def test_standard_marks_low_confidence_estimate_as_approximate() -> None:
    text = render_weather_report(_report())

    assert "~81°F  Mostly Cloudy" in text
    assert "2 inputs" in text
    assert "2 source families" in text
    assert "Evidence spread  7°F" in text
