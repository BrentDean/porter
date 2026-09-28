# Structured operational logging

Porter emits machine-readable operational events through a dedicated stdlib logger. Structured logging is another observer of the existing runtime lifecycle alongside SQLite telemetry and Prometheus metrics; it is not authoritative application state.

## Output contract

Porter-owned operational events are emitted as one JSON object per line to the process logging stream. Each event includes:

- UTC `timestamp`;
- lowercase `level`;
- logger name;
- stable `event` name;
- event-specific operational fields.

Examples:

```json
{"event":"request.finished","execution_path":"deterministic","latency_ms":12,"level":"info","logger":"porter.operations","outcome":"succeeded","request_id":"request-123","source":"web","timestamp":"2026-09-18T00:00:00.000Z"}
{"attempt_index":2,"event":"provider.fallback.started","from_provider":"ollama","level":"info","logger":"porter.operations","model":"gpt-example","request_id":"request-456","timestamp":"2026-09-18T00:00:01.000Z","to_provider":"openai"}
```

Each executable entry point selects its default log threshold. The canonical `porter` entry point uses `WARNING`; Compose sets `PORTER_LOG_LEVEL=INFO`. An explicit `PORTER_LOG_LEVEL` value overrides the selected default.

The logger is deliberately inert when Porter is imported as a library and no process entry point has configured logging. This avoids unstructured fallback output during tests and embedded use.

## Runtime events

The request lifecycle currently emits:

- `request.started`;
- `route.selected`;
- `request.path_selected`;
- `tool.attempt.started`;
- `tool.attempt.finished`;
- `provider.attempt.started`;
- `provider.attempt.finished`;
- `provider.fallback.started` when an attempt index greater than one begins;
- `cache.lookup.finished`;
- `request.finished`.

Provider/tool completion events include latency, outcome, and error classification when the existing runtime boundary supplies it. Provider completion also includes token and estimated-cost metadata when available.

The reminder service emits:

- `service.started`;
- `service.shutdown_requested` for supported SIGINT/SIGTERM handling;
- `service.failed` with the exception class for unexpected runner failure;
- `service.stopped`.

Best-effort recognition-gap persistence failure emits `recognition_gap.persistence_failed`.

## Privacy boundary

Operational logs must not contain request message text, persistent-memory content, principal IDs, session IDs, API keys, service tokens, exception messages, or tracebacks.

Request IDs are intentionally present because logs are a correlation surface rather than a bounded-cardinality metric system. Provider/model/tool names, route reasons, execution paths, source, privacy class, outcome, latency, token counts, estimated cost, and exception class names are considered operational metadata.

If a future event needs user content for debugging, that requires a separate explicit privacy design rather than adding it to this logger.

## Failure isolation

`LoggingLifecycle` participates in `CompositeRuntimeLifecycle`, which wraps each observer in `SafeRuntimeLifecycle`. A formatter, handler, or logging observer failure therefore cannot change request routing, provider fallback, tool execution, telemetry persistence, or the returned result.

Logging is diagnostic. It must never become required application state.

## Container behavior

The Docker image uses the normal `porter web` process entry point, which configures structured Porter logging. Docker captures the process streams, so Porter JSON events are available through:

```bash
docker compose logs --tail=100 web | cat
```

`compose.yaml` passes `PORTER_LOG_LEVEL` into the container and defaults it to `INFO`.

Uvicorn remains responsible for its own server/access log format. This contract applies to Porter-owned operational events; it does not claim that third-party runtime logs are JSON.

## Relationship to metrics and telemetry

The three operational surfaces have different purposes:

- SQLite telemetry provides durable request/attempt history and powers reliability reporting.
- Prometheus metrics provide bounded-cardinality aggregate time-series data and alerts.
- structured logs provide request-correlated event sequences and failure context.

Request IDs belong in logs and SQLite telemetry but remain prohibited as Prometheus labels.
