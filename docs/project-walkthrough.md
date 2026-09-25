# Porter: five-minute project walkthrough

This walkthrough demonstrates the current repository's application, reliability, and operations behavior. It runs locally; no public service or cloud API key is required for deterministic examples. Commands marked optional need the corresponding host integration.

## 1. Start with a deterministic request

On Debian/Ubuntu, install the external arithmetic and desktop notification clients when needed:

```bash
sudo apt-get install qalc libnotify-bin
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,tray,web]'
porter doctor
porter "what is 5+6?"
porter "what time is it"
```

These commands exercise Porter's request dispatch, deterministic tool/intent paths, and local telemetry **without an LLM**. Unmatched conversation uses local Ollama only when configured; cloud fallback requires separate explicit approval.

**Inspect:** [Request boundaries](architecture/0001-separation-of-duties.md), [deterministic execution tests](../tests/test_deterministic_intent_execution.py), [cloud authorization tests](../tests/test_inference_authorization.py).

## 2. Exercise durable timers and desktop delivery (optional Linux desktop)

Start Porter's reminder worker as a systemd **user** service and launch its graphical tray from the same logged-in desktop session:

```bash
porter service install --enable-now
porter tray install
porter tray
```

Use a separate terminal for the request:

```bash
porter "set a timer for 30 seconds"
porter "show my timers"
porter service status
```

In the tray, view the per-second countdown and timer Restart/Cancel controls. When the timer expires, the worker delivers a Porter-owned popup through its user-private Unix socket; when the tray is unavailable, delivery falls back to `notify-send`. If you do not want to keep a terminal open, KDE autostart launches the tray at the next graphical login.

**Inspect:** [Desktop delivery design](architecture/desktop-notifications.md), [service management](architecture/local-service-management.md), [timer tests](../tests/test_timer_intents.py).

## 3. Run the containerized web API and metrics

The supplied Compose configuration publishes the API only on host loopback:

```bash
cp .env.example .env
docker compose up --build -d
curl --fail http://127.0.0.1:8000/healthz
curl --fail http://127.0.0.1:8000/readyz
curl --fail http://127.0.0.1:8000/metrics
```

Submit a deterministic request to generate observable traffic:

```bash
curl --fail --silent --show-error \
  --header 'Content-Type: application/json' \
  --data '{"text":"what is 5+6?"}' \
  http://127.0.0.1:8000/api/v1/requests
```

The containerized web runtime is **not** automatically connected to a host Ollama model. This example intentionally exercises the deterministic request path.

**Inspect:** [Web API](architecture/web-api.md), [container runtime](architecture/container-runtime.md), [container smoke test](../scripts/container-smoke.sh).

## 4. Open the operations dashboard (optional)

Set a unique nonempty `GRAFANA_ADMIN_PASSWORD` in your local, untracked `.env` file first; the monitoring overlay refuses to start without one. Then run:

```bash
docker compose -f compose.yaml -f compose.monitoring.yaml up --build -d
```

Open Grafana at `http://127.0.0.1:3000` and select **Dashboards → Porter → Porter Operations**. Prometheus is available at `http://127.0.0.1:9090`. After one or two 15-second scrape intervals, request count, errors, and request latency panels should reflect API traffic. Provider/cache panels can show no data when only deterministic requests have executed.

The repository provisions the [dashboard](../ops/grafana/dashboards/porter-operations.json) and [Prometheus alert rules](../ops/prometheus/rules/porter-alerts.yml). Rules do not by themselves configure an outbound paging channel.

**Inspect:** [Monitoring runbook](architecture/monitoring-stack.md), [monitoring smoke test](../scripts/monitoring-smoke.sh).

## 5. Demonstrate recovery without overwriting the live database

From the host-installed Porter (not the Compose container), run:

```bash
porter backup create --keep 14
porter backup list
```

Copy one actual backup path from the output and substitute it below. Use a *new* recovery destination:

```bash
porter backup verify /path/to/actual-backup.db
porter backup restore /path/to/actual-backup.db --destination /path/to/new-recovery.db
```

Restore verifies the snapshot, applies supported migrations to the copy, and refuses to overwrite the active database or an existing destination. Snapshot retention and daily systemd backup scheduling are opt-in.

**Inspect:** [Recovery contract](architecture/local-data-protection.md), [backup tests](../tests/test_backup.py).

## 6. Verify the engineering contracts

```bash
ruff check .
python -m pytest -q -m resilience
python -m pytest -q
git diff --check
```

The [CI workflow](../.github/workflows/ci.yml) also tests Python 3.11/3.12 and runs container and monitoring smoke tests; the [publication-verification workflow](../.github/workflows/publication-verification.yml) checks tracked content and Git history for privacy and secret patterns.

**Boundary:** The local web endpoint has no application authentication. Keep the supplied loopback bindings; do not publish it to a LAN or the Internet without an explicit authentication and access-control design.
