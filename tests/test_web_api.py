from pathlib import Path

from fastapi.testclient import TestClient

from porter.app import build_application
from porter.web import create_web_app
from tests.fakes import FakeProvider


def _build_test_application(
    tmp_path: Path,
    *,
    providers=(),
):
    return build_application(
        env={"PORTER_DATA_DIR": str(tmp_path)},
        home=tmp_path,
        providers=providers,
    )


def test_frontend_root_is_served(tmp_path: Path) -> None:
    application = _build_test_application(tmp_path)

    with TestClient(create_web_app(application)) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'data-porter-ui="local-chat"' in response.text


def test_frontend_assets_are_served(tmp_path: Path) -> None:
    application = _build_test_application(tmp_path)

    with TestClient(create_web_app(application)) as client:
        css_response = client.get("/styles.css")
        js_response = client.get("/app.js")

    assert css_response.status_code == 200
    assert css_response.headers["content-type"].startswith("text/css")
    assert js_response.status_code == 200
    assert "javascript" in js_response.headers["content-type"]


def test_unknown_frontend_path_returns_404(tmp_path: Path) -> None:
    application = _build_test_application(tmp_path)

    with TestClient(create_web_app(application)) as client:
        response = client.get("/not-a-porter-route")

    assert response.status_code == 404


def test_health_endpoint(tmp_path: Path) -> None:
    application = _build_test_application(tmp_path)

    with TestClient(create_web_app(application)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"status": "ok"}


