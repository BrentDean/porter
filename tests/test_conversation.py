import asyncio
from types import SimpleNamespace

from porter.cli.commands.ask import execute_text
from porter.conversation import ConversationSession
from porter.core.models import ExecutionPath, RequestResult


def test_conversation_session_builds_bounded_history() -> None:
    session = ConversationSession(max_turns=2, session_id="session-1")

    session.record_turn("first", "answer one")
    session.record_turn("second", "answer two")
    session.record_turn("third", "answer three")

    assert [message.content for message in session.history] == [
        "second",
        "answer two",
        "third",
        "answer three",
    ]
    assert [message.role for message in session.messages_for("follow up")] == [
        "system",
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
    ]
    assert session.messages_for("follow up")[-1].content == "follow up"


def test_conversation_session_role_grounding_distinguishes_prior_assistant_text() -> None:
    session = ConversationSession(session_id="session-1")
    session.record_turn(
        "my favorite number is 12",
        "Twelve has many mathematical and cultural properties.",
    )

    messages = session.messages_for("what did I just tell you?")

    assert messages[0].role == "system"
    assert "only user-role messages" in messages[0].content
    assert "do not attribute their contents to the user" in messages[0].content
    assert [message.role for message in messages[1:]] == [
        "user",
        "assistant",
        "user",
    ]


def test_conversation_session_grounding_preserves_literal_user_values() -> None:
    session = ConversationSession(session_id="session-1")
    session.record_turn(
        "my favorite color is mice",
        "You may have meant a pale tan or light brown color.",
    )

    messages = session.messages_for("what is my favorite color?")

    assert messages[1].content == "my favorite color is mice"
    assert "preserve the user's wording" in messages[0].content
    assert "Do not correct, normalize, reinterpret, or infer" in messages[0].content


def test_conversation_session_clear_preserves_session_identity() -> None:
    session = ConversationSession(session_id="session-1")
    session.record_turn("hello", "hi")

    session.clear()

    assert session.session_id == "session-1"
    assert session.history == ()
    assert [message.role for message in session.messages_for("fresh start")] == ["user"]


def test_execute_text_reuses_repl_conversation_context(capsys) -> None:
    requests = []

    class FakeDispatcher:
        async def execute(self, request, inference_decider=None):
            requests.append(request)
            return RequestResult(
                text=("Guido van Rossum" if len(requests) == 1 else "1991"),
                path=ExecutionPath.INFERENCE,
                provider="fake",
                model="fake-model",
            )

    application = SimpleNamespace(dispatcher=FakeDispatcher())
    session = ConversationSession(session_id="repl-session")

    assert asyncio.run(
        execute_text(
            application,  # type: ignore[arg-type]
            "Who created Python?",
            conversation=session,
        )
    ) == 0
    assert asyncio.run(
        execute_text(
            application,  # type: ignore[arg-type]
            "When did he create it?",
            conversation=session,
        )
    ) == 0

    assert requests[0].session_id == "repl-session"
    assert [message.content for message in requests[0].messages] == [
        "Who created Python?"
    ]
    assert requests[1].session_id == "repl-session"
    assert [message.role for message in requests[1].messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert [message.content for message in requests[1].messages[1:]] == [
        "Who created Python?",
        "Guido van Rossum",
        "When did he create it?",
    ]

    captured = capsys.readouterr()
    assert "Guido van Rossum" in captured.out
    assert "1991" in captured.out
