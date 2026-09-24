from pathlib import Path

import pytest

from porter.app import build_application
from porter.app.inference import InferenceDecision
from porter.core.models import Message, PrivacyClass, RequestContext, RequestSource
from tests.fakes import FakeProvider


def _request(
    text: str,
    *,
    principal_id: str = "local-user",
    source: RequestSource = RequestSource.CLI,
    session_id: str | None = "test-session",
    privacy_class: PrivacyClass = PrivacyClass.LOCAL_ONLY,
    allow_cloud: bool = False,
) -> RequestContext:
    return RequestContext(
        messages=(Message(role="user", content=text),),
        principal_id=principal_id,
        source=source,
        session_id=session_id,
        privacy_class=privacy_class,
        allow_cloud=allow_cloud,
    )


def test_memory_repository_persists_scope_and_provenance(tmp_path: Path) -> None:
    application = build_application(
        env={"PORTER_DATA_DIR": str(tmp_path)},
        home=tmp_path,
    )
    request = _request("remember that my favorite number is 12")

    fact = application.memory_repository.remember(
        request,
        "my favorite number is 12",
    )

    stored = application.memory_repository.list_for_principal("local-user")
    assert stored == (fact,)
    assert fact.provenance_source == "cli"
    assert fact.provenance_session_id == "test-session"
    assert fact.provenance_request_id == request.request_id
    assert application.memory_repository.list_for_principal("someone-else") == ()


def test_memory_survives_application_rebuild(tmp_path: Path) -> None:
    first_application = build_application(
        env={"PORTER_DATA_DIR": str(tmp_path)},
        home=tmp_path,
    )
    first_application.memory_repository.remember(
        _request("remember that my favorite number is 12"),
        "my favorite number is 12",
    )

    second_application = build_application(
        env={"PORTER_DATA_DIR": str(tmp_path)},
        home=tmp_path,
    )

    stored = second_application.memory_repository.list_for_principal("local-user")
    assert len(stored) == 1
    assert stored[0].content == "my favorite number is 12"


def test_memory_repository_deduplicates_normalized_content(tmp_path: Path) -> None:
    application = build_application(
        env={"PORTER_DATA_DIR": str(tmp_path)},
        home=tmp_path,
    )

    first = application.memory_repository.remember(
        _request("first", session_id="one"),
        "My favorite number is 12",
    )
    second = application.memory_repository.remember(
        _request("second", session_id="two"),
        "  my   favorite number IS 12  ",
    )

    assert second.id == first.id
    assert len(application.memory_repository.list_for_principal("local-user")) == 1
    assert second.provenance_session_id == "two"


@pytest.mark.asyncio
async def test_memory_commands_require_explicit_remember_that_phrase(tmp_path: Path) -> None:
    application = build_application(
        env={"PORTER_DATA_DIR": str(tmp_path)},
        home=tmp_path,
    )

    result = await application.deterministic_executor.execute(
        _request("remember twelve")
    )

    assert result is None
    assert application.memory_repository.list_for_principal("local-user") == ()


@pytest.mark.asyncio
async def test_memory_commands_remember_list_and_forget(tmp_path: Path) -> None:
    application = build_application(
        env={"PORTER_DATA_DIR": str(tmp_path)},
        home=tmp_path,
    )

    remembered = await application.dispatcher.execute(
        _request("remember that my favorite number is 12", source=RequestSource.WEB)
    )
    listed = await application.dispatcher.execute(
        _request("what do you remember about me", source=RequestSource.WEB)
    )
    forgotten = await application.dispatcher.execute(
        _request("forget that my favorite number is 12", source=RequestSource.WEB)
    )

    assert remembered.path.value == "deterministic"
    assert remembered.text == "I'll remember: my favorite number is 12"
    assert "my favorite number is 12" in listed.text
    assert forgotten.text == "Forgot: my favorite number is 12"
    assert application.memory_repository.list_for_principal("local-user") == ()


@pytest.mark.asyncio
async def test_relevant_persistent_memory_is_injected_into_local_inference(
    tmp_path: Path,
) -> None:
    provider = FakeProvider(name="local", model="test-model", response="12")
    application = build_application(
        env={"PORTER_DATA_DIR": str(tmp_path)},
        home=tmp_path,
        providers=(provider,),
    )
    application.memory_repository.remember(
        _request("remember"),
        "my favorite number is 12",
    )

    result = await application.dispatcher.execute(
        _request("what is my favorite number?", session_id=None),
        inference_decider=lambda _request: InferenceDecision.APPROVED,
    )

    assert result.text == "12"
    assert provider.calls == 1
    messages = provider.requests[0].messages
    assert messages[0].role == "system"
    assert "my favorite number is 12" in messages[0].content
    assert messages[-1].content == "what is my favorite number?"


@pytest.mark.asyncio
async def test_persistent_memory_is_not_injected_when_cloud_is_allowed(
    tmp_path: Path,
) -> None:
    provider = FakeProvider(name="local", model="test-model", response="ok")
    application = build_application(
        env={"PORTER_DATA_DIR": str(tmp_path)},
        home=tmp_path,
        providers=(provider,),
    )
    application.memory_repository.remember(
        _request("remember"),
        "my favorite number is 12",
    )

    await application.dispatcher.execute(
        _request(
            "what is my favorite number?",
            session_id=None,
            privacy_class=PrivacyClass.CLOUD_ALLOWED,
            allow_cloud=True,
        ),
        inference_decider=lambda _request: InferenceDecision.APPROVED,
    )

    assert provider.calls == 1
    assert [message.content for message in provider.requests[0].messages] == [
        "what is my favorite number?"
    ]
