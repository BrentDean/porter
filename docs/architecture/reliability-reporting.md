# Reliability reporting

Porter derives SLO-style reliability reports from its persisted SQLite request telemetry. This is a reporting layer over existing execution data, not a second source of operational truth.

## Command

```bash
porter reliability
porter reliability --window 24h
porter reliability --window 7d --target 99.5
```

The default lookback window is `24h` and the default availability target is `99.5%`. Windows accept a positive integer followed by `m`, `h`, `d`, or `w`.

## Population and outcomes

Only terminal requests completed within the selected UTC lookback window are considered.

- `succeeded` and `failed` requests form the SLO denominator.
- `cancelled` requests are reported separately and excluded from availability, latency percentiles, and error-budget calculations.
- Historical SLO requests without `latency_ms` still count toward availability but are excluded from latency percentile samples.

This prevents explicit inference declines, authorization cancellations, and similar non-service-failure outcomes from consuming the availability error budget.

## Calculations

For `N = succeeded + failed` and target fraction `T`:

```text
success_rate = succeeded / N
allowed_errors = N * (1 - T)
error_budget_consumed = failed / allowed_errors
error_budget_remaining = max(0, 1 - error_budget_consumed)
```

Error-budget consumption may exceed 100 percent. When the selected window contains no SLO requests, success rate and error-budget percentages are reported as `n/a`.

p50 and p95 are calculated from persisted `latency_ms` values for succeeded and failed requests in the SLO population using linear interpolation between ordered samples.

## Boundaries

Reliability reporting does not change routing, request execution, provider health, retries, or Prometheus metrics. It reads existing persisted telemetry through `TelemetryRepository` and performs calculations in `ReliabilityService`.

`porter reliability` uses a storage-only composition root and does not construct inference providers, weather adapters, tools, or the interactive request dispatcher.

The report is currently aggregate across Porter request sources and execution paths. Per-source or per-path SLOs can be added later if operational use demonstrates a need for them.
