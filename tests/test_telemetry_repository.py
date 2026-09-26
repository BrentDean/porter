from pathlib import Path

import pytest

from porter.core.lifecycle import ExecutionOutcome
from porter.core.models import ExecutionPath
from porter.storage.database import Database
from porter.storage.migrations import MigrationRunner
from porter.telemetry.repository import TelemetryRepository
from tests.fakes import make_request


def build_repository(
    tmp_path: Path,
) -> tuple[Database, TelemetryRepository]:
    database = Database(tmp_path / "porter.db")
    MigrationRunner(database).apply_all()
    return database, TelemetryRepository(database)


def test_start_request_persists_request_metadata(
    tmp_path: Path,
) -> None:
    database, repository = build_repository(tmp_path)
    request = make_request(
        content="do not persist this message"
    )

    repository.start_request(request)

    with database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM requests WHERE request_id = ?",
            (request.request_id,),
        ).fetchone()

    assert row is not None
    assert row["principal_id"] == "test-user"
    assert row["source"] == "cli"
    assert row["task_type"] == "general"
    assert row["privacy_class"] == "local_only"
    assert row["allow_cloud"] == 0
    assert row["outcome"] is None
    assert row["completed_at"] is None


def test_request_lifecycle_records_route_and_outcome(
    tmp_path: Path,
) -> None:
    database, repository = build_repository(tmp_path)
    request = make_request()

    repository.start_request(request)
    repository.set_route(
        request.request_id,
        "local_only_route",
    )
    repository.finish_request(
        request.request_id,
        ExecutionOutcome.SUCCEEDED,
    )

    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT route_reason, outcome, completed_at
            FROM requests
            WHERE request_id = ?
            """,
            (request.request_id,),
        ).fetchone()

    assert row is not None
    assert row["route_reason"] == "local_only_route"
    assert row["outcome"] == "succeeded"
    assert row["completed_at"] is not None



def test_request_execution_path_is_persisted(
    tmp_path: Path,
) -> None:
    database, repository = build_repository(tmp_path)
    request = make_request()

    repository.start_request(request)
    repository.set_execution_path(
        request.request_id,
        ExecutionPath.TOOL,
    )

    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT execution_path
            FROM requests
            WHERE request_id = ?
            """,
            (request.request_id,),
        ).fetchone()

    assert row is not None
    assert row["execution_path"] == "tool"


def test_provider_attempt_lifecycle_records_metrics(
    tmp_path: Path,
) -> None:
    database, repository = build_repository(tmp_path)
    request = make_request()
    repository.start_request(request)

    repository.start_provider_attempt(
        request_id=request.request_id,
        attempt_index=1,
        provider="ollama",
        model="test-model",
    )

    repository.finish_provider_attempt(
        request_id=request.request_id,
        attempt_index=1,
        outcome=ExecutionOutcome.FAILED,
        latency_ms=125,
        input_tokens=10,
        output_tokens=4,
        estimated_cost_microusd=2500,
        error_classification="provider_unavailable",
    )

    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM provider_attempts
            WHERE request_id = ?
              AND attempt_index = ?
            """,
            (request.request_id, 1),
        ).fetchone()

    assert row is not None
    assert row["request_id"] == request.request_id
    assert row["attempt_index"] == 1
    assert row["provider"] == "ollama"
    assert row["model"] == "test-model"
    assert row["outcome"] == "failed"
    assert row["latency_ms"] == 125
    assert row["input_tokens"] == 10
    assert row["output_tokens"] == 4
    assert row["estimated_cost_microusd"] == 2500
    assert row["error_classification"] == "provider_unavailable"
    assert row["completed_at"] is not None



def test_tool_attempt_lifecycle_records_metrics(
    tmp_path: Path,
) -> None:
    database, repository = build_repository(tmp_path)
    request = make_request()
    repository.start_request(request)

    repository.start_tool_attempt(
        request_id=request.request_id,
        attempt_index=1,
        tool="qalculate",
    )

    repository.finish_tool_attempt(
        request_id=request.request_id,
        attempt_index=1,
        outcome=ExecutionOutcome.SUCCEEDED,
        latency_ms=8,
    )

    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM tool_attempts
            WHERE request_id = ?
              AND attempt_index = ?
            """,
            (request.request_id, 1),
        ).fetchone()

    assert row is not None
    assert row["request_id"] == request.request_id
    assert row["attempt_index"] == 1
    assert row["tool"] == "qalculate"
    assert row["outcome"] == "succeeded"
    assert row["latency_ms"] == 8
    assert row["error_classification"] is None
    assert row["completed_at"] is not None


def test_updates_reject_unknown_records(
    tmp_path: Path,
) -> None:
    _, repository = build_repository(tmp_path)

    with pytest.raises(
        KeyError,
        match="request not found",
    ):
        repository.set_route(
            "missing-request",
            "test",
        )

    with pytest.raises(
        KeyError,
        match="provider attempt not found",
    ):
        repository.finish_provider_attempt(
            request_id="missing-request",
            attempt_index=1,
            outcome=ExecutionOutcome.FAILED,
        )

    with pytest.raises(
        KeyError,
        match="tool attempt not found",
    ):
        repository.finish_tool_attempt(
            request_id="missing-request",
            attempt_index=1,
            outcome=ExecutionOutcome.FAILED,
        )


def test_request_cannot_be_finalized_twice(
    tmp_path: Path,
) -> None:
    _, repository = build_repository(tmp_path)
    request = make_request()

    repository.start_request(request)
    repository.finish_request(
        request.request_id,
        ExecutionOutcome.SUCCEEDED,
    )

    with pytest.raises(
        RuntimeError,
        match="already finalized",
    ):
        repository.finish_request(
            request.request_id,
            ExecutionOutcome.FAILED,
        )


def test_provider_attempt_cannot_be_finalized_twice(
    tmp_path: Path,
) -> None:
    _, repository = build_repository(tmp_path)
    request = make_request()

    repository.start_request(request)
    repository.start_provider_attempt(
        request_id=request.request_id,
        attempt_index=1,
        provider="ollama",
        model="test-model",
    )
    repository.finish_provider_attempt(
        request_id=request.request_id,
        attempt_index=1,
        outcome=ExecutionOutcome.SUCCEEDED,
    )

    with pytest.raises(
        RuntimeError,
        match="already finalized",
    ):
        repository.finish_provider_attempt(
            request_id=request.request_id,
            attempt_index=1,
            outcome=ExecutionOutcome.FAILED,
        )


def test_tool_attempt_cannot_be_finalized_twice(
    tmp_path: Path,
) -> None:
    _, repository = build_repository(tmp_path)
    request = make_request()

    repository.start_request(request)
    repository.start_tool_attempt(
        request_id=request.request_id,
        attempt_index=1,
        tool="qalculate",
    )
    repository.finish_tool_attempt(
        request_id=request.request_id,
        attempt_index=1,
        outcome=ExecutionOutcome.SUCCEEDED,
    )

    with pytest.raises(
        RuntimeError,
        match="already finalized",
    ):
        repository.finish_tool_attempt(
            request_id=request.request_id,
            attempt_index=1,
            outcome=ExecutionOutcome.FAILED,
        )
