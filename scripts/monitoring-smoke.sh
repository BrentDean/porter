#!/usr/bin/env bash
set -euo pipefail

project="${PORTER_MONITORING_SMOKE_PROJECT:-porter-monitoring-smoke}"
porter_port="${PORTER_MONITORING_SMOKE_PORTER_PORT:-18002}"
prometheus_port="${PORTER_MONITORING_SMOKE_PROMETHEUS_PORT:-19090}"
grafana_port="${PORTER_MONITORING_SMOKE_GRAFANA_PORT:-13000}"
alertmanager_port="${PORTER_MONITORING_SMOKE_ALERTMANAGER_PORT:-19093}"
receiver_port="${PORTER_MONITORING_SMOKE_RECEIVER_PORT:-19087}"
grafana_user="${GRAFANA_ADMIN_USER:-admin}"
grafana_password="${GRAFANA_ADMIN_PASSWORD:-porter-monitoring-smoke}"

export COMPOSE_PROJECT_NAME="${project}"
export PORTER_WEB_PORT="${porter_port}"
export PROMETHEUS_PORT="${prometheus_port}"
export GRAFANA_PORT="${grafana_port}"
export ALERTMANAGER_PORT="${alertmanager_port}"
export ALERT_RECEIVER_PORT="${receiver_port}"
export GRAFANA_ADMIN_USER="${grafana_user}"
export GRAFANA_ADMIN_PASSWORD="${grafana_password}"

compose=(
    docker compose
    -f compose.yaml
    -f compose.monitoring.yaml
)

cleanup() {
    "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
}

wait_http() {
    local url="$1"
    for _ in {1..60}; do
        if curl --fail --silent --show-error "${url}" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    return 1
}

trap cleanup EXIT
cleanup

"${compose[@]}" config >/dev/null
"${compose[@]}" up --build --detach

wait_http "http://127.0.0.1:${porter_port}/readyz"
wait_http "http://127.0.0.1:${prometheus_port}/-/ready"
wait_http "http://127.0.0.1:${grafana_port}/api/health"
wait_http "http://127.0.0.1:${alertmanager_port}/-/ready"
wait_http "http://127.0.0.1:${receiver_port}/healthz"

alertmanager_connected=false
for _ in {1..30}; do
    alertmanagers_json="$(curl --fail --silent --show-error \
        "http://127.0.0.1:${prometheus_port}/api/v1/alertmanagers")"
    if python - "${alertmanagers_json}" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
active = payload["data"]["activeAlertmanagers"]
raise SystemExit(0 if active else 1)
PY
    then
        alertmanager_connected=true
        break
    fi
    sleep 1
done
if [[ "${alertmanager_connected}" != "true" ]]; then
    echo "Prometheus did not discover Alertmanager." >&2
    exit 1
fi

targets_healthy=false
for _ in {1..30}; do
    targets_json="$(curl --fail --silent --show-error \
        "http://127.0.0.1:${prometheus_port}/api/v1/targets")"
    if python - "${targets_json}" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
targets = payload["data"]["activeTargets"]
health_by_job = {
    target["labels"]["job"]: target["health"]
    for target in targets
}
expected = {"porter", "node", "prometheus"}
raise SystemExit(
    0
    if expected <= health_by_job.keys()
    and all(health_by_job[job] == "up" for job in expected)
    else 1
)
PY
    then
        targets_healthy=true
        break
    fi
    sleep 1
done
if [[ "${targets_healthy}" != "true" ]]; then
    echo "Prometheus targets did not all become healthy." >&2
    exit 1
fi

dashboard_loaded=false
for _ in {1..30}; do
    if curl --fail --silent --show-error \
        --user "${grafana_user}:${grafana_password}" \
        "http://127.0.0.1:${grafana_port}/api/dashboards/uid/porter-operations" \
        | grep -F '"uid":"porter-operations"' >/dev/null; then
        dashboard_loaded=true
        break
    fi
    sleep 1
done
if [[ "${dashboard_loaded}" != "true" ]]; then
    echo "Grafana did not load the Porter operations dashboard." >&2
    exit 1
fi

curl --fail --silent --show-error \
    --request POST \
    "http://127.0.0.1:${receiver_port}/reset" >/dev/null

curl --fail --silent --show-error \
    --header "Content-Type: application/json" \
    --data '[{"labels":{"alertname":"PorterMonitoringSmoke","severity":"info"},"annotations":{"summary":"monitoring smoke alert"}}]' \
    "http://127.0.0.1:${alertmanager_port}/api/v2/alerts" >/dev/null

notification_delivered=false
for _ in {1..30}; do
    events_json="$(curl --fail --silent --show-error \
        "http://127.0.0.1:${receiver_port}/events")"
    if python - "${events_json}" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
for event in payload["events"]:
    webhook = event.get("payload", {})
    for alert in webhook.get("alerts", []):
        if alert.get("labels", {}).get("alertname") == "PorterMonitoringSmoke":
            raise SystemExit(0)
raise SystemExit(1)
PY
    then
        notification_delivered=true
        break
    fi
    sleep 1
done
if [[ "${notification_delivered}" != "true" ]]; then
    echo "Alertmanager did not deliver the smoke alert to the local receiver." >&2
    exit 1
fi

curl --fail --silent --show-error \
    --header "Content-Type: application/json" \
    --data '{"text":"what is 5+6?"}' \
    "http://127.0.0.1:${porter_port}/api/v1/requests" >/dev/null

for _ in {1..20}; do
    query_result="$(curl --fail --silent --show-error \
        --get \
        --data-urlencode 'query=porter_requests_total' \
        "http://127.0.0.1:${prometheus_port}/api/v1/query")"
    if grep -F '"result":[' <<<"${query_result}" >/dev/null \
        && ! grep -F '"result":[]' <<<"${query_result}" >/dev/null; then
        printf '%s\n' "Monitoring smoke test passed."
        exit 0
    fi
    sleep 1
done

echo "Porter request metric was not queryable from Prometheus." >&2
exit 1
