from pathlib import Path

import pytest

from porter.app.bootstrap import build_application
from porter.app.inference import InferenceDecision
from porter.core.exceptions import NoProviderAvailable
from porter.core.lifecycle import RuntimeLifecycle
from porter.core.models import PrivacyClass
from porter.orchestration import Orchestrator
from porter.policy import PolicyEngine
from porter.providers.executor import ProviderExecutor
from porter.providers.registry import ProviderRegistry
from porter.routing import ModelRouter
from tests.fakes import FakeProvider, make_request


@pytest.mark.resilience
@pytest.mark.asyncio
async def test_application_records_request_and_provider_fallback(
    tmp_path: Path,
) -> None:
    local = FakeProvider(
        name="local",
        model="local-model",
        fail=True,
    )
    cloud = FakeProvider(
        name="cloud",
        model="cloud-model",
        is_cloud=True,
        response="cloud response",
    )
    application = build_application(
        env={"PORTER_DATA_DIR": str(tmp_path)},
        home=tmp_path,
        providers=(local, cloud),
    )
    request = make_request(
        privacy_class=PrivacyClass.CLOUD_ALLOWED,
        allow_cloud=True,
    )

    result = await application.dispatcher.execute(
        request,
        inference_decider=lambda _request: InferenceDecision.APPROVED,
    )

    assert result.provider == "cloud"

    with application.database.connect() as connection:
        request_row = connection.execute(
            """
            SELECT route_reason, outcome, completed_at
            FROM requests
            WHERE request_id = ?
            """,
            (request.request_id,),
        ).fetchone()

        attempts = connection.execute(
            """
            SELECT
                attempt_index,
                provider,
                model,
                outcome,
                latency_ms,
                input_tokens,
                output_tokens,
                estimated_cost_microusd,
                error_classification
            FROM provider_attempts
            WHERE request_id = ?
            ORDER BY attempt_index
            """,
            (request.request_id,),
        ).fetchall()

    assert request_row is not None
    assert (
        request_row["route_reason"]
        == "local_preferred_cloud_fallback_allowed"
    )
    assert request_row["outcome"] == "succeeded"
    assert request_row["completed_at"] is not None

    assert len(attempts) == 2

    assert attempts[0]["attempt_index"] == 1
    assert attempts[0]["provider"] == "local"
    assert attempts[0]["model"] == "local-model"
    assert attempts[0]["outcome"] == "failed"
    assert attempts[0]["latency_ms"] >= 0
    assert attempts[0]["input_tokens"] is None
    assert attempts[0]["output_tokens"] is None
    assert attempts[0]["estimated_cost_microusd"] is None
    assert (
        attempts[0]["error_classification"]
        == "ProviderError"
    )

    assert attempts[1]["attempt_index"] == 2
    assert attempts[1]["provider"] == "cloud"
    assert attempts[1]["model"] == "cloud-model"
    assert attempts[1]["outcome"] == "succeeded"
    assert attempts[1]["latency_ms"] >= 0
    assert attempts[1]["input_tokens"] is None
    assert attempts[1]["output_tokens"] is None
    assert attempts[1]["estimated_cost_microusd"] is None
    assert attempts[1]["error_classification"] is None


@pytest.mark.asyncio
async def test_application_records_provider_usage_metrics(tmp_path: Path) -> None:
    provider = FakeProvider(name="local", model="local-model", response="ok")

    async def generate_with_usage(request):
        provider.calls += 1
        from porter.core.models import InferenceResult

        return InferenceResult(
            text="ok",
            provider=provider.name,
            model=provider.model,
            input_tokens=23,
            output_tokens=7,
            estimated_cost_microusd=0,
        )

    provider.generate = generate_with_usage  # type: ignore[method-assign]

    application = build_application(
        env={"PORTER_DATA_DIR": str(tmp_path)},
        home=tmp_path,
        providers=(provider,),
    )
    request = make_request()

    await application.dispatcher.execute(
        request,
        inference_decider=lambda _request: InferenceDecision.APPROVED,
    )

    with application.database.connect() as connection:
        row = connection.execute(
            """
            SELECT input_tokens, output_tokens, estimated_cost_microusd
            FROM provider_attempts
            WHERE request_id = ?
            """,
            (request.request_id,),
        ).fetchone()

    assert row is not None
    assert row["input_tokens"] == 23
    assert row["output_tokens"] == 7
    assert row["estimated_cost_microusd"] == 0


