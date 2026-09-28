from __future__ import annotations

import re
from datetime import date

from porter.core.models import RequestContext
from porter.tools.base import Tool
from porter.tools.models import ToolResult
from porter.weather.composite import CompositeWeatherService
from porter.weather.current import (
    CurrentWeatherProvider,
    CurrentWeatherService,
    NwsObservationProvider,
)
from porter.weather.extended import DailyForecast, OpenMeteoExtendedProvider
from porter.weather.geocoding import OpenMeteoGeocoder
from porter.weather.model_guidance import OpenMeteoModelCurrentProvider
from porter.weather.models import WeatherForecast, WeatherPeriod
from porter.weather.nws import NwsWeatherProvider
from porter.weather.open_meteo import OpenMeteoWeatherProvider
from porter.weather.presentation import WeatherDetail, render_weather_report
from porter.weather.report import build_weather_report
from porter.weather.synoptic import SynopticObservationProvider

_WEATHER = re.compile(
    r"^\s*(?:what(?:'s| is)\s+)?"
    r"(?:the\s+)?(?P<kind>weather|forecast)"
    r"(?:\s+(?:in|for))?\s+"
    r"(?P<body>.+?)"
    r"\??\s*$",
    re.IGNORECASE,
)
_DAYS = re.compile(r"(?:^|\s)--days\s+(?P<days>\d+)(?=\s|$)", re.IGNORECASE)
_DETAIL = re.compile(r"(?:^|\s)--(?P<detail>brief|detailed)(?=\s|$)", re.IGNORECASE)
_FORECAST_DAYS = frozenset({5, 7, 10, 30})


