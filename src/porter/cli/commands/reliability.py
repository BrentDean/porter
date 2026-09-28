from __future__ import annotations

import argparse
import re
from datetime import timedelta

from porter.telemetry.bootstrap import build_reliability_runtime
from porter.telemetry.reliability import ReliabilityReport

_WINDOW_PATTERN = re.compile(r"^(?P<value>[1-9]\d*)(?P<unit>[mhdw])$")
_WINDOW_UNITS = {
    "m": "minutes",
    "h": "hours",
    "d": "days",
    "w": "weeks",
}


def _window(value: str) -> timedelta:
    match = _WINDOW_PATTERN.fullmatch(value.strip().casefold())
    if match is None:
        raise argparse.ArgumentTypeError(
            "window must be a positive integer followed by m, h, d, or w"
        )

    amount = int(match.group("value"))
    unit = _WINDOW_UNITS[match.group("unit")]
    return timedelta(**{unit: amount})


def _target(value: str) -> float:
    try:
        target = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("target must be a percentage") from exc

    if not 0 < target < 100:
        raise argparse.ArgumentTypeError(
            "target must be greater than 0 and less than 100"
        )
    return target


def _format_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}%"


def _format_latency(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1f} ms"


def _print_report(
    report: ReliabilityReport,
    *,
    window_label: str,
) -> None:
    print("Porter reliability")
    print(f"  window: {window_label}")
    print(f"  availability target: {report.target_percent:.2f}%")
    print(f"  SLO requests: {report.slo_requests}")
    print(f"  succeeded: {report.succeeded}")
    print(f"  failed: {report.failed}")
    print(f"  cancelled (excluded): {report.cancelled}")
    print(f"  success rate: {_format_percent(report.success_rate_percent)}")
    print(f"  latency samples: {report.latency_samples}")
    print(f"  p50 latency: {_format_latency(report.p50_latency_ms)}")
    print(f"  p95 latency: {_format_latency(report.p95_latency_ms)}")
    print(f"  allowed errors: {report.allowed_errors:.2f}")
    print(f"  actual errors: {report.failed}")
    print(
        "  error budget consumed: "
        f"{_format_percent(report.error_budget_consumed_percent)}"
    )
    print(
        "  error budget remaining: "
        f"{_format_percent(report.error_budget_remaining_percent)}"
    )


def run(args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="porter reliability",
        description="Report SLO-style reliability from persisted Porter telemetry",
    )
    parser.add_argument(
        "--window",
        default="24h",
        help="lookback window such as 30m, 24h, 7d, or 2w (default: 24h)",
    )
    parser.add_argument(
        "--target",
        type=_target,
        default=99.5,
        help="availability target percentage between 0 and 100 (default: 99.5)",
    )
    parsed = parser.parse_args(args)

    try:
        window = _window(parsed.window)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))

    runtime = build_reliability_runtime()
    report = runtime.reliability_service.report(
        window=window,
        target_percent=parsed.target,
    )
    _print_report(report, window_label=parsed.window)
    return 0