@pytest.mark.asyncio
async def test_application_records_failed_request_without_attempts(
    tmp_path: Path,
) -> None:
    application = build_application(
        env={"PORTER_DATA_DIR": str(tmp_path)},
        home=tmp_path,
    )
    request = make_request()

    with pytest.raises(NoProviderAvailable):
        await application.dispatcher.execute(
            request,
            inference_decider=lambda _request: InferenceDecision.APPROVED,
        )

    with application.database.connect() as connection:
        request_row = connection.execute(
            """
            SELECT route_reason, outcome
            FROM requests
            WHERE request_id = ?
            """,
            (request.request_id,),
        ).fetchone()

        attempt_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM provider_attempts
            WHERE request_id = ?
            """,
            (request.request_id,),
        ).fetchone()

    assert request_row is not None
    assert request_row["route_reason"] == "no_eligible_provider"
    assert request_row["outcome"] == "failed"
    assert attempt_count is not None
    assert attempt_count[0] == 0


class BrokenLifecycle(RuntimeLifecycle):
    def request_started(self, request) -> None:
        raise RuntimeError("synthetic observer failure")


@pytest.mark.resilience
@pytest.mark.asyncio
async def test_lifecycle_failure_does_not_change_runtime_result() -> None:
    provider = FakeProvider(
        name="local",
        model="test-model",
        response="success",
    )
    registry = ProviderRegistry((provider,))
    lifecycle = BrokenLifecycle()

    orchestrator = Orchestrator(
        PolicyEngine(),
        ModelRouter(registry),
        ProviderExecutor(
            registry,
            lifecycle=lifecycle,
        ),
        lifecycle=lifecycle,
    )

    result = await orchestrator.infer(make_request())

    assert result.text == "success"
    assert provider.calls == 1


def test_null_runtime_lifecycle_satisfies_contract() -> None:
    from porter.core.lifecycle import (
        NullRuntimeLifecycle,
        RuntimeLifecycle,
        SafeRuntimeLifecycle,
    )

    lifecycle: RuntimeLifecycle = NullRuntimeLifecycle()
    SafeRuntimeLifecycle(lifecycle)


@pytest.mark.asyncio
async def test_application_records_tool_execution(
    tmp_path: Path,
) -> None:
    application = build_application(
        env={"PORTER_DATA_DIR": str(tmp_path)},
        home=tmp_path,
    )
    request = make_request(
        content="what is 5+6?"
    )

    result = await application.dispatcher.execute(request)

    assert result.path.value == "tool"
    assert result.tool == "qalculate"
    assert result.text == "11"

    with application.database.connect() as connection:
        request_row = connection.execute(
            """
            SELECT execution_path, outcome, completed_at
            FROM requests
            WHERE request_id = ?
            """,
            (request.request_id,),
        ).fetchone()

        attempts = connection.execute(
            """
            SELECT
                attempt_index,
                tool,
                outcome,
                latency_ms,
                error_classification
            FROM tool_attempts
            WHERE request_id = ?
            ORDER BY attempt_index
            """,
            (request.request_id,),
        ).fetchall()

    assert request_row is not None
    assert request_row["execution_path"] == "tool"
    assert request_row["outcome"] == "succeeded"
    assert request_row["completed_at"] is not None

    assert len(attempts) == 1
    assert attempts[0]["attempt_index"] == 1
    assert attempts[0]["tool"] == "qalculate"
    assert attempts[0]["outcome"] == "succeeded"
    assert attempts[0]["latency_ms"] >= 0
    assert attempts[0]["error_classification"] is None


@pytest.mark.resilience
@pytest.mark.asyncio
async def test_telemetry_write_failure_does_not_trigger_provider_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local = FakeProvider(
        name="local",
        model="local-model",
        response="local response",
    )
    cloud = FakeProvider(
        name="cloud",
        model="cloud-model",
        is_cloud=True,
        response="cloud response",
    )
    application = build_application(
        env={"PORTER_DATA_DIR": str(tmp_path)},
        home=tmp_path,
        providers=(local, cloud),
    )

    def fail_start_provider_attempt(**kwargs) -> None:
        raise RuntimeError("telemetry database unavailable")

    monkeypatch.setattr(
        application.telemetry_repository,
        "start_provider_attempt",
        fail_start_provider_attempt,
    )

    result = await application.dispatcher.execute(
        make_request(
            privacy_class=PrivacyClass.CLOUD_ALLOWED,
            allow_cloud=True,
        ),
        inference_decider=lambda _request: InferenceDecision.APPROVED,
    )

    assert result.provider == "local"
    assert local.calls == 1
    assert cloud.calls == 0


@pytest.mark.resilience
@pytest.mark.asyncio
async def test_tool_failure_is_persisted_and_request_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = build_application(
        env={"PORTER_DATA_DIR": str(tmp_path)},
        home=tmp_path,
    )
    tool = application.tool_registry.get("qalculate")

    async def fail_execute(request) -> None:
        raise RuntimeError("synthetic tool outage")

    monkeypatch.setattr(tool, "execute", fail_execute)
    request = make_request(content="what is 5+6?")

    with pytest.raises(RuntimeError, match="synthetic tool outage"):
        await application.dispatcher.execute(request)

    with application.database.connect() as connection:
        request_row = connection.execute(
            """
            SELECT execution_path, outcome
            FROM requests
            WHERE request_id = ?
            """,
            (request.request_id,),
        ).fetchone()
        attempt = connection.execute(
            """
            SELECT outcome, latency_ms, error_classification
            FROM tool_attempts
            WHERE request_id = ?
            """,
            (request.request_id,),
        ).fetchone()

    assert request_row is not None
    assert request_row["execution_path"] == "tool"
    assert request_row["outcome"] == "failed"
    assert attempt is not None
    assert attempt["outcome"] == "failed"
    assert attempt["latency_ms"] >= 0
    assert attempt["error_classification"] == "RuntimeError"
