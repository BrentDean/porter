# Third-Party Inventory

Porter tracks software, model weights, datasets, external services, and upstream reference projects independently. A permissive software license does not imply that associated model weights, training datasets, sentence corpora, or hosted services are usable under the same terms.

This file is also Porter's upstream reuse and provenance ledger.

## Active project tooling

| Component | Version Constraint | Role | Code License | Review Status |
|---|---|---|---|---|
| pytest | >=8 | Test runner | MIT | Preliminary |
| pytest-asyncio | >=0.23 | Async test support | Apache-2.0 | Preliminary |
| Ruff | >=0.6 | Linting | MIT | Preliminary |
| HTTPX2 | 2.9.0 | ASGI endpoint test client | BSD-3-Clause | Reviewed 2026-08-16 |

## Adopted runtime dependencies

### HassIL

- Upstream: OHF-Voice/hassil
- Audited upstream commit: `88a18ee`
- Porter version: `3.11.0`
- License: Apache-2.0
- Status: adopted runtime dependency
- Use: deterministic natural-language intent recognition
- Porter boundary: `porter.intents.PorterIntentRecognizer`
- Notes: consumed through the public package API; the research clone is not required at runtime.

### Home Assistant Intents package

- Package: `home-assistant-intents`
- Upstream packaging project: OHF-Voice/intents-package
- Porter version: `2026.7.30`
- Audited packaging commit: `4bb35a97`
- Bundled OHF-Voice/intents corpus commit: `2f08327a`
- Packaging project license: Apache-2.0
- Sentence corpus license: CC-BY-4.0
- Status: adopted runtime data dependency
- Use: packaged Home Assistant/OHF intent definitions consumed by HassIL
- Porter boundary: loaded inside `porter.intents.PorterIntentRecognizer`
- Notes: Porter enables only intent names backed by registered Porter handlers. The `2026.7.30` package tag points at packaging commit `4bb35a97`, which pins the underlying OHF-Voice/intents submodule to `2f08327a`; reference checkouts may be newer and must not be mistaken for the runtime corpus revision.

### tzlocal

- Package: `tzlocal`
- Upstream: regebro/tzlocal
- Porter version: `5.4.4`
- Audited tag commit: `42dfd052`
- License: MIT
- Status: adopted runtime dependency
- Use: discover the operating system's configured local IANA timezone as a `zoneinfo` timezone
- Porter boundary: `porter.core.clock.system_timezone`
- Notes: Porter keeps timezone discovery behind its own clock boundary. Consumers should not import `tzlocal` directly; this leaves one place to change if deployment/timezone policy changes later.

### Prometheus Python Client

- Package: `prometheus-client`
- Upstream: prometheus/client_python
- Porter version: `0.26.0`
- License: Apache-2.0 AND BSD-2-Clause
- Status: adopted runtime observability dependency
- Use: expose Porter-owned counters and latency histograms in Prometheus text format
- Porter boundary: `porter.telemetry.metrics.MetricsLifecycle` and the local `/metrics` endpoint
- Integration form: Porter uses a dedicated `CollectorRegistry`; Prometheus source is not copied into Porter.
- Cardinality rule: metric labels are bounded operational dimensions such as source, execution path, provider, tool, and cache outcome. Request IDs, principals, sessions, and prompt content are not metric labels.
- Review date: 2026-09-17

### PySide6-Essentials / Qt for Python

- Package: `PySide6-Essentials`
- Upstream: Qt for Python / The Qt Company
- Porter version: `6.11.1`
- License: PySide6 is offered under LGPLv3/GPLv3 and commercial licensing; bundled Qt libraries remain subject to their applicable Qt licensing terms.
- Status: optional desktop UI dependency through Porter's `tray` extra
- Use: cross-desktop system-tray icon and reminder menu through `QSystemTrayIcon`, with KDE supported through the StatusNotifierItem system tray implementation
- Porter boundary: `porter.tray.qt_app.PorterTrayController`
- Integration form: Porter uses the public Qt for Python API; Qt/PySide source is not copied into Porter.
- CI approach: GitHub Actions installs the optional `tray` extra and exercises the menu through Qt's offscreen platform without requiring a graphical system tray.
- Review date: 2026-08-15
- Release note: preserve the optional dependency boundary and perform a dedicated Qt/PySide redistribution review before bundling a desktop binary or Qt libraries with Porter.

