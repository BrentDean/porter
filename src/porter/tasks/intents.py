from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from porter.core.models import RequestContext
from porter.intents.handlers import IntentHandler
from porter.intents.models import IntentResult, RecognizedIntent
from porter.tasks import (
    Task,
    TaskList,
    TaskListNotFoundError,
    TaskService,
    TaskStatus,
)


def _required_text_slot(
    intent: RecognizedIntent,
    name: str,
) -> str:
    value = intent.slots.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"intent slot must be non-empty text: {name}")
    return value.strip()


def _match_key(value: str) -> str:
    return unicodedata.normalize("NFKC", value.strip()).casefold()


@dataclass(frozen=True, slots=True)
class _TaskMatch:
    task_list: TaskList
    item_text: str
    tasks: tuple[Task, ...]


class _TaskIntentHandler(IntentHandler):
    def __init__(self, task_service: TaskService) -> None:
        self._task_service = task_service

    def _get_list(
        self,
        request: RequestContext,
        intent: RecognizedIntent,
    ) -> TaskList | IntentResult:
        list_name = _required_text_slot(intent, "name")
        try:
            return self._task_service.get_list_by_name(
                request.principal_id,
                list_name,
            )
        except TaskListNotFoundError:
            return IntentResult(
                text=f"I couldn't find the {list_name} list.",
                data={
                    "intent": self.intent_name,
                    "operation": "resolve_list",
                    "outcome": "not_found",
                    "list_name": list_name,
                },
            )

    def _find_tasks(
        self,
        request: RequestContext,
        intent: RecognizedIntent,
        *,
        status: TaskStatus | None = None,
    ) -> _TaskMatch | IntentResult:
        task_list = self._get_list(request, intent)
        if isinstance(task_list, IntentResult):
            return task_list

        item_text = _required_text_slot(intent, "item")
        tasks = self._task_service.list_tasks(
            request.principal_id,
            list_id=task_list.id,
            status=status,
        )

        id_matches = tuple(
            task
            for task in tasks
            if task.id == item_text
        )
        if len(id_matches) == 1:
            return _TaskMatch(
                task_list=task_list,
                item_text=item_text,
                tasks=id_matches,
            )

        item_key = _match_key(item_text)
        summary_matches = tuple(
            task
            for task in tasks
            if _match_key(task.summary) == item_key
        )
        if not summary_matches:
            return IntentResult(
                text=(
                    f"I couldn't find {item_text} "
                    f"on {task_list.name}."
                ),
                data={
                    "intent": self.intent_name,
                    "operation": "resolve_task",
                    "outcome": "not_found",
                    "list_id": task_list.id,
                    "list_name": task_list.name,
                    "item": item_text,
                },
            )

        if len(summary_matches) > 1:
            return IntentResult(
                text=(
                    f"There is more than one {item_text} "
                    f"on {task_list.name}; specify which one."
                ),
                data={
                    "intent": self.intent_name,
                    "operation": "resolve_task",
                    "outcome": "ambiguous",
                    "list_id": task_list.id,
                    "list_name": task_list.name,
                    "item": item_text,
                    "candidate_task_ids": tuple(
                        task.id
                        for task in summary_matches
                    ),
                },
            )

        return _TaskMatch(
            task_list=task_list,
            item_text=item_text,
            tasks=summary_matches,
        )


class ListAddItemHandler(_TaskIntentHandler):
    intent_name = "HassListAddItem"

    async def handle(
        self,
        request: RequestContext,
        intent: RecognizedIntent,
    ) -> IntentResult:
        task_list = self._get_list(request, intent)
        if isinstance(task_list, IntentResult):
            return task_list

        item_text = _required_text_slot(intent, "item")
        task = self._task_service.add_task(
            request.principal_id,
            task_list.id,
            item_text,
        )
        return IntentResult(
            text=f"Added {task.summary} to {task_list.name}.",
            data={
                "intent": self.intent_name,
                "operation": "add",
                "outcome": "succeeded",
                "list_id": task_list.id,
                "list_name": task_list.name,
                "task_id": task.id,
                "summary": task.summary,
                "status": task.status.value,
            },
        )


class ListCompleteItemHandler(_TaskIntentHandler):
    intent_name = "HassListCompleteItem"

    async def handle(
        self,
        request: RequestContext,
        intent: RecognizedIntent,
    ) -> IntentResult:
        match = self._find_tasks(
            request,
            intent,
            status=TaskStatus.NEEDS_ACTION,
        )
        if isinstance(match, IntentResult):
            return match

        task = self._task_service.complete_task(
            request.principal_id,
            match.tasks[0].id,
        )
        return IntentResult(
            text=f"Completed {task.summary} on {match.task_list.name}.",
            data={
                "intent": self.intent_name,
                "operation": "complete",
                "outcome": "succeeded",
                "list_id": match.task_list.id,
                "list_name": match.task_list.name,
                "task_id": task.id,
                "summary": task.summary,
                "status": task.status.value,
            },
        )


class ListRemoveItemHandler(_TaskIntentHandler):
    intent_name = "HassListRemoveItem"

    async def handle(
        self,
        request: RequestContext,
        intent: RecognizedIntent,
    ) -> IntentResult:
        match = self._find_tasks(request, intent)
        if isinstance(match, IntentResult):
            return match

        task = match.tasks[0]
        self._task_service.delete_task(
            request.principal_id,
            task.id,
        )
        return IntentResult(
            text=f"Removed {task.summary} from {match.task_list.name}.",
            data={
                "intent": self.intent_name,
                "operation": "remove",
                "outcome": "succeeded",
                "list_id": match.task_list.id,
                "list_name": match.task_list.name,
                "task_id": task.id,
                "summary": task.summary,
            },
        )
