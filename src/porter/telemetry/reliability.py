from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import ceil, floor

from porter.core.lifecycle import ExecutionOutcome
from porter.telemetry.repository import TelemetryRepository

_DEFAULT_TARGET_PERCENT = 99.5


@dataclass(frozen=True, slots=True)
class ReliabilityReport:
    window: timedelta
    target_percent: float
    succeeded: int
    failed: int
    cancelled: int
    latency_samples: int
    p50_latency_ms: float | None
    p95_latency_ms: float | None
    success_rate_percent: float | None
    allowed_errors: float
    error_budget_consumed_percent: float | None
    error_budget_remaining_percent: float | None

    @property
    def slo_requests(self) -> int:
        return self.succeeded + self.failed


class ReliabilityService:
    """Calculate SLO-style reliability from persisted request telemetry."""

    def __init__(
        self,
        repository: TelemetryRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(UTC))

    def report(
        self,
        *,
        window: timedelta,
        target_percent: float = _DEFAULT_TARGET_PERCENT,
    ) -> ReliabilityReport:
        if window <= timedelta(0):
            raise ValueError("window must be positive")
        if not 0 < target_percent < 100:
            raise ValueError("target_percent must be greater than 0 and less than 100")

        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")

        rows = self._repository.completed_requests_since(now - window)
        succeeded = sum(row.outcome is ExecutionOutcome.SUCCEEDED for row in rows)
        failed = sum(row.outcome is ExecutionOutcome.FAILED for row in rows)
        cancelled = sum(row.outcome is ExecutionOutcome.CANCELLED for row in rows)

        slo_rows = tuple(
            row
            for row in rows
            if row.outcome in {ExecutionOutcome.SUCCEEDED, ExecutionOutcome.FAILED}
        )
        latencies = sorted(
            row.latency_ms
            for row in slo_rows
            if row.latency_ms is not None
        )
        slo_requests = succeeded + failed
        allowed_errors = slo_requests * (1 - target_percent / 100)

        if slo_requests == 0:
            success_rate_percent = None
            consumed_percent = None
            remaining_percent = None
        else:
            success_rate_percent = succeeded / slo_requests * 100
            consumed_percent = failed / allowed_errors * 100
            remaining_percent = max(0.0, 100.0 - consumed_percent)

        return ReliabilityReport(
            window=window,
            target_percent=target_percent,
            succeeded=succeeded,
            failed=failed,
            cancelled=cancelled,
            latency_samples=len(latencies),
            p50_latency_ms=_percentile(latencies, 0.50),
            p95_latency_ms=_percentile(latencies, 0.95),
            success_rate_percent=success_rate_percent,
            allowed_errors=allowed_errors,
            error_budget_consumed_percent=consumed_percent,
            error_budget_remaining_percent=remaining_percent,
        )


def _percentile(values: list[int], quantile: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])

    position = (len(values) - 1) * quantile
    lower = floor(position)
    upper = ceil(position)
    if lower == upper:
        return float(values[lower])

    fraction = position - lower
    return values[lower] + (values[upper] - values[lower]) * fraction
