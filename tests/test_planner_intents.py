from __future__ import annotations

from datetime import UTC, date, datetime
from itertools import count
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from porter.app import build_application
from porter.core.models import Message, RequestContext, RequestSource
from porter.intents import (
    IntentResult,
    PlannerOverdueHandler,
    PlannerTodayHandler,
    PlannerUnscheduledHandler,
    PlannerUpcomingHandler,
    PorterIntentRecognizer,
    RecognizedIntent,
)
from porter.storage.database import Database
from porter.storage.migrations import MigrationRunner
from porter.tasks import SqliteTaskRepository, TaskService
from porter.tasks.planning import PlannerService

TORONTO = ZoneInfo("America/Toronto")
NOW = datetime(2026, 8, 15, 16, tzinfo=UTC)


def _request(
    text: str,
    *,
    principal_id: str = "alice",
) -> RequestContext:
    return RequestContext(
        messages=(Message(role="user", content=text),),
        principal_id=principal_id,
        source=RequestSource.CLI,
    )


def _services(tmp_path: Path) -> tuple[TaskService, PlannerService]:
    database = Database(tmp_path / "porter.db")
    MigrationRunner(database).apply_all()
    repository = SqliteTaskRepository(database)
    identifiers = count(1)
    task_service = TaskService(
        repository,
        clock=lambda: NOW,
        id_generator=lambda: f"id-{next(identifiers)}",
    )
    planner_service = PlannerService(task_service, clock=lambda: NOW)
    return task_service, planner_service


@pytest.mark.parametrize(
    ("text", "intent_name"),
    [
        ("what tasks are due today", "PorterPlannerToday"),
        ("what tasks are overdue", "PorterPlannerOverdue"),
        ("what tasks are coming up", "PorterPlannerUpcoming"),
        ("what tasks have no due date", "PorterPlannerUnscheduled"),
    ],
)
def test_recognizes_porter_planner_sentences(
    text: str,
    intent_name: str,
) -> None:
    recognizer = PorterIntentRecognizer(
        supported_intents=frozenset(
            {
                "PorterPlannerToday",
                "PorterPlannerOverdue",
                "PorterPlannerUpcoming",
                "PorterPlannerUnscheduled",
            }
        )
    )

    assert recognizer.recognize(text) == RecognizedIntent(
        name=intent_name,
        slots={},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler_type", "intent_name", "view", "summary", "due"),
    [
        (
            PlannerTodayHandler,
            "PorterPlannerToday",
            "today",
            "Today task",
            date(2026, 8, 15),
        ),
        (
            PlannerOverdueHandler,
            "PorterPlannerOverdue",
            "overdue",
            "Overdue task",
            date(2026, 8, 14),
        ),
        (
            PlannerUpcomingHandler,
            "PorterPlannerUpcoming",
            "upcoming",
            "Upcoming task",
            date(2026, 8, 16),
        ),
        (
            PlannerUnscheduledHandler,
            "PorterPlannerUnscheduled",
            "unscheduled",
            "Unscheduled task",
            None,
        ),
    ],
)
async def test_planner_handlers_use_principal_scope_and_timezone(
    tmp_path: Path,
    handler_type,
    intent_name: str,
    view: str,
    summary: str,
    due,
) -> None:
    task_service, planner_service = _services(tmp_path)
    alice_list = task_service.create_list("alice", "Work")
    bob_list = task_service.create_list("bob", "Work")
    expected = task_service.add_task(
        "alice",
        alice_list.id,
        summary,
        due=due,
    )
    task_service.add_task(
        "bob",
        bob_list.id,
        f"Bob {summary}",
        due=due,
    )
    handler = handler_type(
        planner_service,
        timezone_provider=lambda: TORONTO,
    )

    result = await handler.handle(
        _request("ignored"),
        RecognizedIntent(name=intent_name, slots={}),
    )

    assert result.data["intent"] == intent_name
    assert result.data["view"] == view
    assert result.data["count"] == 1
    assert result.data["task_ids"] == (expected.id,)
    assert result.data["summaries"] == (summary,)
    assert result.data["timezone"] == "America/Toronto"
    assert summary in result.text
    assert f"Bob {summary}" not in result.text


@pytest.mark.asyncio
async def test_planner_intent_text_is_bounded_but_structured_data_is_complete(
    tmp_path: Path,
) -> None:
    task_service, planner_service = _services(tmp_path)
    task_list = task_service.create_list("alice", "Work")
    for index in range(7):
        task_service.add_task(
            "alice",
            task_list.id,
            f"Task {index + 1}",
        )
    handler = PlannerUnscheduledHandler(
        planner_service,
        timezone_provider=lambda: TORONTO,
    )

    result = await handler.handle(
        _request("ignored"),
        RecognizedIntent(name="PorterPlannerUnscheduled", slots={}),
    )

    assert result.data["count"] == 7
    assert len(result.data["task_ids"]) == 7
    assert len(result.data["summaries"]) == 7
    assert "and 2 more" in result.text


@pytest.mark.asyncio
async def test_bootstrapped_planner_intent_routes_deterministically(
    tmp_path: Path,
) -> None:
    application = build_application(
        env={"PORTER_DATA_DIR": str(tmp_path)},
        home=tmp_path,
    )

    result = await application.deterministic_executor.execute(
        _request("what tasks are overdue")
    )

    assert isinstance(result, IntentResult)
    assert result.text == "You have no overdue tasks."
    assert result.data["intent"] == "PorterPlannerOverdue"
    assert result.data["view"] == "overdue"
    assert result.data["count"] == 0
