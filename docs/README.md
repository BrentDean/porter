# Porter documentation

Porter's documentation is split by purpose so implementation changes do not require rewriting every document.

## Documentation roles

- `../README.md` describes the capabilities that exist on the current default branch, operator-facing commands, runtime requirements, and the main application boundaries.
- `architecture/` records stable architectural contracts, ownership boundaries, and behavior that would be difficult to reconstruct from individual implementation files.
- `../THIRD_PARTY.md` records dependency, hosted-service, dataset, license, provenance, and adoption decisions.
- tests provide executable evidence for behavioral contracts and failure/recovery semantics.

## Architecture documents

- [Separation of duties](architecture/0001-separation-of-duties.md) — request dispatch, policy, routing, providers, lifecycle, and component ownership.
- [Configuration and persistence](architecture/0002-configuration-and-persistence.md) — validated configuration, SQLite, migrations, WAL, and persistence boundaries.
- [Web API](architecture/web-api.md) — localhost HTTP boundary, browser behavior, health/readiness/metrics endpoints, and web authorization.
- [Training corpus](architecture/training-corpus.md) — training capture, recognition gaps, grouping, review, and promotion into deterministic behavior.
- [Reliability reporting](architecture/reliability-reporting.md) — reliability population, latency percentiles, SLI/SLO calculations, and error-budget semantics.
- [Resilience testing](architecture/resilience-testing.md) — deterministic fault-injection scenarios and recovery contracts.
- [Container runtime](architecture/container-runtime.md) — Docker/Compose runtime, persistence, binding, health semantics, runtime hardening, and smoke testing.
- [Structured logging](architecture/structured-logging.md) — JSON operational events, privacy boundaries, lifecycle isolation, and log/metric/telemetry responsibilities.
- [Monitoring stack](architecture/monitoring-stack.md) — Prometheus, Grafana, node_exporter, dashboards, alert rules, persistence, and monitoring-network boundaries.
- [Local service management](architecture/local-service-management.md) — systemd reminder-service lifecycle and desktop-session tray autostart.
- [Desktop notifications](architecture/desktop-notifications.md) — tray-first reminder presentation, private local IPC, and `notify-send` fallback.
- [Local data protection](architecture/local-data-protection.md) — online SQLite backups, integrity verification, private file permissions, and the offline restore boundary.

## Documentation maintenance

For a meaningful Porter feature, documentation should be updated in the same change when the feature affects one of these surfaces:

- update `README.md` when current capabilities, commands, installation, or operator-visible behavior change;
- add or update an architecture document when a stable ownership boundary, persistence rule, security rule, reliability semantic, or execution contract changes;
- update `THIRD_PARTY.md` when adopting, replacing, or materially changing a dependency, external service, dataset, or model/runtime integration;
- update command examples when CLI behavior changes;
- keep implementation details out of architecture documents when an internal refactor does not change the contract.

Small bug fixes and internal refactors do not require documentation changes unless they correct documented behavior.

Documentation should describe the system that exists on the default branch. Planned capabilities belong in explicit roadmap material rather than being presented as already implemented.