class WeatherTool(Tool):
    name = "weather"

    def __init__(
        self,
        *,
        geocoder: OpenMeteoGeocoder | None = None,
        service: CompositeWeatherService | None = None,
        current_service: CurrentWeatherService | None = None,
        extended_provider: OpenMeteoExtendedProvider | None = None,
        synoptic_token: str | None = None,
        synoptic_radius_miles: float = 5.0,
        synoptic_station_limit: int = 12,
        synoptic_within_minutes: int = 30,
    ) -> None:
        self._geocoder = geocoder or OpenMeteoGeocoder(country_code="US")
        self._service = service or CompositeWeatherService(
            (
                NwsWeatherProvider(),
                OpenMeteoWeatherProvider(),
            )
        )
        self._current_service = current_service or CurrentWeatherService(
            self._default_current_providers(
                synoptic_token=synoptic_token,
                synoptic_radius_miles=synoptic_radius_miles,
                synoptic_station_limit=synoptic_station_limit,
                synoptic_within_minutes=synoptic_within_minutes,
            )
        )
        self._extended_provider = extended_provider or OpenMeteoExtendedProvider()

    @staticmethod
    def _default_current_providers(
        *,
        synoptic_token: str | None,
        synoptic_radius_miles: float,
        synoptic_station_limit: int,
        synoptic_within_minutes: int,
    ) -> tuple[CurrentWeatherProvider, ...]:
        providers: list[CurrentWeatherProvider] = [
            NwsObservationProvider(),
            OpenMeteoModelCurrentProvider(
                source="open-meteo-hrrr-current",
                model="ncep_hrrr_conus",
            ),
            OpenMeteoModelCurrentProvider(
                source="open-meteo-nbm-current",
                model="ncep_nbm_conus",
            ),
            OpenMeteoModelCurrentProvider(
                source="open-meteo-ecmwf-current",
                model="ecmwf_ifs",
            ),
        ]
        if synoptic_token is not None:
            providers.insert(
                1,
                SynopticObservationProvider(
                    token=synoptic_token,
                    radius_miles=synoptic_radius_miles,
                    station_limit=synoptic_station_limit,
                    within_minutes=synoptic_within_minutes,
                ),
            )
        return tuple(providers)

    def supports(self, request: RequestContext) -> bool:
        return self._options(request) is not None

    async def execute(self, request: RequestContext) -> ToolResult:
        options = self._options(request)
        if options is None:
            raise ValueError("WeatherTool does not support request")

        kind, location_query, days, detail = options
        location = await self._geocoder.resolve(location_query)
        comparison = await self._service.forecast(
            latitude=location.latitude,
            longitude=location.longitude,
        )
        nws = self._nws_forecast(comparison.forecasts)

        if kind == "forecast":
            if days == 30:
                text = self._thirty_day_message(location.display_name)
            else:
                extended = await self._extended_provider.forecast(
                    latitude=location.latitude,
                    longitude=location.longitude,
                    days=days,
                )
                text = self._forecast_table(
                    location.display_name,
                    extended,
                    nws,
                    days,
                )
            data: dict[str, object] = {
                "location": location.display_name,
                "latitude": location.latitude,
                "longitude": location.longitude,
                "agreement": comparison.agreement.value,
                "sources": tuple(
                    forecast.source for forecast in comparison.forecasts
                ),
                "days": days,
            }
        else:
            current = await self._current_service.current(
                latitude=location.latitude,
                longitude=location.longitude,
            )
            report = build_weather_report(
                location=location,
                current=current,
                forecast=comparison,
            )
            text = render_weather_report(report, detail)
            data = report.to_dict()

        return ToolResult(text=text, data=data)

    @staticmethod
    def _nws_forecast(
        forecasts: tuple[WeatherForecast, ...],
    ) -> WeatherForecast | None:
        return next(
            (
                forecast
                for forecast in forecasts
                if forecast.source == "nws" and forecast.periods
            ),
            None,
        )

    @classmethod
    def _forecast_table(
        cls,
        location_name: str,
        extended: tuple[DailyForecast, ...],
        nws: WeatherForecast | None,
        days: int,
    ) -> str:
        rows = [cls._daily_row(day, nws) for day in extended[:days]]
        headers = (
            "Day",
            "Conditions",
            "High",
            "Low",
            "Rain",
            "Hum",
            "Wind",
            "Source",
        )
        table = cls._table(headers, rows)
        return "\n".join(
            (
                location_name,
                "",
                f"{days}-Day Forecast",
                table,
                "",
                "Humidity is the Open-Meteo daily mean from hourly values.",
                "NWS values are preferred where matching daily periods exist.",
            )
        )

    @classmethod
    def _daily_row(
        cls,
        day: DailyForecast,
        nws: WeatherForecast | None,
    ) -> tuple[str, ...]:
        periods = (
            ()
            if nws is None
            else tuple(
                period
                for period in nws.periods
                if period.start_time[:10] == day.date
            )
        )
        daytime = next((period for period in periods if period.is_daytime), None)
        nighttime = next((period for period in periods if not period.is_daytime), None)

        high = cls._period_temperature(daytime, day.high_f)
        low = cls._period_temperature(nighttime, day.low_f)
        rain_values = [
            period.precipitation_probability
            for period in periods
            if period.precipitation_probability is not None
        ]
        rain = max(rain_values) if rain_values else day.precipitation_probability
        condition_period = daytime or nighttime
        condition = (
            condition_period.short_forecast
            if condition_period and condition_period.short_forecast
            else day.condition
        )
        wind = (
            condition_period.wind_speed
            if condition_period and condition_period.wind_speed
            else cls._mph(day.wind_speed_mph)
        )
        source = "NWS+OM" if periods else "OM"

        return (
            cls._display_date(day.date),
            cls._clip(condition, 24),
            cls._degrees(high),
            cls._degrees(low),
            cls._percent(rain),
            cls._percent(day.humidity_mean_percent),
            cls._clip(wind or "--", 14),
            source,
        )

    @staticmethod
    def _period_temperature(
        period: WeatherPeriod | None,
        fallback: float | None,
    ) -> float | None:
        if period is not None and period.temperature_f is not None:
            return period.temperature_f
        return fallback

    @staticmethod
    def _table(
        headers: tuple[str, ...],
        rows: list[tuple[str, ...]],
    ) -> str:
        widths = [len(header) for header in headers]
        for row in rows:
            for index, value in enumerate(row):
                widths[index] = max(widths[index], len(value))

        border = "+-" + "-+-".join("-" * width for width in widths) + "-+"

        def render(row: tuple[str, ...]) -> str:
            cells = (
                value.ljust(widths[index])
                for index, value in enumerate(row)
            )
            return "| " + " | ".join(cells) + " |"

        lines = [border, render(headers), border]
        lines.extend(render(row) for row in rows)
        lines.append(border)
        return "\n".join(lines)

    @staticmethod
    def _thirty_day_message(location_name: str) -> str:
        return "\n".join(
            (
                location_name,
                "",
                "30-Day Outlook",
                "A 30-day outlook should use sub-seasonal ensemble guidance,",
                "not day-by-day short-range forecasts. Seasonal outlook",
                "support is intentionally not enabled yet.",
            )
        )

    @staticmethod
    def _display_date(value: str) -> str:
        try:
            return date.fromisoformat(value).strftime("%a %b %d")
        except ValueError:
            return value

    @staticmethod
    def _degrees(value: float | None) -> str:
        if value is None:
            return "--"
        return f"{value:.0f}°F"

    @staticmethod
    def _percent(value: float | None) -> str:
        if value is None:
            return "--"
        return f"{value:.0f}%"

    @staticmethod
    def _mph(value: float | None) -> str | None:
        if value is None:
            return None
        return f"{value:g} mph"

    @staticmethod
    def _clip(value: str, width: int) -> str:
        if len(value) <= width:
            return value
        return value[: width - 1] + "…"

    @staticmethod
    def _options(
        request: RequestContext,
    ) -> tuple[str, str, int, WeatherDetail] | None:
        text = request.latest_user_text
        if text is None:
            return None
        match = _WEATHER.fullmatch(text)
        if match is None:
            return None

        kind = match.group("kind").casefold()
        body = match.group("body").strip()
        days_match = _DAYS.search(body)
        days = 7
        if days_match is not None:
            days = int(days_match.group("days"))
            body = _DAYS.sub(" ", body).strip()

        detail = WeatherDetail.STANDARD
        detail_match = _DETAIL.search(body)
        if detail_match is not None:
            detail = WeatherDetail(detail_match.group("detail").casefold())
            body = _DETAIL.sub(" ", body).strip()

        if not body or days not in _FORECAST_DAYS:
            return None
        return kind, body, days, detail
