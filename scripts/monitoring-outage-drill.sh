#!/usr/bin/env bash
set -euo pipefail

project="${PORTER_ALERT_DRILL_PROJECT:-porter-alert-drill}"
porter_port="${PORTER_ALERT_DRILL_PORTER_PORT:-18003}"
prometheus_port="${PORTER_ALERT_DRILL_PROMETHEUS_PORT:-19091}"
grafana_port="${PORTER_ALERT_DRILL_GRAFANA_PORT:-13001}"
alertmanager_port="${PORTER_ALERT_DRILL_ALERTMANAGER_PORT:-19093}"
receiver_port="${PORTER_ALERT_DRILL_RECEIVER_PORT:-19087}"
grafana_user="${GRAFANA_ADMIN_USER:-admin}"
grafana_password="${GRAFANA_ADMIN_PASSWORD:-porter-alert-drill}"
firing_timeout_seconds="${PORTER_ALERT_DRILL_FIRING_TIMEOUT_SECONDS:-240}"
resolved_timeout_seconds="${PORTER_ALERT_DRILL_RESOLVED_TIMEOUT_SECONDS:-120}"

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
    local timeout_seconds="${2:-60}"
    local deadline=$((SECONDS + timeout_seconds))
    while (( SECONDS < deadline )); do
        if curl --fail --silent --show-error "${url}" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    return 1
}

event_received() {
    local expected_status="$1"
    curl --fail --silent --show-error         "http://127.0.0.1:${receiver_port}/events"         | python - "${expected_status}" <<'PY'
import json
import sys

expected_status = sys.argv[1]
payload = json.load(sys.stdin)
for event in payload["events"]:
    webhook = event.get("payload", {})
    if webhook.get("status") != expected_status:
        continue
    for alert in webhook.get("alerts", []):
        labels = alert.get("labels", {})
        if labels.get("alertname") == "PorterTargetDown":
            raise SystemExit(0)
raise SystemExit(1)
PY
}

wait_event() {
    local expected_status="$1"
    local timeout_seconds="$2"
    local deadline=$((SECONDS + timeout_seconds))
    while (( SECONDS < deadline )); do
        if event_received "${expected_status}"; then
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

wait_http "http://127.0.0.1:${porter_port}/readyz" 90
wait_http "http://127.0.0.1:${prometheus_port}/-/ready" 90
wait_http "http://127.0.0.1:${grafana_port}/api/health" 90
wait_http "http://127.0.0.1:${alertmanager_port}/-/ready" 90
wait_http "http://127.0.0.1:${receiver_port}/healthz" 90

curl --fail --silent --show-error     --request POST     "http://127.0.0.1:${receiver_port}/reset" >/dev/null

outage_started_epoch="$(date +%s)"
printf '%s\n' "Stopping Porter web service to trigger PorterTargetDown..."
"${compose[@]}" stop web >/dev/null

if ! wait_event firing "${firing_timeout_seconds}"; then
    echo "PorterTargetDown firing notification was not delivered in time." >&2
    exit 1
fi
firing_received_epoch="$(date +%s)"
detection_seconds=$((firing_received_epoch - outage_started_epoch))
printf 'Firing notification received after %ss.\n' "${detection_seconds}"

recovery_started_epoch="$(date +%s)"
printf '%s\n' "Restarting Porter web service..."
"${compose[@]}" start web >/dev/null
wait_http "http://127.0.0.1:${porter_port}/readyz" 90

if ! wait_event resolved "${resolved_timeout_seconds}"; then
    echo "PorterTargetDown resolved notification was not delivered in time." >&2
    exit 1
fi
resolved_received_epoch="$(date +%s)"
recovery_seconds=$((resolved_received_epoch - recovery_started_epoch))
printf 'Resolved notification received after %ss from restart.\n' "${recovery_seconds}"
printf '%s\n' "Outage/recovery drill passed."
