from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry, generate_latest

from porter.app import build_application
from porter.app.inference import InferenceDecision
from porter.core.exceptions import NoProviderAvailable
from porter.core.lifecycle import (
    CompositeRuntimeLifecycle,
    ExecutionOutcome,
    NullRuntimeLifecycle,
)
from porter.core.models import PrivacyClass
from porter.telemetry.metrics import MetricsLifecycle
from porter.web import create_web_app
from tests.fakes import FakeProvider, make_request


def _metrics_text(application) -> str:
    return generate_latest(application.metrics_registry).decode("utf-8")


def test_healthz_and_readyz_report_distinct_operational_states(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = build_application(
        env={"PORTER_DATA_DIR": str(tmp_path)},
        home=tmp_path,
    )

    with TestClient(create_web_app(application)) as client:
        health = client.get("/healthz")
        ready = client.get("/readyz")
        monkeypatch.setattr(application.database, "healthcheck", lambda: False)
        unavailable = client.get("/readyz")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}
    assert unavailable.status_code == 503
    assert unavailable.json() == {"status": "unavailable"}


def test_metrics_endpoint_exposes_request_metrics(tmp_path: Path) -> None:
    application = build_application(
        env={"PORTER_DATA_DIR": str(tmp_path)},
        home=tmp_path,
    )

    with TestClient(create_web_app(application)) as client:
        request = client.post(
            "/api/v1/requests",
            json={"text": "what time is it"},
        )
        metrics = client.get("/metrics")

    assert request.status_code == 200
    assert metrics.status_code == 200
    assert metrics.headers["content-type"].startswith("text/plain")
    assert "porter_requests_total" in metrics.text
    assert 'source="web"' in metrics.text
    assert 'path="deterministic"' in metrics.text
    assert "porter_request_duration_seconds" in metrics.text


@pytest.mark.asyncio
async def test_request_latency_is_persisted(tmp_path: Path) -> None:
    application = build_application(
        env={"PORTER_DATA_DIR": str(tmp_path)},
        home=tmp_path,
    )
    request = make_request(content="what time is it")

    await application.dispatcher.execute(request)

    with application.database.connect() as connection:
        row = connection.execute(
            "SELECT latency_ms FROM requests WHERE request_id = ?",
            (request.request_id,),
        ).fetchone()

    assert row is not None
    assert row["latency_ms"] is not None
    assert row["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_provider_fallback_and_cache_metrics_are_emitted(
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
        content="explain a routing problem",
        privacy_class=PrivacyClass.CLOUD_ALLOWED,
        allow_cloud=True,
    )

    result = await application.dispatcher.execute(
        request,
        inference_decider=lambda _request: InferenceDecision.APPROVED,
    )

    metrics = _metrics_text(application)

    assert result.provider == "cloud"
    assert 'porter_provider_attempts_total{provider="local"} 1.0' in metrics
    assert 'porter_provider_attempts_total{provider="cloud"} 1.0' in metrics
    assert 'porter_provider_attempt_failures_total{provider="local"} 1.0' in metrics
    assert 'porter_provider_fallbacks_total{provider="cloud"} 1.0' in metrics
    assert (
        'porter_inference_cache_lookups_total{outcome="miss",provider="local"} 1.0'
        in metrics
    )
    assert (
        'porter_inference_cache_lookups_total{outcome="miss",provider="cloud"} 1.0'
        in metrics
    )


@pytest.mark.asyncio
async def test_cache_hit_is_observed_without_second_provider_call(
    tmp_path: Path,
) -> None:
    provider = FakeProvider(
        name="local",
        model="local-model",
        response="cached response",
    )
    application = build_application(
        env={"PORTER_DATA_DIR": str(tmp_path)},
        home=tmp_path,
        providers=(provider,),
    )

    for _ in range(2):
        await application.dispatcher.execute(
            make_request(content="explain the same thing"),
            inference_decider=lambda _request: InferenceDecision.APPROVED,
        )

    metrics = _metrics_text(application)

    assert provider.calls == 1
    assert (
        'porter_inference_cache_lookups_total{outcome="miss",provider="local"} 1.0'
        in metrics
    )
    assert (
        'porter_inference_cache_lookups_total{outcome="hit",provider="local"} 1.0'
        in metrics
    )


@pytest.mark.asyncio
async def test_failed_request_is_counted(tmp_path: Path) -> None:
    application = build_application(
        env={"PORTER_DATA_DIR": str(tmp_path)},
        home=tmp_path,
    )

    with pytest.raises(NoProviderAvailable):
        await application.dispatcher.execute(
            make_request(content="needs inference"),
            inference_decider=lambda _request: InferenceDecision.APPROVED,
        )

    metrics = _metrics_text(application)
    assert (
        'porter_request_failures_total{path="inference",source="cli"} 1.0'
        in metrics
    )


def test_tool_metrics_capture_attempt_failure_and_duration() -> None:
    registry = CollectorRegistry()
    metrics = MetricsLifecycle(registry)

    metrics.tool_attempt_started(
        request_id="request-1",
        attempt_index=1,
        tool="synthetic",
    )
    metrics.tool_attempt_finished(
        request_id="request-1",
        attempt_index=1,
        outcome=ExecutionOutcome.FAILED,
        latency_ms=25,
        error_classification="SyntheticError",
    )

    payload = generate_latest(registry).decode("utf-8")
    assert 'porter_tool_attempts_total{tool="synthetic"} 1.0' in payload
    assert 'porter_tool_attempt_failures_total{tool="synthetic"} 1.0' in payload
    assert "porter_tool_attempt_duration_seconds" in payload


def test_composite_lifecycle_isolates_observer_failure() -> None:
    class BrokenObserver(NullRuntimeLifecycle):
        def request_started(self, request) -> None:
            raise RuntimeError("synthetic metrics failure")

    class CountingObserver(NullRuntimeLifecycle):
        def __init__(self) -> None:
            self.calls = 0

        def request_started(self, request) -> None:
            self.calls += 1

    counting = CountingObserver()
    lifecycle = CompositeRuntimeLifecycle((BrokenObserver(), counting))

    lifecycle.request_started(make_request())

    assert counting.calls == 1
