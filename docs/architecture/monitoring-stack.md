# Monitoring stack

Porter's monitoring stack turns the existing `/metrics` endpoint into an operator-facing system without making monitoring authoritative application state.

The stack is defined in `compose.monitoring.yaml` and is layered on top of the normal Porter Compose runtime:

```bash
docker compose -f compose.yaml -f compose.monitoring.yaml up --build -d
```

## Components

- **Porter web** remains the application and metric source at `web:8000/metrics` inside the Compose network.
- **Prometheus** scrapes Porter, node_exporter, and itself every 15 seconds, evaluates repository-managed rules, forwards active alerts to Alertmanager, and persists time-series data in the `prometheus-data` volume.
- **Alertmanager** groups and routes Prometheus alerts and sends both firing and resolved notifications to the local webhook receiver. Alertmanager state is persisted in the `alertmanager-data` volume.
- **Local alert receiver** is a Porter-owned, standard-library HTTP service in a separate container. It remains available when the Porter web service is stopped and exposes received webhook events only on host loopback for verification.
- **node_exporter** exposes Linux host CPU, memory, filesystem, and network metrics to Prometheus. Host `/proc`, `/sys`, and the root filesystem are mounted read-only; the exporter is not published on a host port.
- **Grafana OSS** uses a provisioned Prometheus datasource and a provisioned **Porter Operations** dashboard. Grafana state is persisted in the `grafana-data` volume.

The pinned runtime versions are recorded in `THIRD_PARTY.md`.

## Network boundary

The monitoring UI is local-only by default:

- Porter: `127.0.0.1:8000`
- Prometheus: `127.0.0.1:9090`
- Alertmanager: `127.0.0.1:9093`
- local alert receiver: `127.0.0.1:9087`
- Grafana: `127.0.0.1:3000`
- node_exporter: Compose-network access only

These services are not an authentication boundary for Porter's API. Do not change the bindings to `0.0.0.0` or publish them through an unauthenticated reverse proxy merely to make the dashboards remotely reachable.

For remote administration, prefer an explicit private-access layer such as an SSH tunnel or a separately reviewed Tailscale/authenticated-proxy design.

## Dashboard

Grafana provisions the `porter-operations` dashboard from the repository. It includes:

- scrape-target health;
- Porter request count, throughput, and error rate;
- p50/p95 request latency;
- provider attempt/fallback activity;
- inference-cache outcomes and cache-hit ratio;
- host CPU and memory utilization;
- root-filesystem utilization;
- host network receive/transmit throughput.

For latency, p50 is the median observed request latency and p95 is the estimated 95th percentile from Porter's Prometheus histogram: approximately 95% of observed requests fall at or below that value. The dashboard uses p50 to show typical latency and p95 to expose slower tail behavior.

The summary-card display thresholds are intended to match the operational rules where applicable:

- request error rate: yellow at 1%, red at 5%;
- p95 request latency: yellow at 500 ms, red at 1 second;
- provider fallbacks in the selected range: yellow at 1, red at 5;
- host memory usage: yellow at 80%, red at 90%;
- root-filesystem usage: yellow at 70%, red at 80%.

A provider or cache panel showing `No data` is not automatically a failure. Porter emits those series only when inference-provider or inference-cache paths are exercised. Deterministic-only traffic can therefore populate request and latency panels while leaving provider/cache panels empty.

The dashboard uses only bounded Prometheus dimensions. Request IDs, principals, sessions, and prompt content remain excluded from metric labels.

## Alert rules

Prometheus evaluates repository-managed rules for:

- Porter scrape failure;
- Porter request error rate above 5%;
- Porter p95 request latency above 1 second;
- repeated provider fallback activity;
- node_exporter scrape failure;
- host memory above 90%;
- writable filesystem usage above 80%;
- sustained host CPU above 90%.

Prometheus forwards these alerts to the local Alertmanager service. Alertmanager groups by `alertname`, waits 5 seconds before the first notification, uses a 15-second group interval, and sends resolved notifications. The default receiver is intentionally local and secret-free: it records webhook payloads in memory for operator verification and incident drills.

The local receiver is demonstration infrastructure, not a durable paging system or incident log. Email, Slack, PagerDuty, or another external destination still requires a separate destination/secrets review.

A firing host alert describes the host condition represented by that metric; it does not by itself mean Porter is unhealthy. For example, `HostFilesystemUsageHigh` can fire for a mounted data volume above 80% usage while the Porter scrape target and application remain healthy.

