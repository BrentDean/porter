# ADR 0002: Configuration and Persistence Foundation

## Status

Accepted.

## Context

Porter will eventually persist telemetry, cache entries, planner state, conversation state,
memories, audit events, benchmark results, and other local data. These domains must not each
invent their own database paths, SQLite settings, or schema-upgrade behavior.

Configuration has the same ownership problem. Providers and services should receive validated
settings rather than reading environment variables independently throughout the codebase.

## Decision

Porter establishes two shared plumbing boundaries before application tables are introduced:

- `ConfigLoader` owns reading environment-backed application settings.
- `PorterConfig` and nested configuration models represent validated settings.
- `Database` owns SQLite connection setup and local filesystem preparation.
- `MigrationRunner` owns schema version tracking and ordered migration application.

The initial database is SQLite because Porter is local-first and single-host today. Business
services will not embed SQLite connection lifecycle logic directly.

SQL migrations are packaged with the application and applied exactly once. The first migration
is intentionally empty of application tables so migration plumbing exists before telemetry,
planner, cache, memory, and event schemas depend on it.

## Storage defaults

Unless explicitly configured, Porter stores application data under the platform's normal user
data location:

```text
$XDG_DATA_HOME/porter
```

or, when `XDG_DATA_HOME` is unset:

```text
~/.local/share/porter
```

The following environment variables may override storage locations:

- `PORTER_DATA_DIR`
- `PORTER_DB_PATH`

## SQLite concurrency

Porter may have multiple local processes using the same SQLite database, including interactive,
background-service, desktop, and future API processes. `Database` therefore configures persistent
WAL journal mode and a five-second busy timeout for every Porter connection.

WAL improves local read/write concurrency without changing Porter's single-host storage model.
The busy timeout allows short-lived lock contention to resolve before SQLite returns a busy
error. SQLite still permits only one writer at a time, so repository transactions must remain
short and domain-level atomic updates or expected-state guards remain responsible for protecting
application invariants.

Porter's SQLite database is expected to live on a local filesystem that supports SQLite WAL
shared-memory semantics. A deployment that needs network-filesystem storage or materially
different concurrency guarantees should use a different persistence strategy behind Porter's
repository boundaries rather than weakening these connection guarantees implicitly.

## Ownership rules

Configuration loading does not create database schemas.

The database layer does not own planner, telemetry, cache, or memory semantics.

The migration runner does not decide which application data should exist; it only applies the
ordered schema definitions shipped with Porter.

Secrets must not be persisted in the primary Porter database merely because configuration uses
environment variables. Provider credentials will receive a separate explicit boundary when real
external providers are introduced.

## Consequences

Future persistence features can share one connection and migration discipline without sharing
business logic. SQLite can later be replaced behind repository boundaries if deployment needs
change, while the initial system remains simple enough to inspect and understand directly.
