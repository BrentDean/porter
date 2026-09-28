from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WeatherPeriod:
    name: str
    start_time: str
    end_time: str
    is_daytime: bool
    temperature_f: float | None
    precipitation_probability: float | None
    wind_speed: str | None
    short_forecast: str | None
    detailed_forecast: str | None
    temperature_high_f: float | None = None
    temperature_low_f: float | None = None
    humidity_mean_percent: float | None = None

    @property
    def is_daily(self) -> bool:
        return self.temperature_high_f is not None or self.temperature_low_f is not None

    def comparable_temperature_f(self, *, is_daytime: bool) -> float | None:
        if self.is_daily:
            if is_daytime:
                return self.temperature_high_f
            return self.temperature_low_f
        return self.temperature_f


@dataclass(frozen=True, slots=True)
class WeatherForecast:
    latitude: float
    longitude: float
    source: str
    periods: tuple[WeatherPeriod, ...]
    narrative: str | None = None