### FastAPI

- Package: `fastapi`
- Upstream: fastapi/fastapi
- Porter version: `0.141.1`
- License: MIT
- Status: optional web runtime dependency through Porter's `web` extra
- Use: typed ASGI HTTP boundary for Porter's local web API
- Porter boundary: `porter.web.app.create_web_app`
- Integration form: Porter uses FastAPI's public application, routing, validation, encoder, and response APIs; FastAPI source is not copied into Porter.
- Network scope: Porter's `porter web` process defaults to localhost. Deployment packaging may explicitly set `PORTER_WEB_HOST`; the supplied Docker image binds all interfaces only inside the container network namespace, while Compose publishes the port on host loopback. This does not provide authentication or authorize public exposure.
- Review date: 2026-08-16
- Release note: preserve the optional dependency boundary and keep authentication/remote exposure decisions in Porter-owned policy and interface code.

### Uvicorn

- Package: `uvicorn`
- Upstream: Kludex/uvicorn
- Porter version: `0.52.3`
- Audited tag commit: `a68da608147c5f79d962352dce11de8f6e32d972`
- License: BSD-3-Clause
- Status: optional web runtime dependency through Porter's `web` extra
- Use: ASGI server process for `porter-web`
- Porter boundary: `porter.web.cli`
- Integration form: Porter calls Uvicorn's public server API; Uvicorn source is not copied into Porter.
- Network scope: Porter defaults to `127.0.0.1`. `PORTER_WEB_HOST` is an explicit deployment-only environment override used by the container image; the supplied Compose definition still publishes only on host loopback.
- Review date: 2026-08-16
- Release note: any future LAN, Tailscale, or public binding must be reviewed together with explicit authentication and authorization changes rather than treated as a server configuration-only change.

## Operational monitoring containers

### Prometheus Server

- Image: `prom/prometheus:v3.14.0`
- Upstream: prometheus/prometheus
- License: Apache-2.0
- Status: optional operational monitoring runtime
- Use: scrape Porter and host metrics, persist time series, and evaluate repository-managed alert rules
- Porter boundary: `compose.monitoring.yaml` and `ops/prometheus/`
- Network scope: published on host loopback only by the supplied Compose overlay
- Review date: 2026-09-18

### Prometheus node_exporter

- Image: `prom/node-exporter:v1.12.1`
- Upstream: prometheus/node_exporter
- License: Apache-2.0
- Status: optional Linux host-metrics runtime
- Use: expose CPU, memory, filesystem, and network metrics to Prometheus
- Porter boundary: `compose.monitoring.yaml`
- Host access: `/proc`, `/sys`, and the root filesystem are mounted read-only; the exporter is not published on a host port
- Review date: 2026-09-18

### Grafana OSS

- Image: `grafana/grafana:13.2.2`
- Upstream: grafana/grafana
- License: AGPL-3.0
- Status: optional operational dashboard runtime
- Use: visualize Porter and host metrics through a provisioned Prometheus datasource and repository-managed dashboard
- Porter boundary: `compose.monitoring.yaml` and `ops/grafana/`
- Network scope: published on host loopback only by the supplied Compose overlay
- Privacy configuration: analytics reporting and update checks are disabled in the supplied Compose service
- Review date: 2026-09-18

## External executables and local runtimes

### Qalculate / qalc

