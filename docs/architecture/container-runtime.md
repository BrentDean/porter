# Container runtime

Porter ships a single-container web runtime for repeatable local and single-host deployment testing. The container is an operational packaging boundary around the existing Porter application; it does not introduce a second application architecture.

## Image

The root `Dockerfile`:

- uses Python 3.12 on Debian Bookworm slim;
- installs `qalc`, CA certificates, timezone data, and the minimal account-management package needed during image construction;
- installs Porter with the optional `web` extra;
- runs the final process as the unprivileged `porter` user with UID/GID 10001;
- stores application state under `/var/lib/porter`;
- listens on container port 8000;
- defines a Docker liveness check against `GET /healthz`;
- uses `SIGTERM` as the container stop signal.

The image does not contain a database, model weights, API keys, or deployment-specific configuration.

## Network boundary

Host execution remains safe by default: `porter web` binds to `127.0.0.1` unless `PORTER_WEB_HOST` is explicitly set.

The container image sets `PORTER_WEB_HOST=0.0.0.0` because a process bound only to the container loopback interface cannot receive Docker-published traffic. The supplied `compose.yaml` compensates for that internal bind by publishing port 8000 only on host `127.0.0.1`.

This is not an authenticated remote API. Do not change the Compose host binding to `0.0.0.0`, a public interface, or a public reverse proxy until an explicit access-control design exists.

## Persistence

Compose mounts the named volume `porter-data` at `/var/lib/porter`. Porter's existing `PORTER_DATA_DIR` configuration therefore keeps SQLite state outside the container writable layer.

Replacing or recreating the web container does not replace the named volume. Removing the named volume is a destructive data operation.

## Health and readiness

The image-level Docker health check uses `/healthz` for process liveness.

The supplied Compose service overrides that health check with `/readyz`, which additionally verifies access to Porter's SQLite database. External inference and weather providers are intentionally not readiness dependencies.

## Runtime hardening

The Compose service:

- runs the image-defined non-root user;
- enables `no-new-privileges`;
- drops all Linux capabilities;
- uses Docker's init process for PID 1 child reaping;
- sets a bounded stop grace period;
- uses `restart: unless-stopped`;
- keeps the published HTTP port on host loopback.

A read-only root filesystem is intentionally deferred until Porter's writable home/config behavior and every external executable have an explicit writable-path contract.

## Configuration

Copy the example only when local overrides are needed:

```bash
cp .env.example .env
```

`.env` is gitignored. It may contain deployment-specific values such as `TZ`, `PORTER_WEB_PORT`, or optional service tokens. Secrets are injected at runtime rather than copied into the image.

Environment variables remain visible to processes with permission to inspect the container. A future VPS deployment can move sensitive values to a dedicated secret-management mechanism without changing Porter's application image.

`PORTER_LOG_LEVEL` controls Porter-owned JSON operational logging and defaults to `INFO` in Compose. Docker captures the process streams; use `docker compose logs --tail=100 web | cat` to inspect recent events. Uvicorn retains its own server/access log format.

## Ollama boundary

Porter's Ollama adapter currently requires a loopback URL. A normal bridged container has its own loopback namespace, so the host's `127.0.0.1:11434` is not the container's loopback endpoint.

The supplied Compose service therefore does not inject an Ollama URL or model. Deterministic Porter behavior, persistence, health/readiness, and the web boundary work without Ollama.

Do not point `PORTER_OLLAMA_URL` at `host.docker.internal`, a bridge gateway, LAN address, or public endpoint to work around this restriction. Container-to-Ollama networking requires a separate design that preserves Porter's local-inference trust boundary explicitly rather than silently weakening `OllamaConfig`.

## Commands

Build and start the local container:

```bash
docker compose up --build -d
docker compose ps
curl --fail http://127.0.0.1:8000/healthz
curl --fail http://127.0.0.1:8000/readyz
```

Inspect logs and stop the container without deleting persisted state:

```bash
docker compose logs --tail=100 web | cat
docker compose down
```

The named `porter-data` volume remains after `docker compose down`. Do not use `docker compose down --volumes` unless deleting Porter state is intentional.

## CI smoke test

`scripts/container-smoke.sh` validates the built image by:

1. starting the image with a named data volume;
2. waiting for SQLite-backed readiness;
3. verifying the Docker liveness health check becomes healthy;
4. verifying the runtime UID is non-root;
5. generating one persisted Porter request;
6. removing the container;
7. recreating it against the same volume;
8. verifying the prior request remains visible through `porter reliability`.

GitHub Actions runs this smoke test after the Python test matrix succeeds.
