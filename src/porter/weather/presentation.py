from __future__ import annotations

import textwrap
from enum import StrEnum

from porter.weather.consensus import CurrentSourceEvidence
from porter.weather.report import PorterWeatherReport

_REPORT_WIDTH = 78


class WeatherDetail(StrEnum):
    BRIEF = "brief"
    STANDARD = "standard"
    DETAILED = "detailed"


def render_weather_report(
    report: PorterWeatherReport,
    detail: WeatherDetail = WeatherDetail.STANDARD,
) -> str:
    if detail is WeatherDetail.BRIEF:
        return _render_brief(report)
    if detail is WeatherDetail.DETAILED:
        return _render_detailed(report)
    return _render_standard(report)


def _render_brief(report: PorterWeatherReport) -> str:
    current = report.current
    near = report.near_term
    current_parts = [
        (
            f"{_estimate_degrees(report)} "
            f"{current.condition or 'Conditions unavailable'}"
        ),
    ]
    if current.apparent_temperature_f is not None:
        current_parts.append(f"feels {_degrees(current.apparent_temperature_f)}")
    if current.humidity_percent is not None:
        current_parts.append(f"humidity {_percent(current.humidity_percent)}")
    if current.confidence.value == "low":
        evidence_range = _temperature_range(report)
        if evidence_range:
            current_parts.append(f"evidence range {evidence_range}")
    current_parts.append(f"confidence {current.confidence.value.upper()}")

    forecast_label = "high" if near.is_daytime else "low"
    forecast_parts = [f"{near.name}: {forecast_label} {_degrees(near.temperature_f)}"]
    if near.precipitation_probability is not None:
        forecast_parts.append(f"rain {_percent(near.precipitation_probability)}")

    return "\n".join(
        (
            report.location,
            "  •  ".join(current_parts),
            "  •  ".join(forecast_parts),
        )
    )


def _render_standard(report: PorterWeatherReport) -> str:
    current = report.current
    near = report.near_term
    current_panel = _panel(
        "Now — Porter estimate",
        (
            (
                f"{_estimate_degrees(report)}  "
                f"{current.condition or 'Conditions unavailable'}"
            ),
            _current_metrics(report),
            (
                f"Confidence {current.confidence.value.upper()}  •  "
                f"{_input_count_label(current.accepted_source_count)}  •  "
                f"{_family_count_label(current.accepted_family_count)}"
            ),
        ),
    )

    lines = [report.location, "", current_panel]
    if current.raw_temperature_spread_f is not None:
        lines.extend(
            (
                "",
                (
                    "Evidence spread  "
                    f"{current.raw_temperature_spread_f:g}°F"
                    + _rejection_suffix(report)
                ),
            )
        )

    if current.confidence.value == "low" or current.rejected_source_count:
        lines.append(_compact_evidence(report))

    forecast_label = "High" if near.is_daytime else "Low"
    forecast_panel = _panel(
        near.name,
        (
            (
                f"{forecast_label} {_degrees(near.temperature_f)}  "
                f"{near.short_forecast or 'Conditions unavailable'}"
            ),
            (
                f"Rain {_percent(near.precipitation_probability)}  •  "
                f"Wind {near.wind_speed or '--'}"
            ),
        ),
    )
    lines.extend(("", forecast_panel))

    source_names = {
        "nws": "NWS",
        "open-meteo": "Open-Meteo",
    }
    forecast_sources = " ↔ ".join(
        source_names.get(source, source)
        for source in near.sources
    )
    forecast_check = [forecast_sources or "Forecast source unavailable"]
    if near.temperature_spread_f is not None:
        metric = "high" if near.is_daytime else "low"
        forecast_check.append(f"Δ {metric} {near.temperature_spread_f:g}°F")
    forecast_check.append(f"confidence {near.confidence.upper()}")
    lines.extend(("", "Forecast check  " + "  •  ".join(forecast_check)))

    if near.official_outlook:
        lines.extend(("", _panel("Official NWS outlook", (near.official_outlook,))))
    return "\n".join(lines)


def _render_detailed(report: PorterWeatherReport) -> str:
    current = report.current
    standard = _render_standard(report)
    headers = ("Source", "Type", "Temp", "Dist", "Age", "Base", "Eff", "Status")
    rows = tuple(
        (
            _source_label(item),
            item.kind,
            _degrees(item.temperature_f),
            _distance(item.distance_miles),
            _age(item.age_minutes),
            f"{item.base_weight:.2f}",
            f"{item.weight:.2f}",
            "USED" if item.accepted else "DROPPED",
        )
        for item in current.evidence
    )
    evidence = _table(headers, rows)
    estimate_lines = [
        f"Weighted temperature  {current.temperature_f:.1f}°F",
        f"Confidence            {current.confidence.value.upper()}",
        f"Source families        {current.accepted_family_count}",
    ]
    if current.accepted_temperature_spread_f is not None:
        estimate_lines.append(
            f"Accepted spread       {current.accepted_temperature_spread_f:g}°F"
        )
    if current.rejected_source_count:
        estimate_lines.append(f"Rejected inputs        {current.rejected_source_count}")

    return "\n".join(
        (
            standard,
            "",
            "Current consensus details",
            evidence,
            "",
            *estimate_lines,
        )
    )


