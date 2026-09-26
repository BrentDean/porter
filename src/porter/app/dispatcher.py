from __future__ import annotations

import asyncio
from dataclasses import replace
from time import perf_counter_ns

from porter.app.inference import (
    InferenceDecider,
    InferenceDecision,
    InferenceGate,
)
from porter.core.exceptions import (
    ActionNotAuthorized,
    InferenceConfirmationRequired,
    InferenceDeclined,
)
from porter.core.lifecycle import (
    ExecutionOutcome,
    NullRuntimeLifecycle,
    RuntimeLifecycle,
    SafeRuntimeLifecycle,
)
from porter.core.models import (
    Capability,
    ExecutionPath,
    Message,
    RequestContext,
    RequestResult,
)
from porter.intents.executor import DeterministicIntentExecutor
from porter.memory import MemoryRepository
from porter.orchestration import Orchestrator
from porter.tools.executor import ToolExecutor


class RequestDispatcher:
    def __init__(
        self,
        deterministic_executor: DeterministicIntentExecutor,
        tool_executor: ToolExecutor,
        orchestrator: Orchestrator,
        lifecycle: RuntimeLifecycle | None = None,
        inference_gate: InferenceGate | None = None,
        memory_repository: MemoryRepository | None = None,
    ) -> None:
        self._deterministic_executor = deterministic_executor
        self._tool_executor = tool_executor
        self._orchestrator = orchestrator
        self._lifecycle = SafeRuntimeLifecycle(
            lifecycle or NullRuntimeLifecycle()
        )
        self._inference_gate = inference_gate or InferenceGate()
        self._memory_repository = memory_repository

    async def execute(
        self,
        request: RequestContext,
        *,
        inference_decider: InferenceDecider | None = None,
    ) -> RequestResult:
        started_ns = perf_counter_ns()
        self._lifecycle.request_started(request)

        try:
            result = await self._dispatch(
                request,
                inference_decider=inference_decider,
            )
        except (
            asyncio.CancelledError,
            ActionNotAuthorized,
            InferenceConfirmationRequired,
            InferenceDeclined,
        ):
            self._lifecycle.request_finished(
                request.request_id,
                ExecutionOutcome.CANCELLED,
                latency_ms=self._elapsed_ms(started_ns),
            )
            raise
        except Exception:
            self._lifecycle.request_finished(
                request.request_id,
                ExecutionOutcome.FAILED,
                latency_ms=self._elapsed_ms(started_ns),
            )
            raise

        self._lifecycle.request_finished(
            request.request_id,
            ExecutionOutcome.SUCCEEDED,
            latency_ms=self._elapsed_ms(started_ns),
        )
        return result

    @staticmethod
    def _elapsed_ms(started_ns: int) -> int:
        return max(0, (perf_counter_ns() - started_ns) // 1_000_000)

    async def _dispatch(
        self,
        request: RequestContext,
        *,
        inference_decider: InferenceDecider | None,
    ) -> RequestResult:
        if request.capabilities_required == frozenset({Capability.TEXT}):
            deterministic_result = (
                await self._deterministic_executor.execute(request)
            )
            if deterministic_result is not None:
                self._lifecycle.execution_path_selected(
                    request.request_id,
                    ExecutionPath.DETERMINISTIC,
                )
                return RequestResult(
                    text=deterministic_result.text,
                    path=ExecutionPath.DETERMINISTIC,
                    data=deterministic_result.data,
                )

            tool_execution = await self._tool_executor.execute_supported(
                request
            )
            if tool_execution is not None:
                tool_name, tool_result = tool_execution

                return RequestResult(
                    text=tool_result.text,
                    path=ExecutionPath.TOOL,
                    tool=tool_name,
                    data=tool_result.data,
                )

        decision = (
            inference_decider(request)
            if inference_decider is not None
            else InferenceDecision.UNSPECIFIED
        )
        self._inference_gate.require_approval(request, decision)

        self._lifecycle.execution_path_selected(
            request.request_id,
            ExecutionPath.INFERENCE,
        )
        inference_request = self._with_persistent_memory(request)
        inference_result = await self._orchestrator.infer(inference_request)

        return RequestResult(
            text=inference_result.text,
            path=ExecutionPath.INFERENCE,
            provider=inference_result.provider,
            model=inference_result.model,
        )

    def _with_persistent_memory(self, request: RequestContext) -> RequestContext:
        if self._memory_repository is None or request.allow_cloud:
            return request

        query = request.latest_user_text
        if query is None:
            return request
        facts = self._memory_repository.search(request.principal_id, query)
        if not facts:
            return request

        memory_text = (
            "Persistent user memory. These items were explicitly stored by the user. "
            "Treat them as user-provided facts and preserve their wording:\n"
            + "\n".join(f"- {fact.content}" for fact in facts)
        )
        return replace(
            request,
            messages=(Message(role="system", content=memory_text), *request.messages),
        )