- Upstream: Qalculate/libqalculate
- Runtime component: `qalc` command-line executable
- Porter version: not pinned; supplied by the host operating system package manager
- CLI license: GPL-2.0-or-later
- Status: adopted external local executable
- Use: deterministic arithmetic and unit conversion
- Porter boundary: `porter.tools.qalculate.QalculateTool`
- Integration form: Porter launches `qalc` as a separate subprocess and consumes stdout/stderr; Qalculate source is not copied into Porter.
- CI requirement: GitHub Actions installs the Ubuntu `qalc` package before executing tests that exercise this integration.
- Release note: installation/distribution packaging should continue to identify `qalc` as an external runtime requirement and review applicable redistribution obligations for any bundled distribution.

### libnotify / notify-send

- Upstream: GNOME/libnotify
- Runtime component: `notify-send` command-line executable
- Audited Debian 12 package: `libnotify-bin` `0.8.1-1`
- Upstream version at review time: `0.8.8`
- License: LGPL-2.1-or-later
- Status: adopted external local executable
- Use: deliver one-shot Porter reminders to a freedesktop desktop notification endpoint
- Porter boundary: `porter.notifications.notify_send.NotifySendReminderDelivery`
- Integration form: Porter launches `notify-send` as a separate subprocess with explicit argv and consumes its exit status/stdout/stderr; libnotify source is not copied into Porter and no Python libnotify binding is required.
- Delivery semantics: exit status zero means the notification endpoint accepted the request. Porter does not treat that as proof that a human read or acknowledged the notification.
- Runtime requirement: the executable must be able to reach a desktop notification daemon in the user session. Headless delivery should use another Porter-owned `ReminderDelivery` adapter rather than binding the background service itself to a graphical session.
- CI approach: unit tests inject a fake executable and do not require a graphical notification daemon.
- Review date: 2026-08-15
- Release note: installation/distribution packaging should identify `notify-send` as an external runtime requirement and review applicable LGPL redistribution obligations if libnotify is ever bundled with Porter rather than supplied by the host operating system.

### Ollama

- Upstream: ollama/ollama
- Runtime component: Ollama server/API
- Porter version: not pinned by Porter; the server is separately installed and operated
- Upstream server code license: MIT
- Status: optional external local inference runtime
- Use: local text generation through Ollama's HTTP API
- Porter boundary: `porter.providers.ollama.OllamaProvider` and `OllamaClient`
- Notes: Porter does not vendor the Ollama server. Model weights served by Ollama have their own licenses and must be reviewed separately from Ollama's server-code license.

## External weather data and hosted services

### National Weather Service API

- Service: `api.weather.gov`
- Operator: NOAA / National Weather Service
- Official documentation: `https://www.weather.gov/documentation/services-web-API`
- Status: adopted weather service
- Use: official forecasts, station discovery, station observations, and related NWS weather data
- Access terms reviewed: 2026-08-14
- Terms: NWS states that information presented through the API is intended to be open data and free to use for any purpose. The service has reasonable unpublished rate limits.
- Operational requirement: an identifying `User-Agent` is required.
- Porter boundary: `porter.weather.nws` and `porter.weather.current.NwsObservationProvider`
- Accuracy note: station observations are weighted by distance and freshness rather than treated as exact conditions at the requested point. Multiple NWS stations are one observation source family for consensus purposes.

### Open-Meteo hosted API

- Service: `api.open-meteo.com`
- Official terms: `https://open-meteo.com/en/terms`
- Official model documentation: `https://open-meteo.com/en/docs`
- Status: adopted hosted weather/model service for Porter's current personal/non-commercial use
- Use: geocoding, extended forecasts, and normalized access to numerical weather-model guidance
- Access terms reviewed: 2026-08-14
- Free hosted API restriction: non-commercial use only.
- Free hosted API limits at review time: fewer than 10,000 calls/day, 5,000 calls/hour, and 600 calls/minute.
- Data license: CC BY 4.0; attribution is required.
- Commercial note: Open-Meteo's customer API provides a commercial-use license. Open-Meteo also publishes server code for self-hosting; deployment and upstream-data terms would require a separate review before commercial use.
- Models currently requested by Porter for current-condition guidance:
  - `ncep_hrrr_conus` — NOAA HRRR, approximately 3 km, hourly updates.
  - `ncep_nbm_conus` — NOAA National Blend of Models, approximately 2.5 km, hourly updates.
  - `ecmwf_ifs` — ECMWF IFS guidance exposed by Open-Meteo.
