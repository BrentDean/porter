from __future__ import annotations

from collections.abc import Sequence

from porter.storage.database import Database
from porter.training.models import (
    RecognitionGap,
    TrainingExample,
    TrainingGroup,
    TrainingGroupHandling,
    TrainingReviewSummary,
    TrainingRouteType,
    normalize_training_text,
)


class TrainingCorpusRepository:
    """Persists and groups non-executing examples of how the user addresses Porter."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def add(self, *, session_id: str, raw_text: str) -> TrainingExample:
        if not session_id.strip():
            raise ValueError("training session_id must not be empty")
        if not raw_text.strip():
            raise ValueError("training raw_text must not be empty")

        normalized_text = normalize_training_text(raw_text)
        with self._database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO training_examples (
                    session_id,
                    raw_text,
                    normalized_text
                )
                VALUES (?, ?, ?)
                """,
                (session_id, raw_text, normalized_text),
            )
            connection.commit()
            row = self._select_by_id(connection, int(cursor.lastrowid))

        if row is None:
            raise RuntimeError("training example insert did not return a row")
        return self._from_row(row)

    def list_unreviewed(self, *, limit: int = 100) -> tuple[TrainingExample, ...]:
        if limit <= 0:
            raise ValueError("training review limit must be positive")

        with self._database.connect() as connection:
            rows = connection.execute(
                f"""
                {self._example_select_sql()}
                WHERE review_status = 'unreviewed'
                ORDER BY id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return tuple(self._from_row(row) for row in rows)

    def list_ungrouped(self, *, limit: int = 200) -> tuple[TrainingExample, ...]:
        if limit <= 0:
            raise ValueError("training grouping limit must be positive")

        with self._database.connect() as connection:
            rows = connection.execute(
                f"""
                {self._example_select_sql()}
                WHERE group_id IS NULL AND review_status != 'promoted'
                ORDER BY id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return tuple(self._from_row(row) for row in rows)

    def create_group(
        self,
        *,
        name: str,
        handling: TrainingGroupHandling,
        example_ids: Sequence[int],
        target_label: str | None = None,
    ) -> TrainingGroup:
        normalized_name = " ".join(name.split())
        if not normalized_name:
            raise ValueError("training group name must not be empty")

        selected_ids = tuple(dict.fromkeys(int(example_id) for example_id in example_ids))
        if not selected_ids:
            raise ValueError("training group requires at least one example")
        if any(example_id <= 0 for example_id in selected_ids):
            raise ValueError("training example ids must be positive")

        normalized_target = None if target_label is None else target_label.strip()
        if handling is TrainingGroupHandling.EXISTING_BEHAVIOR:
            if not normalized_target:
                raise ValueError("existing behavior groups require a target label")
        else:
            normalized_target = None

        route_type = {
            TrainingGroupHandling.EXISTING_BEHAVIOR: TrainingRouteType.DETERMINISTIC,
            TrainingGroupHandling.NEW_DETERMINISTIC: TrainingRouteType.DETERMINISTIC,
            TrainingGroupHandling.INFERENCE: TrainingRouteType.INFERENCE,
            TrainingGroupHandling.DISCARD: TrainingRouteType.DISCARD,
        }[handling]

        placeholders = ", ".join("?" for _ in selected_ids)
        with self._database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id
                FROM training_examples
                WHERE id IN ({placeholders})
                  AND group_id IS NULL
                  AND review_status != 'promoted'
                """,
                selected_ids,
            ).fetchall()
            found_ids = {int(row["id"]) for row in rows}
            if found_ids != set(selected_ids):
                raise ValueError("one or more training examples are missing or already grouped")

            cursor = connection.execute(
                """
                INSERT INTO training_groups (name, handling, target_label)
                VALUES (?, ?, ?)
                """,
                (normalized_name, handling.value, normalized_target),
            )
            group_id = int(cursor.lastrowid)

            connection.execute(
                f"""
                UPDATE training_examples
                SET
                    group_id = ?,
                    label = ?,
                    route_type = ?,
                    review_status = 'reviewed',
                    reviewed_at = CURRENT_TIMESTAMP
                WHERE id IN ({placeholders})
                """,
                (
                    group_id,
                    normalized_target,
                    route_type.value,
                    *selected_ids,
                ),
            )
            connection.commit()
            row = self._select_group_by_id(connection, group_id)

        if row is None:
            raise RuntimeError("training group insert did not return a row")
        return self._group_from_row(row)

    def list_groups(self) -> tuple[TrainingGroup, ...]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    groups.id,
                    groups.name,
                    groups.handling,
                    groups.target_label,
                    groups.created_at,
                    COUNT(examples.id) AS example_count
                FROM training_groups AS groups
                LEFT JOIN training_examples AS examples
                    ON examples.group_id = groups.id
                GROUP BY groups.id
                ORDER BY groups.id
                """
            ).fetchall()

        return tuple(self._group_from_row(row) for row in rows)

    def review_summary(self) -> TrainingReviewSummary:
        with self._database.connect() as connection:
            ungrouped = connection.execute(
                """
                SELECT COUNT(*)
                FROM training_examples
                WHERE group_id IS NULL AND review_status != 'promoted'
                """
            ).fetchone()
            grouped = connection.execute(
                "SELECT COUNT(*) FROM training_examples WHERE group_id IS NOT NULL"
            ).fetchone()
            groups = connection.execute("SELECT COUNT(*) FROM training_groups").fetchone()
            promoted = connection.execute(
                "SELECT COUNT(*) FROM training_examples WHERE review_status = 'promoted'"
            ).fetchone()

        return TrainingReviewSummary(
            ungrouped=int(ungrouped[0]) if ungrouped is not None else 0,
            grouped=int(grouped[0]) if grouped is not None else 0,
            groups=int(groups[0]) if groups is not None else 0,
            promoted=int(promoted[0]) if promoted is not None else 0,
        )

    @staticmethod
    def _example_select_sql() -> str:
        return """
            SELECT
                id,
                session_id,
                raw_text,
                normalized_text,
                label,
                route_type,
                group_id,
                review_status,
                created_at,
                reviewed_at
            FROM training_examples
        """

    @classmethod
    def _select_by_id(cls, connection, example_id: int):
        return connection.execute(
            f"""
            {cls._example_select_sql()}
            WHERE id = ?
            """,
            (example_id,),
        ).fetchone()

    @staticmethod
    def _select_group_by_id(connection, group_id: int):
        return connection.execute(
            """
            SELECT
                groups.id,
                groups.name,
                groups.handling,
                groups.target_label,
                groups.created_at,
                COUNT(examples.id) AS example_count
            FROM training_groups AS groups
            LEFT JOIN training_examples AS examples
                ON examples.group_id = groups.id
            WHERE groups.id = ?
            GROUP BY groups.id
            """,
            (group_id,),
        ).fetchone()

    @staticmethod
    def _from_row(row) -> TrainingExample:
        route_type = row["route_type"]
        return TrainingExample(
            id=int(row["id"]),
            session_id=str(row["session_id"]),
            raw_text=str(row["raw_text"]),
            normalized_text=str(row["normalized_text"]),
            label=None if row["label"] is None else str(row["label"]),
            route_type=(None if route_type is None else TrainingRouteType(str(route_type))),
            group_id=None if row["group_id"] is None else int(row["group_id"]),
            review_status=str(row["review_status"]),
            created_at=str(row["created_at"]),
            reviewed_at=(None if row["reviewed_at"] is None else str(row["reviewed_at"])),
        )

    @staticmethod
    def _group_from_row(row) -> TrainingGroup:
        return TrainingGroup(
            id=int(row["id"]),
            name=str(row["name"]),
            handling=TrainingGroupHandling(str(row["handling"])),
            target_label=None if row["target_label"] is None else str(row["target_label"]),
            example_count=int(row["example_count"]),
            created_at=str(row["created_at"]),
        )


