# Resilience testing

Porter keeps a deterministic resilience test slice for failure and recovery behavior that should remain stable across deployment environments.

Run it with:

```bash
pytest -q -m resilience
```

The `resilience` marker does not replace the full test suite. It provides a focused operational regression set for failure paths that are especially important when changing providers, persistence, background services, or deployment configuration.

## Covered scenarios

The marked suite currently verifies:

- provider failure falls back to the next approved provider;
- all approved providers failing exhausts the route and raises `NoProviderAvailable`;
- cache read failure degrades to live provider execution instead of failing the request;
- persisted request/provider telemetry records a successful fallback;
- lifecycle observer failure does not change a successful inference result;
- a telemetry database write failure does not cause an unrelated provider fallback;
- tool execution failure is persisted as a failed tool attempt and failed request;
- expected reminder delivery failure backs off without blocking later reminders;
- reminder retry timing is respected and a later successful retry clears retry state;
- stale reminder delivery claims recover without losing prior failure count;
- shutdown waits for an in-flight service pass to finish;
- the Unix SIGTERM/SIGINT bridge sets the graceful-stop event and restores handlers.

## Boundary

These are deterministic fault-injection tests, not production chaos experiments. They inject failures at Porter-owned boundaries and assert externally meaningful behavior and persisted recovery state.

Deployment-level resilience drills belong outside this suite. Once Porter is containerized and deployed, process termination, provider outage, disk pressure, restart, alerting, and restore drills should be exercised against the deployed system separately.
