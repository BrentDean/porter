import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from porter.cli import _parse_training_selection, _run_repl, _run_training_review
from porter.storage.database import Database
from porter.storage.migrations import MigrationRunner
from porter.training import (
    RecognitionGapRepository,
    TrainingCorpusRepository,
    TrainingGroupHandling,
    normalize_training_text,
)


def test_training_text_normalization_preserves_semantic_words() -> None:
    assert normalize_training_text("  How   MUCH Space Is Left?  ") == "how much space is left?"


def test_training_repository_preserves_raw_text_and_session(tmp_path: Path) -> None:
    database = Database(tmp_path / "porter.db")
    MigrationRunner(database).apply_all()
    repository = TrainingCorpusRepository(database)

    example = repository.add(
        session_id="session-1",
        raw_text="How   MUCH space is left?",
    )

    assert example.session_id == "session-1"
    assert example.raw_text == "How   MUCH space is left?"
    assert example.normalized_text == "how much space is left?"
    assert example.label is None
    assert example.route_type is None
    assert example.group_id is None
    assert example.review_status == "unreviewed"
    assert example.reviewed_at is None
    assert repository.list_unreviewed() == (example,)
    assert repository.list_ungrouped() == (example,)


def test_group_multiple_examples_as_new_deterministic_behavior(tmp_path: Path) -> None:
    database = Database(tmp_path / "porter.db")
    MigrationRunner(database).apply_all()
    repository = TrainingCorpusRepository(database)
    first = repository.add(session_id="session-1", raw_text="savecats")
    second = repository.add(session_id="session-1", raw_text="savecat")
    third = repository.add(session_id="session-1", raw_text="dumpmovie")

    group = repository.create_group(
        name="media save scripts",
        handling=TrainingGroupHandling.NEW_DETERMINISTIC,
        example_ids=(first.id, second.id, third.id),
    )

    assert group.name == "media save scripts"
    assert group.handling is TrainingGroupHandling.NEW_DETERMINISTIC
    assert group.target_label is None
    assert group.example_count == 3
    assert repository.list_ungrouped() == ()
    assert repository.list_groups() == (group,)

    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT group_id, route_type, label, review_status
            FROM training_examples
            ORDER BY id
            """
        ).fetchall()

    assert all(row["group_id"] == group.id for row in rows)
    assert all(row["route_type"] == "deterministic" for row in rows)
    assert all(row["label"] is None for row in rows)
    assert all(row["review_status"] == "reviewed" for row in rows)

    summary = repository.review_summary()
    assert summary.ungrouped == 0
    assert summary.grouped == 3
    assert summary.groups == 1
    assert summary.promoted == 0


def test_existing_behavior_group_applies_internal_target_without_user_typing_it(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "porter.db")
    MigrationRunner(database).apply_all()
    repository = TrainingCorpusRepository(database)
    example = repository.add(session_id="session-1", raw_text="disk usage")

    group = repository.create_group(
        name="show disk usage",
        handling=TrainingGroupHandling.EXISTING_BEHAVIOR,
        example_ids=(example.id,),
        target_label="PorterDiskUsage",
    )

    assert group.target_label == "PorterDiskUsage"
    with database.connect() as connection:
        row = connection.execute(
            "SELECT route_type, label FROM training_examples WHERE id = ?",
            (example.id,),
        ).fetchone()

    assert row is not None
    assert tuple(row) == ("deterministic", "PorterDiskUsage")


def test_existing_behavior_group_requires_internal_target(tmp_path: Path) -> None:
    database = Database(tmp_path / "porter.db")
    MigrationRunner(database).apply_all()
    repository = TrainingCorpusRepository(database)
    example = repository.add(session_id="session-1", raw_text="disk usage")

    with pytest.raises(ValueError, match="require a target label"):
        repository.create_group(
            name="show disk usage",
            handling=TrainingGroupHandling.EXISTING_BEHAVIOR,
            example_ids=(example.id,),
        )


def test_training_selection_accepts_ids_and_ranges() -> None:
    assert _parse_training_selection("2-5,7,9", set(range(1, 11))) == (
        2,
        3,
        4,
        5,
        7,
        9,
    )


@pytest.mark.parametrize("selection", ("", "5-2", "2,x", "2-4"))
def test_training_selection_rejects_invalid_or_unavailable_ids(selection: str) -> None:
    with pytest.raises(ValueError):
        _parse_training_selection(selection, {1, 2, 5})


def test_recognition_gap_repository_groups_and_counts_outcomes(tmp_path: Path) -> None:
    database = Database(tmp_path / "porter.db")
    MigrationRunner(database).apply_all()
    repository = RecognitionGapRepository(database)

    repository.record(
        raw_text="How much hard drive space is left",
        ai_approved=False,
    )
    gap = repository.record(
        raw_text="  HOW much hard drive space is left  ",
        ai_approved=True,
    )

    assert gap.normalized_text == "how much hard drive space is left"
    assert gap.latest_raw_text == "  HOW much hard drive space is left  "
    assert gap.occurrence_count == 2
    assert gap.ai_approved_count == 1
    assert gap.ai_declined_count == 1
    assert repository.list_common() == (gap,)


def test_repl_training_mode_never_dispatches(monkeypatch, capsys) -> None:
    captured_examples: list[tuple[str, str]] = []

    class FakeTrainingRepository:
        def add(self, *, session_id: str, raw_text: str) -> None:
            captured_examples.append((session_id, raw_text))

    class FailingDispatcher:
        async def execute(self, *args, **kwargs) -> None:
            raise AssertionError("training examples must never reach the dispatcher")

    responses = iter(
        (
            "training",
            "restart plex",
            "population of new hampshire",
            "END",
            "quit",
        )
    )
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    application = SimpleNamespace(
        training_repository=FakeTrainingRepository(),
        dispatcher=FailingDispatcher(),
    )

    result = asyncio.run(_run_repl(application))  # type: ignore[arg-type]

    output = capsys.readouterr().out
    assert result == 0
    assert [raw_text for _, raw_text in captured_examples] == [
        "restart plex",
        "population of new hampshire",
    ]
    assert len({session_id for session_id, _ in captured_examples}) == 1
    assert "Nothing entered here will execute." in output
    assert "Training session saved: 2 examples" in output


def test_training_review_groups_multiple_phrases_without_intent_label(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    database = Database(tmp_path / "porter.db")
    MigrationRunner(database).apply_all()
    training_repository = TrainingCorpusRepository(database)
    gap_repository = RecognitionGapRepository(database)
    first = training_repository.add(session_id="session-1", raw_text="savecats")
    second = training_repository.add(session_id="session-1", raw_text="savecat")
    third = training_repository.add(session_id="session-1", raw_text="disk usage")

    responses = iter(
        (
            f"{first.id}-{second.id}",
            "media save scripts",
            "2",
            "q",
        )
    )
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    application = SimpleNamespace(
        training_repository=training_repository,
        recognition_gap_repository=gap_repository,
    )

    result = _run_training_review(application)  # type: ignore[arg-type]

    output = capsys.readouterr().out
    assert result == 0
    groups = training_repository.list_groups()
    assert len(groups) == 1
    assert groups[0].name == "media save scripts"
    assert groups[0].example_count == 2
    assert training_repository.list_ungrouped() == (third,)
    assert "No internal intent label is required yet" in output
    assert "Intent label:" not in output


def test_training_review_selects_registered_deterministic_behavior(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    database = Database(tmp_path / "porter.db")
    MigrationRunner(database).apply_all()
    training_repository = TrainingCorpusRepository(database)
    gap_repository = RecognitionGapRepository(database)
    example = training_repository.add(session_id="session-1", raw_text="show disk use")

    class FakeIntentRegistry:
        def supported_intents(self) -> frozenset[str]:
            return frozenset({"PorterDiskUsage"})

    responses = iter(
        (
            str(example.id),
            "show disk usage",
            "1",
            "1",
        )
    )
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    application = SimpleNamespace(
        training_repository=training_repository,
        recognition_gap_repository=gap_repository,
        intent_handler_registry=FakeIntentRegistry(),
    )

    result = _run_training_review(application)  # type: ignore[arg-type]

    output = capsys.readouterr().out
    groups = training_repository.list_groups()
    assert result == 0
    assert len(groups) == 1
    assert groups[0].handling is TrainingGroupHandling.EXISTING_BEHAVIOR
    assert groups[0].target_label == "PorterDiskUsage"
    assert "Storage — disk usage" in output
    assert "cli.doctor" not in output
