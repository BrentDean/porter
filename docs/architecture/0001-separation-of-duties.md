# ADR 0001: Separation of Duties

## Status

Accepted.

## Context

Porter is intended to become a private, local-first AI platform that may integrate local inference, cloud inference, Home Assistant, voice, cameras, image/video generation, tools, memory, and other external systems. Those integrations must remain replaceable and must not become the owners of orchestration or security policy.

The most important architectural requirement is that each important decision has exactly one owner.

## Decision

Porter will use the following control-plane boundaries:

- `Orchestrator` coordinates the canonical request lifecycle.
- `PolicyEngine` owns privacy and execution-permission decisions for inference.
- `ActionPolicy` owns source-based authorization for recognized deterministic actions.
- `ModelRouter` owns deterministic provider eligibility/order after policy has been evaluated.
- `ProviderRegistry` owns the set of available inference providers.
- `ProviderExecutor` owns execution attempts and approved fallback mechanics.
- `InferenceProvider` translates a canonical request to one provider protocol and translates its response back.

The initial canonical inference flow is:

```text
RequestContext
    -> PolicyEngine
    -> PolicyDecision
    -> ModelRouter
    -> RouteDecision
    -> ProviderExecutor
    -> InferenceProvider
    -> InferenceResult
```

Recognized deterministic intents cross a separate action-authorization boundary before their handler executes:

```text
RecognizedIntent
    -> IntentHandlerRegistry
    -> ActionEffect
    -> ActionPolicy
    -> IntentHandler
```

Every registered deterministic intent must have an explicit action classification. The initial classes are:

- `READ` for non-mutating deterministic operations;
- `LOCAL_WRITE` for Porter-owned local state changes such as tasks and reminders;
- `SYSTEM_WRITE` for host-level side effects such as controlling a system service.

Reads are currently allowed from every defined request source. Writes are initially authorized only from the CLI. Voice, automation, Home Assistant, web, and future request sources must receive explicit write authorization when their trust, authentication, and confirmation behavior is implemented. This keeps new interfaces fail-closed by default.

## Security invariants

1. `LOCAL_ONLY` requests cannot authorize cloud execution.
2. Cloud execution requires an explicit policy decision and explicit request permission.
3. `CLOUD_ALLOWED_REDACTED` fails closed until a real redaction stage exists.
4. Providers do not make privacy, authorization, or routing decisions.
5. The executor does not invent new providers or widen an approved route.
6. Expected external-provider failures must be translated into `ProviderError`; unexpected programming errors propagate rather than being hidden as fallback conditions.
7. Recognition of a deterministic action is not authorization to execute it.
8. Every registered deterministic intent must have an explicit `ActionEffect`; unclassified intents fail closed during registry construction.
9. Deterministic writes must cross `ActionPolicy` before their handler runs.
10. New request-source types do not silently inherit write authorization.
11. Future side-effecting tools outside deterministic intent handling must receive an equivalent explicit authorization boundary. A model proposal is not an authorization.

## Product boundary

Porter owns the control plane. Ollama, OpenAI-compatible APIs, Home Assistant, speech engines, ComfyUI, cameras, MCP servers, and other integrations are execution/data-plane dependencies behind adapters.

This prevents any single provider or integration from becoming the platform architecture.

## Consequences

The first version contains more explicit types and interfaces than a single-script assistant would require, but later providers and interfaces can be added without duplicating policy or orchestration logic.

New deterministic intents must be deliberately classified before they can be registered. New request sources must be deliberately granted write authorization rather than gaining it automatically. `LOCAL_WRITE` and `SYSTEM_WRITE` remain distinct even though both are CLI-only initially so later interfaces may safely gain Porter-local mutations without automatically receiving host-level control.

Caching, memory, generalized event systems, broader tool authorization, and additional providers remain separate capabilities that should be introduced only when their boundaries are exercised by real use cases and tests.