def _current_metrics(report: PorterWeatherReport) -> str:
    current = report.current
    parts: list[str] = []
    if current.apparent_temperature_f is not None:
        parts.append(f"Feels {_degrees(current.apparent_temperature_f)}")
    if current.humidity_percent is not None:
        parts.append(f"Humidity {_percent(current.humidity_percent)}")
    if current.wind_speed_mph is not None:
        direction = _cardinal(current.wind_direction_degrees)
        wind = f"{current.wind_speed_mph:.0f} mph"
        parts.append(f"Wind {direction} {wind}" if direction else f"Wind {wind}")
    return "  •  ".join(parts) if parts else "Current metrics unavailable"


def _compact_evidence(report: PorterWeatherReport) -> str:
    parts = []
    for item in report.current.evidence:
        status = "dropped" if not item.accepted else "used"
        parts.append(f"{_source_label(item)} {_degrees(item.temperature_f)} ({status})")
    return "Evidence       " + "  •  ".join(parts)


def _estimate_degrees(report: PorterWeatherReport) -> str:
    prefix = "~" if report.current.confidence.value == "low" else ""
    return prefix + _degrees(report.current.temperature_f)


def _temperature_range(report: PorterWeatherReport) -> str | None:
    temperatures = [
        item.temperature_f
        for item in report.current.evidence
        if item.temperature_f is not None
    ]
    if len(temperatures) < 2:
        return None
    return f"{min(temperatures):.0f}–{max(temperatures):.0f}°F"


def _rejection_suffix(report: PorterWeatherReport) -> str:
    count = report.current.rejected_source_count
    if not count:
        return ""
    noun = "outlier" if count == 1 else "outliers"
    return f"  •  {count} {noun} dropped"


def _input_count_label(count: int) -> str:
    noun = "input" if count == 1 else "inputs"
    return f"{count} {noun}"


def _family_count_label(count: int) -> str:
    noun = "source family" if count == 1 else "source families"
    return f"{count} {noun}"


def _source_label(item: CurrentSourceEvidence) -> str:
    if item.source == "nws-observation":
        return f"NWS {item.station_id}" if item.station_id else "NWS observation"
    if item.source == "synoptic-local-observation":
        return f"Local {item.station_id}" if item.station_id else "Local station"
    if item.source == "open-meteo-current":
        return "Open-Meteo best"
    if item.source == "open-meteo-hrrr-current":
        return "HRRR"
    if item.source == "open-meteo-nbm-current":
        return "NBM"
    if item.source == "open-meteo-ecmwf-current":
        return "ECMWF IFS"
    return item.source


def _distance(value: float | None) -> str:
    if value is None:
        return "--"
    return f"{value:.1f}mi"


def _age(value: float | None) -> str:
    if value is None:
        return "--"
    return f"{value:.0f}m"


def _cardinal(degrees_value: float | None) -> str | None:
    if degrees_value is None:
        return None
    directions = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
    return directions[round(degrees_value / 45) % len(directions)]


def _panel(title: str, lines: tuple[str, ...], *, width: int = _REPORT_WIDTH) -> str:
    inner_width = width - 2
    content_width = inner_width - 2
    label = f" {title} "
    if len(label) > inner_width:
        label = f" {_clip(title, inner_width - 2)} "

    top = "┌" + label + "─" * (inner_width - len(label)) + "┐"
    bottom = "└" + "─" * inner_width + "┘"
    rendered = [top]
    for line in lines:
        wrapped = textwrap.wrap(
            line,
            width=content_width,
            break_long_words=False,
            break_on_hyphens=False,
        ) or [""]
        for segment in wrapped:
            rendered.append(f"│ {segment.ljust(content_width)} │")
    rendered.append(bottom)
    return "\n".join(rendered)


def _table(headers: tuple[str, ...], rows: tuple[tuple[str, ...], ...]) -> str:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))
    border = "+-" + "-+-".join("-" * width for width in widths) + "-+"

    def render(row: tuple[str, ...]) -> str:
        cells = (value.ljust(widths[index]) for index, value in enumerate(row))
        return "| " + " | ".join(cells) + " |"

    lines = [border, render(headers), border]
    lines.extend(render(row) for row in rows)
    lines.append(border)
    return "\n".join(lines)


def _degrees(value: float | None) -> str:
    if value is None:
        return "--"
    return f"{value:.0f}°F"


def _percent(value: float | None) -> str:
    if value is None:
        return "--"
    return f"{value:.0f}%"


def _clip(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    return value[: width - 1] + "…"
