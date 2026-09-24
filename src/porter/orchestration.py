from porter.core.lifecycle import (
    NullRuntimeLifecycle,
    RuntimeLifecycle,
    SafeRuntimeLifecycle,
)
from porter.core.models import InferenceResult, RequestContext
from porter.policy import PolicyEngine
from porter.providers.executor import ProviderExecutor
from porter.routing import ModelRouter


class Orchestrator:
    def __init__(
        self,
        policy: PolicyEngine,
        router: ModelRouter,
        executor: ProviderExecutor,
        lifecycle: RuntimeLifecycle | None = None,
    ) -> None:
        self._policy = policy
        self._router = router
        self._executor = executor
        self._lifecycle = SafeRuntimeLifecycle(
            lifecycle or NullRuntimeLifecycle()
        )

    async def infer(self, request: RequestContext) -> InferenceResult:
        policy_decision = self._policy.evaluate(request)
        route_decision = self._router.route(
            request,
            policy_decision,
        )
        self._lifecycle.route_selected(
            request.request_id,
            route_decision.reason,
        )

        return await self._executor.execute(
            request,
            route_decision,
        )


__all__ = ["Orchestrator"]