## Configuration

Optional environment settings are documented in `.env.example`:

- `PROMETHEUS_PORT`
- `PROMETHEUS_RETENTION`
- `ALERTMANAGER_PORT`
- `ALERT_RECEIVER_PORT`
- `GRAFANA_PORT`
- `GRAFANA_ADMIN_USER`
- `GRAFANA_ADMIN_PASSWORD`

The monitoring overlay **requires a nonempty `GRAFANA_ADMIN_PASSWORD`** in `.env` or the environment. Generate a unique value before first use, even when binding the UI to loopback. The isolated monitoring smoke test supplies its own disposable test password. Do not use or commit real passwords in `.env.example`.

## Operator verification

After starting the monitoring stack, verify all three monitoring targets in Prometheus under **Status → Target health**:

- `porter` should report `web:8000/metrics` as `UP`;
- `node` should report `node-exporter:9100/metrics` as `UP`;
- `prometheus` should report `prometheus:9090/metrics` as `UP`.

Verify Alertmanager at `http://127.0.0.1:9093/-/ready` and the local receiver at `http://127.0.0.1:9087/healthz`. Received notification payloads are available from `http://127.0.0.1:9087/events`.

Then open Grafana and inspect **Dashboards → Porter → Porter Operations**. Host CPU, memory, and filesystem panels should begin populating immediately. Porter request panels populate after requests are sent through the containerized web runtime.

Generate deterministic test traffic with:

```bash
for i in {1..10}; do
  curl --fail --silent --show-error \
    --header 'Content-Type: application/json' \
    --data '{"text":"what is 5+6?"}' \
    http://127.0.0.1:8000/api/v1/requests >/dev/null
  sleep 2
done
```

Allow at least one or two 15-second Prometheus scrape intervals before evaluating the request panels. The **Requests in range**, **Request error rate**, request-throughput, and p50/p95 latency panels should then contain data. Provider and cache panels may remain empty because this request uses Porter's deterministic tool path.

Prometheus **Alerts** shows the current state of repository-managed alert rules. A firing rule should be investigated using its labels, instance, device, mountpoint, and value rather than treated as proof that the Porter application itself failed.

## Validation

Prometheus configuration and alert rules are checked with `promtool` in CI. The end-to-end monitoring smoke test uses an isolated Compose project and isolated volumes:

```bash
bash scripts/monitoring-smoke.sh
```

The smoke test verifies that:

1. Porter becomes ready.
2. Prometheus becomes ready.
3. Grafana becomes healthy.
4. Alertmanager becomes ready and is discovered by Prometheus.
5. The independent local receiver becomes healthy.
6. Prometheus reports the Porter, node_exporter, and Prometheus scrape targets as healthy.
7. Grafana has loaded the provisioned `porter-operations` dashboard.
8. A synthetic Alertmanager API alert is delivered to the local webhook receiver.
9. A real Porter request produces a metric that can be queried from Prometheus.

The smoke test removes only its own isolated containers and volumes. Normal Porter and monitoring data are not touched.

## Outage and recovery drill

Run the isolated incident drill from the repository root:

```bash
bash scripts/monitoring-outage-drill.sh
```

The drill uses a separate Compose project and disposable volumes. It starts the full monitoring stack, clears the local receiver, stops only the Porter `web` service, waits for the existing `PorterTargetDown` rule to satisfy its 2-minute `for:` condition, and records the first firing notification. It then restarts Porter, waits for readiness, and records the resolved notification.

The script prints two measured values:

- **detection time** — seconds from stopping Porter until the firing webhook arrives;
- **recovery notification time** — seconds from restarting Porter until the resolved webhook arrives.

With the current 15-second scrape/evaluation intervals, 2-minute alert hold, 5-second Alertmanager group wait, and 15-second group interval, these measurements are expected to include deliberate alerting delay rather than represent raw process restart time. That delay is part of the incident-response story: it trades immediate paging for resistance to transient scrape failures.

The drill is intentionally not part of every CI run because it exercises the real 2-minute production-style hold. CI instead validates both configurations and proves end-to-end Alertmanager webhook delivery with a synthetic alert.

## Persistence and teardown

For the normal monitoring stack:

```bash
docker compose -f compose.yaml -f compose.monitoring.yaml down
```

preserves `porter-data`, `prometheus-data`, `alertmanager-data`, and `grafana-data`. The local receiver keeps only in-memory drill events and has no persistent volume.

Do not add `--volumes` unless deleting all three persisted data sets is intentional.
