#!/usr/bin/env bash
set -euo pipefail

image="${PORTER_CONTAINER_IMAGE:-porter:ci}"
container="${PORTER_CONTAINER_NAME:-porter-container-smoke}"
volume="${PORTER_CONTAINER_VOLUME:-porter-container-smoke-data}"
host_port="${PORTER_CONTAINER_PORT:-18000}"
base_url="http://127.0.0.1:${host_port}"

cleanup_container() {
    docker rm -f "${container}" >/dev/null 2>&1 || true
}

cleanup_all() {
    cleanup_container
    docker volume rm "${volume}" >/dev/null 2>&1 || true
}

wait_ready() {
    for _ in {1..30}; do
        if curl --fail --silent "${base_url}/readyz" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done

    docker logs "${container}" | cat
    return 1
}

trap cleanup_all EXIT

cleanup_all
docker volume create "${volume}" >/dev/null

docker run --detach \
    --name "${container}" \
    --publish "127.0.0.1:${host_port}:8000" \
    --volume "${volume}:/var/lib/porter" \
    "${image}" >/dev/null

wait_ready

health_status="$(docker inspect --format '{{.State.Health.Status}}' "${container}")"
if [[ "${health_status}" != "healthy" ]]; then
    for _ in {1..35}; do
        health_status="$(docker inspect --format '{{.State.Health.Status}}' "${container}")"
        [[ "${health_status}" == "healthy" ]] && break
        sleep 1
    done
fi
[[ "${health_status}" == "healthy" ]]

runtime_uid="$(docker exec "${container}" id -u)"
[[ "${runtime_uid}" != "0" ]]

curl --fail --silent --show-error \
    --header "Content-Type: application/json" \
    --data '{"text":"what is 5+6?"}' \
    "${base_url}/api/v1/requests" >/dev/null

container_logs="$(docker logs "${container}" 2>&1)"
grep -F '"event":"request.finished"' <<<"${container_logs}"
grep -F '"execution_path":"tool"' <<<"${container_logs}"
if grep -F 'what is 5+6?' <<<"${container_logs}" >/dev/null; then
    echo "request content leaked into container logs" >&2
    exit 1
fi

cleanup_container

docker run --detach \
    --name "${container}" \
    --publish "127.0.0.1:${host_port}:8000" \
    --volume "${volume}:/var/lib/porter" \
    "${image}" >/dev/null

wait_ready

report="$(docker exec "${container}" porter reliability --window 24h)"
printf '%s\n' "${report}"

grep -Eq 'SLO requests: [1-9][0-9]*' <<<"${report}"
