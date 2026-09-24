from __future__ import annotations

from dataclasses import dataclass

from porter.weather.composite import CompositeWeatherError, WeatherComparison
from porter.weather.consensus import CurrentConsensusEngine, CurrentWeatherEstimate
from porter.weather.current import CurrentWeatherComparison
from porter.weather.geocoding import GeocodedLocation
from porter.weather.models import WeatherForecast


@dataclass(frozen=True, slots=True)
class NearTermForecastReport:
    name: str
    is_daytime: bool
    temperature_f: float | None
    precipitation_probability: float | None
    wind_speed: str | None
    short_forecast: str | None
    official_outlook: str | None
    confidence: str
    temperature_spread_f: float | None
    sources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PorterWeatherReport:
    schema_version: int
    location: str
    latitude: float
    longitude: float
    timezone: str | None
    current: CurrentWeatherEstimate
    near_term: NearTermForecastReport

    def to_dict(self) -> dict[str, object]:
        current = self.current
        return {
            "schema_version": self.schema_version,
            "location": {
                "name": self.location,
                "latitude": self.latitude,
                "longitude": self.longitude,
                "timezone": self.timezone,
            },
            "current": {
                "temperature_f": current.temperature_f,
                "humidity_percent": current.humidity_percent,
                "apparent_temperature_f": current.apparent_temperature_f,
                "wind_speed_mph": current.wind_speed_mph,
                "wind_direction_degrees": current.wind_direction_degrees,
                "condition": current.condition,
                "confidence": current.confidence.value,
                "raw_temperature_spread_f": current.raw_temperature_spread_f,
                "accepted_temperature_spread_f": current.accepted_temperature_spread_f,
                "accepted_source_count": current.accepted_source_count,
                "accepted_evidence_count": current.accepted_source_count,
                "accepted_family_count": current.accepted_family_count,
                "rejected_source_count": current.rejected_source_count,
                "evidence": [
                    {
                        "source": item.source,
                        "family": item.family,
                        "kind": item.kind,
                        "temperature_f": item.temperature_f,
                        "humidity_percent": item.humidity_percent,
                        "apparent_temperature_f": item.apparent_temperature_f,
                        "wind_speed_mph": item.wind_speed_mph,
                        "wind_direction_degrees": item.wind_direction_degrees,
                        "condition": item.condition,
                        "observed_at": item.observed_at,
                        "station_id": item.station_id,
                        "distance_miles": item.distance_miles,
                        "age_minutes": item.age_minutes,
                        "accepted": item.accepted,
                        "base_weight": item.base_weight,
                        "distance_factor": item.distance_factor,
                        "freshness_factor": item.freshness_factor,
                        "weight": item.weight,
                        "rejection_reason": item.rejection_reason,
                    }
                    for item in current.evidence
                ],
            },
            "near_term": {
                "name": self.near_term.name,
                "is_daytime": self.near_term.is_daytime,
                "temperature_f": self.near_term.temperature_f,
                "precipitation_probability": self.near_term.precipitation_probability,
                "wind_speed": self.near_term.wind_speed,
                "short_forecast": self.near_term.short_forecast,
                "official_outlook": self.near_term.official_outlook,
                "confidence": self.near_term.confidence,
                "temperature_spread_f": self.near_term.temperature_spread_f,
                "sources": list(self.near_term.sources),
            },
        }


def build_weather_report(
    *,
    location: GeocodedLocation,
    current: CurrentWeatherComparison,
    forecast: WeatherComparison,
    consensus_engine: CurrentConsensusEngine | None = None,
) -> PorterWeatherReport:
    preferred = _preferred_forecast(forecast.forecasts)
    period = preferred.periods[0]
    engine = consensus_engine or CurrentConsensusEngine()

    return PorterWeatherReport(
        schema_version=1,
        location=location.display_name,
        latitude=location.latitude,
        longitude=location.longitude,
        timezone=location.timezone,
        current=engine.estimate(current),
        near_term=NearTermForecastReport(
            name=period.name or "Near-term forecast",
            is_daytime=period.is_daytime,
            temperature_f=period.comparable_temperature_f(
                is_daytime=period.is_daytime
            ),
            precipitation_probability=period.precipitation_probability,
            wind_speed=period.wind_speed,
            short_forecast=period.short_forecast,
            official_outlook=(
                period.detailed_forecast
                if preferred.source == "nws"
                else None
            ),
            confidence=forecast.agreement.value,
            temperature_spread_f=forecast.temperature_spread_f,
            sources=tuple(item.source for item in forecast.forecasts),
        ),
    )


def _preferred_forecast(
    forecasts: tuple[WeatherForecast, ...],
) -> WeatherForecast:
    nws = next(
        (
            forecast
            for forecast in forecasts
            if forecast.source == "nws" and forecast.periods
        ),
        None,
    )
    if nws is not None:
        return nws

    fallback = next(
        (forecast for forecast in forecasts if forecast.periods),
        None,
    )
    if fallback is None:
        raise CompositeWeatherError(
            "weather composite contains no forecast periods"
        )
    return fallback