- Consensus note: HRRR and NBM are grouped into one `noaa-model` family because they are correlated NOAA guidance and must not receive independent full voting power merely because two model products are queried. ECMWF guidance is a separate model family.
- Geography note: `OpenMeteoGeocoder` is generic and has no implicit country filter. Porter's current default `WeatherTool` explicitly requests U.S.-scoped geocoding because its composition also depends on NWS and CONUS-specific guidance. Broader geographic support should use explicit provider eligibility/composition.
- Porter boundary: `porter.weather.model_guidance`, `porter.weather.open_meteo`, `porter.weather.geocoding`, and `porter.weather.extended`
- Release constraint: the free hosted Open-Meteo endpoint is not commercially viable as currently configured. Replace it with an appropriately licensed endpoint/service or separately reviewed self-hosted path before commercial distribution or operation.

### Synoptic Data Weather API

- Service: `api.synopticdata.com`
- Operator: Synoptic Data PBC
- Official API documentation: `https://docs.synopticdata.com/services/latest`
- Official pricing/access information: `https://synopticdata.com/pricing`
- Status: optional current-observation source when `PORTER_SYNOPIC_TOKEN` is configured
- Use: nearby non-METAR surface observations for a local observation cluster
- Access terms reviewed: 2026-08-14
- Authentication: a Synoptic public API token is required for Weather API calls.
- Open Access restriction: Synoptic's no-cost Open Access program is for qualifying academic/research and other non-commercial access; commercial use requires a commercial agreement.
- Data caveat: Synoptic aggregates many upstream networks whose individual restrictions can differ. Porter therefore ignores records marked `RESTRICTED` and does not treat access to the API as blanket permission to redistribute upstream raw observations.
- QC behavior: Porter requests Synoptic QC with flagged values removed and then performs an additional local temperature-cluster outlier check. The default Synoptic API QC includes a plausibility/range check; stronger/advanced QC availability depends on the account/service tier.
- Duplicate-source rule: Synoptic ASOS/AWOS network ID `1` is excluded because Porter already receives the airport/METAR observation family through NWS and must not double-count the same physical observing network.
- Local-cluster rule: Porter requires at least two usable nearby Synoptic stations before this family participates in consensus. Multiple stations form one `local-observation` family and are distance/freshness weighted with a family influence cap.
- Porter configuration: `PORTER_SYNOPIC_TOKEN`, `PORTER_SYNOPIC_RADIUS_MILES`, `PORTER_SYNOPIC_STATION_LIMIT`, and `PORTER_SYNOPIC_WITHIN_MINUTES`.
- Porter boundary: `porter.weather.synoptic.SynopticObservationProvider`
- Release constraint: a Synoptic-backed Porter deployment must remain within the terms of the configured account and underlying datasets; replace or separately license this adapter before commercial use if the account does not permit it.

### New York State Mesonet

- Service/operator: New York State Mesonet, University at Albany
- Official data policy: `https://www.nysmesonet.org/about/data`
- Status: researched; not an active Porter runtime source yet
- Intended use: possible high-quality local observation evidence, especially precipitation and other station-specific variables
- Access terms reviewed: 2026-08-14
- Terms: data are free to the general public for personal use and available for licensing to other entities. NYS Mesonet states that its data are copyrighted and that redistribution, sharing, or selling is prohibited unless an explicit agreement provides otherwise. Some data requests may carry a cost-recovery fee.
- Porter decision: personal-use access is acceptable in principle, but Porter will not scrape, redistribute, or depend on NYS Mesonet data until a clean machine-access method and the applicable use terms are documented for that integration.
- BKLN siting note: the Brooklyn station metadata supplied during research describes a university rooftop site with WMO classifications of 5/5 for temperature/humidity, 3/5 for surface wind, 2/5 for precipitation, and 1/5 for direct/global radiation. If adopted, weighting must therefore be metric-specific rather than treating the station as uniformly authoritative.

