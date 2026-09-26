from pathlib import Path

import pytest

from porter.app.bootstrap import build_application
from porter.app.inference import InferenceDecision
from tests.fakes import FakeProvider, make_request


@pytest.mark.asyncio
async def test_cache_hit_is_visible_in_request_telemetry(tmp_path: Path) -> None:
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
    first_request = make_request(content="cache telemetry request")
    cached_request = make_request(content="cache telemetry request")

    for request in (first_request, cached_request):
        result = await application.dispatcher.execute(
            request,
            inference_decider=lambda _request: InferenceDecision.APPROVED,
        )
        assert result.text == "cached response"

    assert provider.calls == 1

    with application.database.connect() as connection:
        request_row = connection.execute(
            """
            SELECT route_reason
            FROM requests
            WHERE request_id = ?
            """,
            (cached_request.request_id,),
        ).fetchone()
        attempt_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM provider_attempts
            WHERE request_id = ?
            """,
            (cached_request.request_id,),
        ).fetchone()

    assert request_row is not None
    assert request_row["route_reason"] == (
        "local_only_route;cache_hit=local:local-model"
    )
    assert attempt_count is not None
    assert attempt_count[0] == 0
