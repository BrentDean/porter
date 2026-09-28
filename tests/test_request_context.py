import pytest

from porter.core.models import Capability, Message, RequestContext, RequestSource


def test_request_context_records_identity_and_origin() -> None:
    request = RequestContext(
        messages=(Message(role="user", content="hello"),),
        principal_id="local-user",
        source=RequestSource.CLI,
        session_id="session-1",
    )

    assert request.principal_id == "local-user"
    assert request.source is RequestSource.CLI
    assert request.session_id == "session-1"
    assert request.request_id


def test_request_context_allows_no_session() -> None:
    request = RequestContext(
        messages=(Message(role="user", content="hello"),),
        principal_id="local-user",
        source=RequestSource.CLI,
    )

    assert request.session_id is None


def test_request_context_rejects_empty_principal_id() -> None:
    with pytest.raises(ValueError, match="principal_id"):
        RequestContext(
            messages=(Message(role="user", content="hello"),),
            principal_id=" ",
            source=RequestSource.CLI,
        )


def test_request_context_rejects_invalid_source() -> None:
    with pytest.raises(ValueError, match="source"):
        RequestContext(
            messages=(Message(role="user", content="hello"),),
            principal_id="local-user",
            source="cli",  # type: ignore[arg-type]
        )


def test_request_context_rejects_empty_session_id() -> None:
    with pytest.raises(ValueError, match="session_id"):
        RequestContext(
            messages=(Message(role="user", content="hello"),),
            principal_id="local-user",
            source=RequestSource.CLI,
            session_id=" ",
        )


def test_request_context_accepts_typed_capabilities() -> None:
    request = RequestContext(
        messages=(Message(role="user", content="look"),),
        principal_id="local-user",
        source=RequestSource.CLI,
        capabilities_required=frozenset({Capability.VISION}),
    )

    assert request.capabilities_required == frozenset({Capability.VISION})


def test_request_context_rejects_untyped_capabilities() -> None:
    with pytest.raises(ValueError, match="capabilities_required"):
        RequestContext(
            messages=(Message(role="user", content="look"),),
            principal_id="local-user",
            source=RequestSource.CLI,
            capabilities_required=frozenset({"vision"}),  # type: ignore[arg-type]
        )


def test_request_context_requires_text_by_default() -> None:
    request = RequestContext(
        messages=(Message(role="user", content="hello"),),
        principal_id="local-user",
        source=RequestSource.CLI,
    )

    assert request.capabilities_required == frozenset({Capability.TEXT})
