from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from uuid import uuid4

from porter.core.models import Message

_DEFAULT_MAX_TURNS = 6
_ROLE_GROUNDING = (
    "Conversation history follows. Treat only user-role messages as statements "
    "made by the user. Assistant-role messages are Porter's previous replies; "
    "do not attribute their contents to the user unless the user also said them. "
    "When recalling what the user previously said, preserve the user's wording "
    "and stated value faithfully. Do not correct, normalize, reinterpret, or infer "
    "a different value unless the user explicitly asks you to do so."
)


@dataclass(slots=True)
class ConversationSession:
    """Bounded, in-memory conversation context for one interactive session."""

    max_turns: int = _DEFAULT_MAX_TURNS
    session_id: str = field(default_factory=lambda: str(uuid4()))
    _messages: deque[Message] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.max_turns <= 0:
            raise ValueError("max_turns must be positive")
        if not self.session_id.strip():
            raise ValueError("session_id must not be empty")
        self._messages = deque(maxlen=self.max_turns * 2)

    @property
    def history(self) -> tuple[Message, ...]:
        return tuple(self._messages)

    def messages_for(self, user_text: str) -> tuple[Message, ...]:
        current = Message(role="user", content=user_text)
        if not self._messages:
            return (current,)
        return (
            Message(role="system", content=_ROLE_GROUNDING),
            *self._messages,
            current,
        )

    def record_turn(self, user_text: str, assistant_text: str) -> None:
        self._messages.append(Message(role="user", content=user_text))
        self._messages.append(Message(role="assistant", content=assistant_text))

    def clear(self) -> None:
        self._messages.clear()


__all__ = ["ConversationSession"]
