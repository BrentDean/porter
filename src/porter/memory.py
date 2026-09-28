from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from porter.core.models import RequestContext
from porter.intents.handlers import IntentHandler
from porter.intents.models import IntentResult, RecognizedIntent
from porter.storage.database import Database

_TOKEN_PATTERN = re.compile(r"[\w']+")
_STOP_WORDS = frozenset(
    {
        "a",
        "about",
        "am",
        "an",
        "and",
        "are",
        "do",
        "i",
        "is",
        "it",
        "me",
        "my",
        "of",
        "the",
        "to",
        "what",
        "you",
    }
)


def _normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).strip().casefold().split())


def _tokens(value: str) -> frozenset[str]:
    return frozenset(
        token
        for token in _TOKEN_PATTERN.findall(_normalize_text(value))
        if token not in _STOP_WORDS
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _to_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _from_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("stored memory timestamp is not timezone-aware")
    return parsed.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class MemoryFact:
    id: str
    principal_id: str
    content: str
    provenance_source: str
    provenance_session_id: str | None
    provenance_request_id: str
    created_at: datetime
    updated_at: datetime


class MemoryRepository:
    """Porter-owned durable memory scoped to one request principal."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def remember(self, request: RequestContext, content: str) -> MemoryFact:
        cleaned = " ".join(content.strip().split())
        if not cleaned:
            raise ValueError("memory content must not be empty")

        now = _utc_now()
        content_key = _normalize_text(cleaned)
        with self._database.connect() as connection:
            existing = connection.execute(
                """
                SELECT *
                FROM memory_facts
                WHERE principal_id = ? AND content_key = ?
                """,
                (request.principal_id, content_key),
            ).fetchone()
            if existing is not None:
                connection.execute(
                    """
                    UPDATE memory_facts
                    SET content = ?,
                        provenance_source = ?,
                        provenance_session_id = ?,
                        provenance_request_id = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        cleaned,
                        request.source.value,
                        request.session_id,
                        request.request_id,
                        _to_iso(now),
                        existing["id"],
                    ),
                )
                connection.commit()
                return MemoryFact(
                    id=existing["id"],
                    principal_id=request.principal_id,
                    content=cleaned,
                    provenance_source=request.source.value,
                    provenance_session_id=request.session_id,
                    provenance_request_id=request.request_id,
                    created_at=_from_iso(existing["created_at"]),
                    updated_at=now,
                )

            fact = MemoryFact(
                id=str(uuid4()),
                principal_id=request.principal_id,
                content=cleaned,
                provenance_source=request.source.value,
                provenance_session_id=request.session_id,
                provenance_request_id=request.request_id,
                created_at=now,
                updated_at=now,
            )
            connection.execute(
                """
                INSERT INTO memory_facts (
                    id,
                    principal_id,
                    content,
                    content_key,
                    provenance_source,
                    provenance_session_id,
                    provenance_request_id,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fact.id,
                    fact.principal_id,
                    fact.content,
                    content_key,
                    fact.provenance_source,
                    fact.provenance_session_id,
                    fact.provenance_request_id,
                    _to_iso(fact.created_at),
                    _to_iso(fact.updated_at),
                ),
            )
            connection.commit()
        return fact

    def list_for_principal(self, principal_id: str) -> tuple[MemoryFact, ...]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM memory_facts
                WHERE principal_id = ?
                ORDER BY updated_at DESC, id
                """,
                (principal_id,),
            ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def search(
        self,
        principal_id: str,
        query: str,
        *,
        limit: int = 5,
    ) -> tuple[MemoryFact, ...]:
        query_tokens = _tokens(query)
        if not query_tokens or limit <= 0:
            return ()

        candidates = self.list_for_principal(principal_id)[:100]
        ranked: list[tuple[int, datetime, MemoryFact]] = []
        for fact in candidates:
            overlap = len(query_tokens & _tokens(fact.content))
            if overlap:
                ranked.append((overlap, fact.updated_at, fact))

        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return tuple(item[2] for item in ranked[:limit])

    def forget(self, principal_id: str, content: str) -> bool:
        content_key = _normalize_text(content)
        if not content_key:
            return False
        with self._database.connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM memory_facts
                WHERE principal_id = ? AND content_key = ?
                """,
                (principal_id, content_key),
            )
            connection.commit()
        return cursor.rowcount > 0

    @staticmethod
    def _from_row(row) -> MemoryFact:
        return MemoryFact(
            id=row["id"],
            principal_id=row["principal_id"],
            content=row["content"],
            provenance_source=row["provenance_source"],
            provenance_session_id=row["provenance_session_id"],
            provenance_request_id=row["provenance_request_id"],
            created_at=_from_iso(row["created_at"]),
            updated_at=_from_iso(row["updated_at"]),
        )


class MemoryRememberHandler(IntentHandler):
    intent_name = "PorterMemoryRemember"

    def __init__(self, repository: MemoryRepository) -> None:
        self._repository = repository

    async def handle(
        self,
        request: RequestContext,
        intent: RecognizedIntent,
    ) -> IntentResult:
        content = str(intent.slots.get("memory", "")).strip()
        fact = self._repository.remember(request, content)
        return IntentResult(
            text=f"I'll remember: {fact.content}",
            data={"memory_id": fact.id, "memory": fact.content},
        )


class MemoryListHandler(IntentHandler):
    intent_name = "PorterMemoryList"

    def __init__(self, repository: MemoryRepository) -> None:
        self._repository = repository

    async def handle(
        self,
        request: RequestContext,
        intent: RecognizedIntent,
    ) -> IntentResult:
        del intent
        facts = self._repository.list_for_principal(request.principal_id)
        if not facts:
            return IntentResult(text="I don't have any persistent memories for you.", data={})
        lines = ["I remember:"]
        lines.extend(f"- {fact.content}" for fact in facts)
        return IntentResult(
            text="\n".join(lines),
            data={"memories": tuple(fact.content for fact in facts)},
        )


class MemoryForgetHandler(IntentHandler):
    intent_name = "PorterMemoryForget"

    def __init__(self, repository: MemoryRepository) -> None:
        self._repository = repository

    async def handle(
        self,
        request: RequestContext,
        intent: RecognizedIntent,
    ) -> IntentResult:
        content = str(intent.slots.get("memory", "")).strip()
        deleted = self._repository.forget(request.principal_id, content)
        if not deleted:
            return IntentResult(
                text=f"I don't have that stored memory: {content}",
                data={"deleted": False},
            )
        return IntentResult(
            text=f"Forgot: {content}",
            data={"deleted": True, "memory": content},
        )
