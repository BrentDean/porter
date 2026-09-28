from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from porter.weather.errors import WeatherSourceError
from porter.weather.models import WeatherForecast, WeatherPeriod


class CompositeWeatherError(Exception):
    """Raised when no forecast source can satisfy a composite request."""


class WeatherProvider(Protocol):
    source: str

    async def forecast(
        self,
        *,
        latitude: float,
        longitude: float,
    ) -> WeatherForecast: ...


class WeatherAgreement(StrEnum):
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class WeatherComparison:
    forecasts: tuple[WeatherForecast, ...]
    temperature_spread_f: float | None
    precipitation_spread_percentage_points: float | None
    agreement: WeatherAgreement


class CompositeWeatherService:
    def __init__(
        self,
        providers: tuple[WeatherProvider, ...],
    ) -> None:
        if len(providers) < 2:
            raise ValueError(
                "composite weather requires at least two providers"
            )

        sources = [provider.source for provider in providers]
        if len(sources) != len(set(sources)):
            raise ValueError("weather provider sources must be unique")

        self._providers = providers

    async def forecast(
        self,
        *,
        latitude: float,
        longitude: float,
    ) -> WeatherComparison:
        results = await asyncio.gather(
            *(
                provider.forecast(
                    latitude=latitude,
                    longitude=longitude,
                )
                for provider in self._providers
            ),
            return_exceptions=True,
        )

        forecasts: list[WeatherForecast] = []
        failures: list[str] = []
        for provider, result in zip(self._providers, results, strict=True):
            if isinstance(result, WeatherSourceError):
                failures.append(f"{provider.source}: {result}")
                continue
            if isinstance(result, BaseException):
                raise result
            forecasts.append(result)

        available_forecasts = tuple(forecasts)
        if not available_forecasts:
            detail = "; ".join(failures) if failures else "no usable forecasts"
            raise CompositeWeatherError(
                f"weather forecast sources unavailable: {detail}"
            )

        periods = self._aligned_periods(available_forecasts)
        if not periods:
            return WeatherComparison(
                forecasts=available_forecasts,
                temperature_spread_f=None,
                precipitation_spread_percentage_points=None,
                agreement=WeatherAgreement.LOW,
            )

        reference = periods[0]
        temperature_spread = self._spread(
            period.comparable_temperature_f(
                is_daytime=reference.is_daytime
            )
            for period in periods
        )

        comparable_granularity = self._same_granularity(periods)
        precipitation_spread = None
        if comparable_granularity:
            precipitation_spread = self._spread(
                period.precipitation_probability
                for period in periods
            )

        return WeatherComparison(
            forecasts=available_forecasts,
            temperature_spread_f=temperature_spread,
            precipitation_spread_percentage_points=precipitation_spread,
            agreement=self._agreement(
                temperature_spread,
                precipitation_spread,
                periods if comparable_granularity else (),
            ),
        )

    @classmethod
    def _aligned_periods(
        cls,
        forecasts: tuple[WeatherForecast, ...],
    ) -> tuple[WeatherPeriod, ...]:
        reference = next(
            (
                forecast.periods[0]
                for forecast in forecasts
                if forecast.periods
            ),
            None,
        )
        if reference is None:
            return ()

        target_date = cls._date_key(reference.start_time)
        aligned: list[WeatherPeriod] = []

        for forecast in forecasts:
            period = next(
                (
                    candidate
                    for candidate in forecast.periods
                    if cls._date_key(candidate.start_time)
                    == target_date
                ),
                None,
            )
            if period is not None:
                aligned.append(period)

        return tuple(aligned)

    @staticmethod
    def _date_key(value: str) -> str:
        return value[:10]

    @staticmethod
    def _same_granularity(
        periods: tuple[WeatherPeriod, ...],
    ) -> bool:
        if len(periods) < 2:
            return False
        daily_flags = {period.is_daily for period in periods}
        return len(daily_flags) == 1

    @staticmethod
    def _spread(values: object) -> float | None:
        available = [
            value
            for value in values
            if isinstance(value, int | float)
        ]
        if len(available) < 2:
            return None
        return float(max(available) - min(available))

    @classmethod
    def _agreement(
        cls,
        temperature_spread: float | None,
        precipitation_spread: float | None,
        periods: tuple[WeatherPeriod, ...],
    ) -> WeatherAgreement:
        if temperature_spread is None:
            return WeatherAgreement.LOW

        condition_agreement = (
            cls._conditions_agree(periods)
            if periods
            else None
        )

        if temperature_spread <= 3:
            if precipitation_spread is not None:
                if precipitation_spread > 15:
                    return WeatherAgreement.MODERATE
                if condition_agreement is False:
                    return WeatherAgreement.MODERATE
            return WeatherAgreement.HIGH

        if temperature_spread <= 6:
            if (
                precipitation_spread is not None
                and precipitation_spread > 30
            ):
                return WeatherAgreement.LOW
            return WeatherAgreement.MODERATE

        return WeatherAgreement.LOW

    @staticmethod
    def _conditions_agree(
        periods: tuple[WeatherPeriod, ...],
    ) -> bool:
        conditions = [
            period.short_forecast.casefold()
            for period in periods
            if period.short_forecast
        ]
        if len(conditions) < 2:
            return False

        condition_groups = (
            ("clear", "sunny"),
            ("cloud", "overcast"),
            ("rain", "shower", "drizzle"),
            ("snow",),
            ("thunder",),
            ("fog",),
        )
        signatures = []
        for condition in conditions:
            signature = frozenset(
                index
                for index, terms in enumerate(condition_groups)
                if any(term in condition for term in terms)
            )
            signatures.append(signature)

        return bool(signatures[0]) and all(
            signature & signatures[0]
            for signature in signatures[1:]
        )
