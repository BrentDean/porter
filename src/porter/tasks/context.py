from __future__ import annotations

from porter.core.models import RequestContext
from porter.intents.context import (
    IntentRecognitionContext,
    IntentSlotValue,
)
from porter.tasks import TaskService


class TaskIntentRecognitionContextProvider:
    def __init__(self, task_service: TaskService) -> None:
        self._task_service = task_service

    def context_for(
        self,
        request: RequestContext,
    ) -> IntentRecognitionContext:
        task_lists = self._task_service.list_lists(request.principal_id)
        return IntentRecognitionContext(
            slot_values={
                "name": tuple(
                    IntentSlotValue(
                        text=task_list.name,
                        value=task_list.name,
                        context={"domain": "todo"},
                    )
                    for task_list in task_lists
                )
            }
        )
