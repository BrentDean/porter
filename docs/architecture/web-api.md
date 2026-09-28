# Local web API

Porter's web boundary is a localhost-only FastAPI process around the existing `PorterApplication` request dispatcher. It is an interface to the control plane, not a second composition root for tasks, reminders, tools, policy, or inference.

## Process boundary

`porter-web` builds the normal interactive `PorterApplication` and serves it through Uvicorn on `127.0.0.1` by default. The command intentionally exposes a port option but no host option. Deployment packaging may set `PORTER_WEB_HOST` explicitly; the supplied container image uses `0.0.0.0` only inside its network namespace, while `compose.yaml` publishes the service exclusively on host `127.0.0.1`. This version is not an authenticated LAN, Tailscale, or public-network interface.

The optional `web` dependency extra contains the web runtime so Porter's core installation does not require an HTTP framework or ASGI server.

## Endpoints

- `GET /health` remains the compatibility liveness endpoint.
- `GET /healthz` returns process liveness without probing external dependencies.
- `GET /readyz` returns readiness based on successful access to Porter's SQLite database. Ollama, cloud providers, and weather services are not readiness dependencies.
- `GET /metrics` exposes Porter-owned Prometheus metrics from the application lifecycle registry.
- `POST /api/v1/requests` creates a normal Porter request with `RequestSource.WEB` and dispatches it through the shared `RequestDispatcher`.
- `GET /` and the packaged frontend assets provide a localhost browser interface over the same request API.

The request body accepts natural-language `text`, an optional `session_id`, and nullable `allow_inference`. An omitted or null value uses local inference automatically if deterministic intents and tools do not match; `true` explicitly approves inference and `false` explicitly declines it. This field does not permit cloud execution.

## Browser UI

`porter-web` serves a small packaged HTML, CSS, and vanilla-JavaScript interface from the same FastAPI application. The frontend is deliberately thin: it does not duplicate routing, policy, intent handling, provider selection, or persistence logic.

The browser sends requests to `POST /api/v1/requests` and keeps one generated `session_id` in `sessionStorage` for the lifetime of the browser tab. Conversation messages are currently held only in the page DOM and are not restored after a reload.

The frontend has no Node/npm build step, framework runtime, CDN dependency, external font, or remote asset. FastAPI serves the packaged static files after normal API routes are registered, so API routes remain authoritative.

The browser submits normal conversational requests once, without a local-AI approval prompt. Unknown requests reach the local inference provider automatically, while recognized deterministic intents and tools still execute first. Local model failure is reported without escalating the request to cloud inference.

Backend and model-provided text is inserted as text content rather than executable markup.

## Safety behavior

Web requests do not receive write authority merely because the HTTP process is local. The existing deterministic `ActionPolicy` remains authoritative:

- read-only deterministic actions may execute;
- Porter-local writes are denied from `RequestSource.WEB`;
- host/system writes are denied from `RequestSource.WEB`.

A denied recognized action returns HTTP 403 and is not executed.

Unmatched web requests default to local inference; explicit `allow_inference: false` still returns HTTP 409 with `inference_declined`. Web requests remain `LOCAL_ONLY`, so even `allow_inference: true` cannot enable cloud execution. The inference gate still requires an explicit decision for any future cloud-eligible request.

The shared application inference gate records approved/declined recognition-gap outcomes, including implicit local approvals. Recognition-gap persistence is best-effort and cannot block an otherwise valid inference request.

## Deferred scope

This boundary deliberately does not add authentication, CORS policy, authenticated remote exposure, WebSockets, streaming, persistent browser conversation storage, or configuration mutation endpoints. Container packaging does not change that trust boundary. Remote access must wait for an explicit authentication/trust design and deliberate write-permission grants.
