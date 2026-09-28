from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from porter.core.lifecycle import ExecutionOutcome
from porter.core.models import ExecutionPath, RequestContext
from porter.storage.database import Database


@dataclass(frozen=True, slots=True)
class CompletedRequestTelemetry:
    outcome: ExecutionOutcome
    latency_ms: int | None


class TelemetryRepository:
    """Owns persistence operations for request and provider-attempt telemetry."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def start_request(self, request: RequestContext) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO requests (
                    request_id,
                    principal_id,
                    source,
                    session_id,
                    task_type,
                    privacy_class,
                    allow_cloud
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request.request_id,
                    request.principal_id,
                    request.source.value,
                    request.session_id,
                    request.task_type,
                    request.privacy_class.value,
                    int(request.allow_cloud),
                ),
            )
            connection.commit()

    def set_route(
        self,
        request_id: str,
        route_reason: str,
    ) -> None:
        with self._database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE requests
                SET route_reason = ?
                WHERE request_id = ?
                """,
                (route_reason, request_id),
            )
            self._require_updated(
                cursor.rowcount,
                "request",
                request_id,
            )
            connection.commit()

    def set_execution_path(
        self,
        request_id: str,
        execution_path: ExecutionPath,
    ) -> None:
        with self._database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE requests
                SET execution_path = ?
                WHERE request_id = ?
                """,
                (
                    execution_path.value,
                    request_id,
                ),
            )
            self._require_updated(
                cursor.rowcount,
                "request",
                request_id,
            )
            connection.commit()

    def finish_request(
        self,
        request_id: str,
        outcome: ExecutionOutcome,
        *,
        latency_ms: int | None = None,
    ) -> None:
        with self._database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE requests
                SET completed_at = CURRENT_TIMESTAMP,
                    outcome = ?,
                    latency_ms = ?
                WHERE request_id = ?
                  AND outcome IS NULL
                """,
                (outcome.value, latency_ms, request_id),
            )
            self._require_request_finalized(
                connection,
                cursor.rowcount,
                request_id,
            )
            connection.commit()

    def completed_requests_since(
        self,
        completed_since: datetime,
    ) -> tuple[CompletedRequestTelemetry, ...]:
        if completed_since.tzinfo is None:
            raise ValueError("completed_since must be timezone-aware")

        cutoff = completed_since.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT outcome, latency_ms
                FROM requests
                WHERE completed_at IS NOT NULL
                  AND outcome IS NOT NULL
                  AND datetime(completed_at) >= datetime(?)
                ORDER BY completed_at, request_id
                """,
                (cutoff,),
            ).fetchall()

        return tuple(
            CompletedRequestTelemetry(
                outcome=ExecutionOutcome(row["outcome"]),
                latency_ms=row["latency_ms"],
            )
            for row in rows
        )

    def start_provider_attempt(
        self,
        *,
        request_id: str,
        attempt_index: int,
        provider: str,
        model: str,
    ) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO provider_attempts (
                    request_id,
                    attempt_index,
                    provider,
                    model
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    request_id,
                    attempt_index,
                    provider,
                    model,
                ),
            )
            connection.commit()

    def finish_provider_attempt(
        self,
        *,
        request_id: str,
        attempt_index: int,
        outcome: ExecutionOutcome,
        latency_ms: int | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        estimated_cost_microusd: int | None = None,
        error_classification: str | None = None,
    ) -> None:
        with self._database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE provider_attempts
                SET completed_at = CURRENT_TIMESTAMP,
                    outcome = ?,
                    latency_ms = ?,
                    input_tokens = ?,
                    output_tokens = ?,
                    estimated_cost_microusd = ?,
                    error_classification = ?
                WHERE request_id = ?
                  AND attempt_index = ?
                  AND outcome IS NULL
                """,
                (
                    outcome.value,
                    latency_ms,
                    input_tokens,
                    output_tokens,
                    estimated_cost_microusd,
                    error_classification,
                    request_id,
                    attempt_index,
                ),
            )
            self._require_provider_attempt_finalized(
                connection,
                cursor.rowcount,
                request_id=request_id,
                attempt_index=attempt_index,
            )
            connection.commit()

    def start_tool_attempt(
        self,
        *,
        request_id: str,
        attempt_index: int,
        tool: str,
    ) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO tool_attempts (
                    request_id,
                    attempt_index,
                    tool
                )
                VALUES (?, ?, ?)
                """,
                (
                    request_id,
                    attempt_index,
                    tool,
                ),
            )
            connection.commit()

    def finish_tool_attempt(
        self,
        *,
        request_id: str,
        attempt_index: int,
        outcome: ExecutionOutcome,
        latency_ms: int | None = None,
        error_classification: str | None = None,
    ) -> None:
        with self._database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE tool_attempts
                SET completed_at = CURRENT_TIMESTAMP,
                    outcome = ?,
                    latency_ms = ?,
                    error_classification = ?
                WHERE request_id = ?
                  AND attempt_index = ?
                  AND outcome IS NULL
                """,
                (
                    outcome.value,
                    latency_ms,
                    error_classification,
                    request_id,
                    attempt_index,
                ),
            )
            self._require_tool_attempt_finalized(
                connection,
                cursor.rowcount,
                request_id=request_id,
                attempt_index=attempt_index,
            )
            connection.commit()

    @staticmethod
    def _require_updated(
        rowcount: int,
        record_type: str,
        identifier: str,
    ) -> None:
        if rowcount != 1:
            raise KeyError(
                f"{record_type} not found: {identifier}"
            )

    @staticmethod
    def _require_request_finalized(
        connection,
        rowcount: int,
        request_id: str,
    ) -> None:
        if rowcount == 1:
            return

        row = connection.execute(
            "SELECT 1 FROM requests WHERE request_id = ?",
            (request_id,),
        ).fetchone()

        if row is None:
            raise KeyError(f"request not found: {request_id}")

        raise RuntimeError(
            f"request already finalized: {request_id}"
        )

    @staticmethod
    def _require_provider_attempt_finalized(
        connection,
        rowcount: int,
        *,
        request_id: str,
        attempt_index: int,
    ) -> None:
        if rowcount == 1:
            return

        row = connection.execute(
            """
            SELECT 1
            FROM provider_attempts
            WHERE request_id = ?
              AND attempt_index = ?
            """,
            (request_id, attempt_index),
        ).fetchone()

        identifier = f"{request_id}/{attempt_index}"

        if row is None:
            raise KeyError(
                f"provider attempt not found: {identifier}"
            )

        raise RuntimeError(
            f"provider attempt already finalized: {identifier}"
        )

    @staticmethod
    def _require_tool_attempt_finalized(
        connection,
        rowcount: int,
        *,
        request_id: str,
        attempt_index: int,
    ) -> None:
        if rowcount == 1:
            return

        row = connection.execute(
            """
            SELECT 1
            FROM tool_attempts
            WHERE request_id = ?
              AND attempt_index = ?
            """,
            (request_id, attempt_index),
        ).fetchone()

        identifier = f"{request_id}/{attempt_index}"

        if row is None:
            raise KeyError(
                f"tool attempt not found: {identifier}"
            )

        raise RuntimeError(
            f"tool attempt already finalized: {identifier}"
        )