## Upstream assistant and service references

| Component | Audited Commit | Role in Porter research | License | Current decision |
|---|---|---|---|---|
| OHF-Voice/hassil | `88a18ee` | Intent parser, grammar, slots, recognition | Apache-2.0 | Adopted package dependency; avoid a Porter fork unless needed |
| OHF-Voice/intents | `2f08327a` | Sentence corpus for time, date, weather, timers, lists, and home control | CC-BY-4.0 | Runtime corpus revision bundled by `home-assistant-intents==2026.7.30`; use newer checkouts only as explicitly recorded research references |
| home-assistant/core | `57f2e39028` | Intent handlers, todo/timer/weather behavior, Assist and integration patterns | Apache-2.0 | Selective adaptation/reference; do not import the whole runtime into Porter |
| OpenVoiceOS/ovos-core | `dc0adff5b2` | Skills, fallback, persona/LLM and voice-stack patterns | Apache-2.0 | Reference only for now |
| rhasspy/rhasspy3 | `11e8d30` | Offline assistant and local voice architecture | MIT | Reference only; archived upstream |

## Current reuse map

### Reuse directly

- HassIL for grammar-based intent recognition rather than a Porter-specific parser.
- `home-assistant-intents` data rather than maintaining a large duplicate phrase library.
- `tzlocal` only behind `porter.core.clock` for operating-system timezone discovery.
- Keep third-party types behind Porter-owned adapters.

### Selectively adapt or reference from Home Assistant

Before implementing equivalent Porter services, inspect upstream behavior for:

- intent/handler/response boundaries;
- todo and shopping-list semantics;
- timer start/cancel/increase/decrease semantics;
- weather behavior;
- entity/device patterns for future Home Assistant integration;
- Assist local-versus-generative routing;
- LLM tool exposure patterns.

Porter's current time/date handlers are Porter-native. They use upstream intent names and sentence data but do not require Home Assistant Core at runtime.

For home-control domains, prefer a Porter Home Assistant adapter over reimplementing Home Assistant's device ecosystem.

### Keep Porter-native

Porter owns:

- `RequestContext` and request identity/origin;
- shared clock/timezone and JSON-HTTP transport boundaries;
- deterministic-versus-inference request dispatch;
- intent handler contracts, registry, and execution;
- privacy classification and `PolicyEngine`;
- `ModelRouter`, `ProviderRegistry`, provider health, and `ProviderExecutor`;
- `OllamaProvider` and future provider adapters;
- lifecycle observation and telemetry;
- SQLite storage and migrations;
- task-domain behavior and planner read models;
- application composition/bootstrap.

## Upstream reference checkout layout

The research clones are outside the Porter repository and are not runtime requirements:

```text
porter-upstream/
├── hassil/
├── home-assistant-core/
├── intents/
├── ovos-core/
└── rhasspy3/
```

Treat these as read-only reference trees. When Porter needs upstream functionality, choose explicitly between a dependency, data/model dependency, supported integration, thin adapter, selective copied/derived code with provenance, or reference-only inspiration.

## Provenance requirements

When source or data is copied or substantially derived into Porter, record the upstream repository, exact commit/tag/version, source path, applicable license, local destination, Porter modifications, material type, and required notices or attribution.

## Rules

1. Record exact dependency versions, model revisions, dataset revisions, service terms, and upstream commits before release.
2. Review code, model-weight, dataset/corpus, and service terms separately.
3. Do not assume repository code terms also govern bundled models, data, sentence corpora, or hosted services.
4. Do not copy source or data from reference projects without a license and provenance review.
5. Prefer maintained dependencies, supported integrations, or narrow adapters when they preserve Porter's ownership boundaries and upgrade path.
6. If code is copied or derived, preserve required notices and record Porter modifications.
7. Perform a dedicated legal review of this inventory and transitive dependencies before commercialization.