from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass

from porter.core.models import InferenceResult, RequestContext
from porter.storage.database import Database

_DEFAULT_TTL_SECONDS = 60 * 60


@dataclass(frozen=True, slots=True)
class CacheStats:
    entries: int
    hits: int
    misses: int


class InferenceCache:
    """Disposable SQLite-backed cache for provider inference results."""

    def __init__(
        self,
        database: Database,
        *,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("cache ttl_seconds must be positive")
        self._database = database
        self._ttl_seconds = ttl_seconds
        self._clock = clock or time.time
        self._ensure_schema()

    def get(
        self,
        request: RequestContext,
        *,
        provider: str,
        model: str,
    ) -> InferenceResult | None:
        cache_key = self._cache_key(request, provider=provider, model=model)
        now = int(self._clock())

        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    response_text,
                    provider,
                    model,
                    input_tokens,
                    output_tokens,
                    estimated_cost_microusd,
                    expires_at_epoch
                FROM inference_cache
                WHERE cache_key = ?
                """,
                (cache_key,),
            ).fetchone()

            if row is None:
                self._record_lookup(connection, hit=False)
                connection.commit()
                return None

            if int(row["expires_at_epoch"]) <= now:
                connection.execute(
                    "DELETE FROM inference_cache WHERE cache_key = ?",
                    (cache_key,),
                )
                self._record_lookup(connection, hit=False)
                connection.commit()
                return None

            self._record_lookup(connection, hit=True)
            connection.commit()

        return InferenceResult(
            text=str(row["response_text"]),
            provider=str(row["provider"]),
            model=str(row["model"]),
            input_tokens=row["input_tokens"],
            output_tokens=row["output_tokens"],
            estimated_cost_microusd=row["estimated_cost_microusd"],
        )

    def put(
        self,
        request: RequestContext,
        result: InferenceResult,
        *,
        provider: str,
        model: str,
    ) -> None:
        now = int(self._clock())
        cache_key = self._cache_key(request, provider=provider, model=model)

        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO inference_cache (
                    cache_key,
                    principal_id,
                    provider,
                    model,
                    response_text,
                    input_tokens,
                    output_tokens,
                    estimated_cost_microusd,
                    created_at_epoch,
                    expires_at_epoch
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    principal_id = excluded.principal_id,
                    provider = excluded.provider,
                    model = excluded.model,
                    response_text = excluded.response_text,
                    input_tokens = excluded.input_tokens,
                    output_tokens = excluded.output_tokens,
                    estimated_cost_microusd = excluded.estimated_cost_microusd,
                    created_at_epoch = excluded.created_at_epoch,
                    expires_at_epoch = excluded.expires_at_epoch
                """,
                (
                    cache_key,
                    request.principal_id,
                    result.provider,
                    result.model,
                    result.text,
                    result.input_tokens,
                    result.output_tokens,
                    result.estimated_cost_microusd,
                    now,
                    now + self._ttl_seconds,
                ),
            )
            connection.commit()

    def stats(self) -> CacheStats:
        now = int(self._clock())
        with self._database.connect() as connection:
            entry_row = connection.execute(
                """
                SELECT COUNT(*)
                FROM inference_cache
                WHERE expires_at_epoch > ?
                """,
                (now,),
            ).fetchone()
            stats_row = connection.execute(
                """
                SELECT hits, misses
                FROM inference_cache_stats
                WHERE id = 1
                """
            ).fetchone()

        return CacheStats(
            entries=int(entry_row[0]) if entry_row is not None else 0,
            hits=int(stats_row["hits"]) if stats_row is not None else 0,
            misses=int(stats_row["misses"]) if stats_row is not None else 0,
        )

    def _ensure_schema(self) -> None:
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS inference_cache (
                    cache_key TEXT PRIMARY KEY,
                    principal_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    response_text TEXT NOT NULL,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    estimated_cost_microusd INTEGER,
                    created_at_epoch INTEGER NOT NULL,
                    expires_at_epoch INTEGER NOT NULL,
                    CHECK (expires_at_epoch > created_at_epoch)
                );

                CREATE INDEX IF NOT EXISTS idx_inference_cache_expires_at
                    ON inference_cache(expires_at_epoch);

                CREATE TABLE IF NOT EXISTS inference_cache_stats (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    hits INTEGER NOT NULL DEFAULT 0,
                    misses INTEGER NOT NULL DEFAULT 0
                );

                INSERT OR IGNORE INTO inference_cache_stats (id, hits, misses)
                VALUES (1, 0, 0);
                """
            )
            self._ensure_usage_columns(connection)
            connection.commit()

    @staticmethod
    def _ensure_usage_columns(connection) -> None:
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(inference_cache)")
        }
        additions = (
            ("input_tokens", "INTEGER"),
            ("output_tokens", "INTEGER"),
            ("estimated_cost_microusd", "INTEGER"),
        )
        for column, sql_type in additions:
            if column not in columns:
                connection.execute(
                    f"ALTER TABLE inference_cache ADD COLUMN {column} {sql_type}"
                )

    @staticmethod
    def _record_lookup(connection, *, hit: bool) -> None:
        column = "hits" if hit else "misses"
        connection.execute(
            f"UPDATE inference_cache_stats SET {column} = {column} + 1 WHERE id = 1"
        )

    @staticmethod
    def _cache_key(
        request: RequestContext,
        *,
        provider: str,
        model: str,
    ) -> str:
        payload = {
            "principal_id": request.principal_id,
            "source": request.source.value,
            "session_id": request.session_id,
            "task_type": request.task_type,
            "privacy_class": request.privacy_class.value,
            "capabilities_required": sorted(
                capability.value for capability in request.capabilities_required
            ),
            "provider": provider,
            "model": model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


__all__ = ["CacheStats", "InferenceCache"]
