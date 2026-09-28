from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from porter.cli.commands.reliability import _target, _window, run
from porter.cli.main import _main
from porter.storage.database import Database
from porter.storage.migrations import MigrationRunner
from porter.telemetry.bootstrap import build_reliability_runtime
from porter.telemetry.reliability import ReliabilityService
from porter.telemetry.repository import TelemetryRepository

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def _repository(tmp_path: Path) -> tuple[Database, TelemetryRepository]:
    database = Database(tmp_path / "porter.db")
    MigrationRunner(database).apply_all()
    return database, TelemetryRepository(database)


def _insert_request(
    database: Database,
    *,
    request_id: str,
    outcome: str,
    completed_at: str,
    latency_ms: int | None,
) -> None:
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO requests (
                request_id,
                principal_id,
                source,
                task_type,
                privacy_class,
                allow_cloud,
                completed_at,
                outcome,
                latency_ms
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                "test-user",
                "cli",
                "general",
                "local_only",
                0,
                completed_at,
                outcome,
                latency_ms,
            ),
        )
        connection.commit()


def test_reliability_report_calculates_slo_and_latency_statistics(
    tmp_path: Path,
) -> None:
    database, repository = _repository(tmp_path)
    _insert_request(
        database,
        request_id="success-1",
        outcome="succeeded",
        completed_at="2026-09-17 10:10:00",
        latency_ms=100,
    )
    _insert_request(
        database,
        request_id="success-2",
        outcome="succeeded",
        completed_at="2026-09-17 10:20:00",
        latency_ms=200,
    )
    _insert_request(
        database,
        request_id="success-no-latency",
        outcome="succeeded",
        completed_at="2026-09-17 10:30:00",
        latency_ms=None,
    )
    _insert_request(
        database,
        request_id="failed-1",
        outcome="failed",
        completed_at="2026-09-17 10:40:00",
        latency_ms=400,
    )
    _insert_request(
        database,
        request_id="cancelled-1",
        outcome="cancelled",
        completed_at="2026-09-17 10:50:00",
        latency_ms=900,
    )
    _insert_request(
        database,
        request_id="old-failure",
        outcome="failed",
        completed_at="2026-09-16 09:00:00",
        latency_ms=500,
    )

    report = ReliabilityService(repository, clock=lambda: NOW).report(
        window=timedelta(hours=2),
        target_percent=75.0,
    )

    assert report.succeeded == 3
    assert report.failed == 1
    assert report.cancelled == 1
    assert report.slo_requests == 4
    assert report.success_rate_percent == pytest.approx(75.0)
    assert report.latency_samples == 3
    assert report.p50_latency_ms == pytest.approx(200.0)
    assert report.p95_latency_ms == pytest.approx(380.0)
    assert report.allowed_errors == pytest.approx(1.0)
    assert report.error_budget_consumed_percent == pytest.approx(100.0)
    assert report.error_budget_remaining_percent == pytest.approx(0.0)


def test_reliability_report_handles_empty_window(tmp_path: Path) -> None:
    _, repository = _repository(tmp_path)

    report = ReliabilityService(repository, clock=lambda: NOW).report(
        window=timedelta(hours=24),
    )

    assert report.slo_requests == 0
    assert report.cancelled == 0
    assert report.latency_samples == 0
    assert report.p50_latency_ms is None
    assert report.p95_latency_ms is None
    assert report.success_rate_percent is None
    assert report.allowed_errors == 0
    assert report.error_budget_consumed_percent is None
    assert report.error_budget_remaining_percent is None


@pytest.mark.parametrize(
    ("window", "expected"),
    [
        ("30m", timedelta(minutes=30)),
        ("24h", timedelta(hours=24)),
        ("7d", timedelta(days=7)),
        ("2w", timedelta(weeks=2)),
        (" 24H ", timedelta(hours=24)),
    ],
)
def test_window_parser_accepts_supported_duration_units(
    window: str,
    expected: timedelta,
) -> None:
    assert _window(window) == expected


@pytest.mark.parametrize("window", ("", "0h", "-1h", "1.5h", "day", "24x"))
def test_window_parser_rejects_invalid_values(window: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="window must be"):
        _window(window)


@pytest.mark.parametrize("target", ("0", "100", "-1", "101", "nan"))
def test_target_parser_rejects_invalid_percentages(target: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="target must be"):
        _target(target)


def test_reliability_service_validates_window_and_target(tmp_path: Path) -> None:
    _, repository = _repository(tmp_path)
    service = ReliabilityService(repository, clock=lambda: NOW)

    with pytest.raises(ValueError, match="window must be positive"):
        service.report(window=timedelta(0))

    with pytest.raises(ValueError, match="target_percent"):
        service.report(window=timedelta(hours=1), target_percent=100)


def test_reliability_runtime_uses_storage_only_configuration(tmp_path: Path) -> None:
    runtime = build_reliability_runtime(
        env={
            "PORTER_DATA_DIR": str(tmp_path),
            "PORTER_OLLAMA_TIMEOUT_SECONDS": "not-a-number",
            "PORTER_SYNOPIC_STATION_LIMIT": "not-an-integer",
        },
        home=tmp_path,
    )

    assert runtime.database.path == tmp_path / "porter.db"
    assert runtime.migration_runner.current_version() == 14


def test_reliability_cli_prints_slo_report(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, repository = _repository(tmp_path)
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO requests (
                request_id,
                principal_id,
                source,
                task_type,
                privacy_class,
                allow_cloud,
                completed_at,
                outcome,
                latency_ms
            )
            VALUES (
                'success-now',
                'test-user',
                'cli',
                'general',
                'local_only',
                0,
                CURRENT_TIMESTAMP,
                'succeeded',
                25
            )
            """
        )
        connection.commit()

    service = ReliabilityService(repository)
    monkeypatch.setattr(
        "porter.cli.commands.reliability.build_reliability_runtime",
        lambda: SimpleNamespace(reliability_service=service),
    )

    result = run(["--window", "24h", "--target", "99.5"])

    output = capsys.readouterr().out
    assert result == 0
    assert "Porter reliability" in output
    assert "window: 24h" in output
    assert "availability target: 99.50%" in output
    assert "SLO requests: 1" in output
    assert "success rate: 100.00%" in output
    assert "p50 latency: 25.0 ms" in output
    assert "p95 latency: 25.0 ms" in output
    assert "error budget consumed: 0.00%" in output
    assert "error budget remaining: 100.00%" in output


def test_reliability_cli_rejects_invalid_window(
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        "porter.cli.commands.reliability.build_reliability_runtime",
        lambda: pytest.fail("invalid arguments must not build the runtime"),
    )

    with pytest.raises(SystemExit) as exc_info:
        run(["--window", "yesterday"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "window must be a positive integer" in captured.err


def test_reliability_subcommand_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    monkeypatch.setattr(
        "porter.cli.commands.reliability.run",
        lambda args: calls.append(args) or 0,
    )

    result = _main(["reliability", "--window", "7d", "--target", "99.9"])

    assert result == 0
    assert calls == [["--window", "7d", "--target", "99.9"]]