def test_web_request_uses_shared_dispatcher_and_records_source(tmp_path: Path) -> None:
    application = _build_test_application(tmp_path)

    with TestClient(create_web_app(application)) as client:
        response = client.post(
            "/api/v1/requests",
            json={"text": "what time is it"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["path"] == "deterministic"
    assert payload["provider"] is None
    assert payload["model"] is None
    assert payload["tool"] is None
    assert isinstance(payload["data"]["time"], str)

    with application.database.connect() as connection:
        row = connection.execute(
            "SELECT source FROM requests WHERE request_id = ?",
            (payload["request_id"],),
        ).fetchone()

    assert row is not None
    assert row["source"] == "web"


def test_web_system_write_is_denied_before_execution(tmp_path: Path) -> None:
    application = _build_test_application(tmp_path)

    with TestClient(create_web_app(application)) as client:
        response = client.post(
            "/api/v1/requests",
            json={"text": "restart plex"},
        )

    assert response.status_code == 403
    assert response.json()["error"] == "action_not_authorized"
    assert "system_write" in response.json()["detail"]
    assert "web" in response.json()["detail"]


def test_web_defaults_to_local_inference_without_approval(tmp_path: Path) -> None:
    provider = FakeProvider(
        name="local",
        model="test-model",
        response="inference result",
    )
    application = _build_test_application(tmp_path, providers=(provider,))

    with TestClient(create_web_app(application)) as client:
        response = client.post(
            "/api/v1/requests",
            json={"text": "explain why dns uses both udp and tcp"},
        )

    assert response.status_code == 200
    assert response.json()["text"] == "inference result"
    assert response.json()["provider"] == "local"
    assert provider.calls == 1

    gaps = application.recognition_gap_repository.list_common()
    assert len(gaps) == 1
    assert gaps[0].ai_approved_count == 1
    assert gaps[0].ai_declined_count == 0


def test_web_never_calls_cloud_provider_without_cloud_authorization(
    tmp_path: Path,
) -> None:
    cloud = FakeProvider(
        name="cloud",
        model="test-model",
        is_cloud=True,
        response="should never appear",
    )
    application = _build_test_application(tmp_path, providers=(cloud,))

    with TestClient(create_web_app(application)) as client:
        response = client.post(
            "/api/v1/requests",
            json={"text": "hello", "allow_inference": True},
        )

    assert response.status_code == 503
    assert response.json()["error"] == "no_provider_available"
    assert cloud.calls == 0


def test_web_explicit_inference_decline_is_recorded(tmp_path: Path) -> None:
    provider = FakeProvider(
        name="local",
        model="test-model",
        response="unused",
    )
    application = _build_test_application(tmp_path, providers=(provider,))

    with TestClient(create_web_app(application)) as client:
        response = client.post(
            "/api/v1/requests",
            json={
                "text": "explain why dns uses both udp and tcp",
                "allow_inference": False,
            },
        )

    assert response.status_code == 409
    assert response.json()["error"] == "inference_declined"
    assert provider.calls == 0

    gaps = application.recognition_gap_repository.list_common()
    assert len(gaps) == 1
    assert gaps[0].occurrence_count == 1
    assert gaps[0].ai_approved_count == 0
    assert gaps[0].ai_declined_count == 1


def test_web_inference_can_be_approved_for_one_request(tmp_path: Path) -> None:
    provider = FakeProvider(
        name="local",
        model="test-model",
        response="inference result",
    )
    application = _build_test_application(tmp_path, providers=(provider,))

    with TestClient(create_web_app(application)) as client:
        response = client.post(
            "/api/v1/requests",
            json={
                "text": "explain why dns uses both udp and tcp",
                "allow_inference": True,
            },
        )

    assert response.status_code == 200
    assert response.json()["path"] == "inference"
    assert response.json()["provider"] == "local"
    assert response.json()["model"] == "test-model"
    assert response.json()["text"] == "inference result"
    assert provider.calls == 1

    gaps = application.recognition_gap_repository.list_common()
    assert len(gaps) == 1
    assert gaps[0].occurrence_count == 1
    assert gaps[0].ai_approved_count == 1
    assert gaps[0].ai_declined_count == 0


def test_web_session_reuses_bounded_conversation_context(tmp_path: Path) -> None:
    provider = FakeProvider(
        name="local",
        model="test-model",
        response="inference result",
    )
    application = _build_test_application(tmp_path, providers=(provider,))

    with TestClient(create_web_app(application)) as client:
        first = client.post(
            "/api/v1/requests",
            json={
                "text": "my favorite test number is 12",
                "session_id": "web-session",
                "allow_inference": True,
            },
        )
        second = client.post(
            "/api/v1/requests",
            json={
                "text": "what number did I just tell you?",
                "session_id": "web-session",
                "allow_inference": True,
            },
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert provider.requests[0].messages[-1].content == "my favorite test number is 12"
    assert [message.role for message in provider.requests[1].messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert [message.content for message in provider.requests[1].messages[1:]] == [
        "my favorite test number is 12",
        "inference result",
        "what number did I just tell you?",
    ]


def test_web_sessions_are_isolated_and_can_be_cleared(tmp_path: Path) -> None:
    provider = FakeProvider(
        name="local",
        model="test-model",
        response="inference result",
    )
    application = _build_test_application(tmp_path, providers=(provider,))

    with TestClient(create_web_app(application)) as client:
        client.post(
            "/api/v1/requests",
            json={
                "text": "remember twelve",
                "session_id": "first-session",
                "allow_inference": True,
            },
        )
        isolated = client.post(
            "/api/v1/requests",
            json={
                "text": "what did I say?",
                "session_id": "second-session",
                "allow_inference": True,
            },
        )
        cleared = client.delete("/api/v1/sessions/first-session")
        after_clear = client.post(
            "/api/v1/requests",
            json={
                "text": "what did I say?",
                "session_id": "first-session",
                "allow_inference": True,
            },
        )

    assert isolated.status_code == 200
    assert cleared.status_code == 204
    assert after_clear.status_code == 200
    assert [message.content for message in provider.requests[1].messages] == ["what did I say?"]
    assert [message.content for message in provider.requests[2].messages] == ["what did I say?"]


def test_web_request_rejects_blank_text(tmp_path: Path) -> None:
    application = _build_test_application(tmp_path)

    with TestClient(create_web_app(application)) as client:
        response = client.post(
            "/api/v1/requests",
            json={"text": "   "},
        )

    assert response.status_code == 422
