from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar
from zoneinfo import ZoneInfo

from porter.core.clock import system_timezone
from porter.core.models import RequestContext
from porter.intents.handlers import IntentHandler
from porter.intents.models import IntentResult, RecognizedIntent
from porter.tasks.planning import PlannerItem, PlannerService, PlannerSnapshot

_TEXT_ITEM_LIMIT = 5


def _render_items(
    heading: str,
    empty_text: str,
    items: tuple[PlannerItem, ...],
) -> str:
    if not items:
        return empty_text

    visible = items[:_TEXT_ITEM_LIMIT]
    rendered = "; ".join(
        f"{item.task.summary} ({item.task_list.name})" for item in visible
    )
    remaining = len(items) - len(visible)
    if remaining:
        return f"{heading}: {rendered}; and {remaining} more."
    return f"{heading}: {rendered}."


class _PlannerQueryHandler(IntentHandler):
    view_name: ClassVar[str]
    heading: ClassVar[str]
    empty_text: ClassVar[str]

    def __init__(
        self,
        planner_service: PlannerService,
        *,
        timezone_provider: Callable[[], ZoneInfo] | None = None,
    ) -> None:
        self._planner_service = planner_service
        self._timezone_provider = timezone_provider or system_timezone

    async def handle(
        self,
        request: RequestContext,
        intent: RecognizedIntent,
    ) -> IntentResult:
        timezone = self._timezone_provider()
        snapshot = self._planner_service.snapshot(
            request.principal_id,
            timezone=timezone,
        )
        items: tuple[PlannerItem, ...] = getattr(snapshot, self.view_name)

        return IntentResult(
            text=_render_items(
                self.heading,
                self._empty_text(snapshot),
                items,
            ),
            data={
                "intent": self.intent_name,
                "view": self.view_name,
                "count": len(items),
                "task_ids": tuple(item.task.id for item in items),
                "list_ids": tuple(item.task_list.id for item in items),
                "summaries": tuple(item.task.summary for item in items),
                "timezone": snapshot.timezone,
                "as_of": snapshot.as_of,
                "upcoming_days": snapshot.upcoming_days,
            },
        )

    def _empty_text(self, snapshot: PlannerSnapshot) -> str:
        return self.empty_text


class PlannerTodayHandler(_PlannerQueryHandler):
    intent_name = "PorterPlannerToday"
    view_name = "today"
    heading = "Today"
    empty_text = "You have no tasks due today."


class PlannerOverdueHandler(_PlannerQueryHandler):
    intent_name = "PorterPlannerOverdue"
    view_name = "overdue"
    heading = "Overdue"
    empty_text = "You have no overdue tasks."


class PlannerUpcomingHandler(_PlannerQueryHandler):
    intent_name = "PorterPlannerUpcoming"
    view_name = "upcoming"
    heading = "Upcoming"
    empty_text = ""

    def _empty_text(self, snapshot: PlannerSnapshot) -> str:
        return (
            "You have no upcoming tasks in the next "
            f"{snapshot.upcoming_days} days."
        )


class PlannerUnscheduledHandler(_PlannerQueryHandler):
    intent_name = "PorterPlannerUnscheduled"
    view_name = "unscheduled"
    heading = "Unscheduled"
    empty_text = "You have no unscheduled tasks."


__all__ = [
    "PlannerOverdueHandler",
    "PlannerTodayHandler",
    "PlannerUnscheduledHandler",
    "PlannerUpcomingHandler",
]