class RecognitionGapRepository:
    """Tracks unmatched normal requests and whether local AI was accepted."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def record(self, *, raw_text: str, ai_approved: bool) -> RecognitionGap:
        if not raw_text.strip():
            raise ValueError("recognition gap raw_text must not be empty")

        normalized_text = normalize_training_text(raw_text)
        approved_increment = 1 if ai_approved else 0
        declined_increment = 0 if ai_approved else 1

        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO recognition_gaps (
                    normalized_text,
                    latest_raw_text,
                    occurrence_count,
                    ai_approved_count,
                    ai_declined_count
                )
                VALUES (?, ?, 1, ?, ?)
                ON CONFLICT(normalized_text) DO UPDATE SET
                    latest_raw_text = excluded.latest_raw_text,
                    occurrence_count = recognition_gaps.occurrence_count + 1,
                    ai_approved_count = recognition_gaps.ai_approved_count + ?,
                    ai_declined_count = recognition_gaps.ai_declined_count + ?,
                    last_seen_at = CURRENT_TIMESTAMP
                """,
                (
                    normalized_text,
                    raw_text,
                    approved_increment,
                    declined_increment,
                    approved_increment,
                    declined_increment,
                ),
            )
            connection.commit()
            row = connection.execute(
                """
                SELECT
                    id,
                    normalized_text,
                    latest_raw_text,
                    occurrence_count,
                    ai_approved_count,
                    ai_declined_count,
                    first_seen_at,
                    last_seen_at
                FROM recognition_gaps
                WHERE normalized_text = ?
                """,
                (normalized_text,),
            ).fetchone()

        if row is None:
            raise RuntimeError("recognition gap insert did not return a row")
        return RecognitionGap(
            id=int(row["id"]),
            normalized_text=str(row["normalized_text"]),
            latest_raw_text=str(row["latest_raw_text"]),
            occurrence_count=int(row["occurrence_count"]),
            ai_approved_count=int(row["ai_approved_count"]),
            ai_declined_count=int(row["ai_declined_count"]),
            first_seen_at=str(row["first_seen_at"]),
            last_seen_at=str(row["last_seen_at"]),
        )

    def list_common(self, *, limit: int = 100) -> tuple[RecognitionGap, ...]:
        if limit <= 0:
            raise ValueError("recognition gap limit must be positive")

        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    normalized_text,
                    latest_raw_text,
                    occurrence_count,
                    ai_approved_count,
                    ai_declined_count,
                    first_seen_at,
                    last_seen_at
                FROM recognition_gaps
                ORDER BY occurrence_count DESC, last_seen_at DESC, id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return tuple(
            RecognitionGap(
                id=int(row["id"]),
                normalized_text=str(row["normalized_text"]),
                latest_raw_text=str(row["latest_raw_text"]),
                occurrence_count=int(row["occurrence_count"]),
                ai_approved_count=int(row["ai_approved_count"]),
                ai_declined_count=int(row["ai_declined_count"]),
                first_seen_at=str(row["first_seen_at"]),
                last_seen_at=str(row["last_seen_at"]),
            )
            for row in rows
        )
