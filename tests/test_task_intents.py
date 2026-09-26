from pathlib import Path

import pytest

from porter.app import build_application
from porter.core.models import Message, RequestContext, RequestSource
from porter.intents import IntentResult
from porter.tasks import TaskStatus


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


@pytest.mark.asyncio
async def test_add_item_uses_upstream_sentence_and_principal_list(
    tmp_path: Path,
) -> None:
    application = build_application(
        env={"PORTER_DATA_DIR": str(tmp_path)},
        home=tmp_path,
    )
    task_list = application.task_service.create_list(
        "alice",
        "Shopping",
    )

    result = await application.deterministic_executor.execute(
        _request("add apples to my Shopping list")
    )

    assert isinstance(result, IntentResult)
    assert result.data["intent"] == "HassListAddItem"
    assert result.data["outcome"] == "succeeded"
    tasks = application.task_service.list_tasks(
        "alice",
        list_id=task_list.id,
    )
    assert [task.summary for task in tasks] == ["apples"]


@pytest.mark.asyncio
async def test_complete_item_marks_only_matching_incomplete_task(
    tmp_path: Path,
) -> None:
    application = build_application(
        env={"PORTER_DATA_DIR": str(tmp_path)},
        home=tmp_path,
    )
    task_list = application.task_service.create_list("alice", "Work")
    task = application.task_service.add_task(
        "alice",
        task_list.id,
        "Submit report",
    )

    result = await application.deterministic_executor.execute(
        _request("complete submit report from my Work list")
    )

    assert isinstance(result, IntentResult)
    assert result.data["intent"] == "HassListCompleteItem"
    assert result.data["task_id"] == task.id
    assert (
        application.task_service.get_task("alice", task.id).status
        is TaskStatus.COMPLETED
    )


@pytest.mark.asyncio
async def test_remove_item_deletes_matching_task(
    tmp_path: Path,
) -> None:
    application = build_application(
        env={"PORTER_DATA_DIR": str(tmp_path)},
        home=tmp_path,
    )
    task_list = application.task_service.create_list(
        "alice",
        "Shopping",
    )
    task = application.task_service.add_task(
        "alice",
        task_list.id,
        "apples",
    )

    result = await application.deterministic_executor.execute(
        _request("remove apples from my Shopping list")
    )

    assert isinstance(result, IntentResult)
    assert result.data["intent"] == "HassListRemoveItem"
    assert result.data["task_id"] == task.id
    assert application.task_service.list_tasks(
        "alice",
        list_id=task_list.id,
    ) == ()


@pytest.mark.asyncio
async def test_duplicate_summaries_return_ambiguity_without_mutation(
    tmp_path: Path,
) -> None:
    application = build_application(
        env={"PORTER_DATA_DIR": str(tmp_path)},
        home=tmp_path,
    )
    task_list = application.task_service.create_list("alice", "Work")
    first = application.task_service.add_task(
        "alice",
        task_list.id,
        "Submit report",
    )
    second = application.task_service.add_task(
        "alice",
        task_list.id,
        "Submit report",
    )

    result = await application.deterministic_executor.execute(
        _request("complete submit report from my Work list")
    )

    assert isinstance(result, IntentResult)
    assert result.data["outcome"] == "ambiguous"
    assert set(result.data["candidate_task_ids"]) == {
        first.id,
        second.id,
    }
    assert (
        application.task_service.get_task("alice", first.id).status
        is TaskStatus.NEEDS_ACTION
    )
    assert (
        application.task_service.get_task("alice", second.id).status
        is TaskStatus.NEEDS_ACTION
    )


@pytest.mark.asyncio
async def test_same_list_name_isolated_between_principals(
    tmp_path: Path,
) -> None:
    application = build_application(
        env={"PORTER_DATA_DIR": str(tmp_path)},
        home=tmp_path,
    )
    alice_list = application.task_service.create_list(
        "alice",
        "Shopping",
    )
    bob_list = application.task_service.create_list(
        "bob",
        "Shopping",
    )

    result = await application.deterministic_executor.execute(
        _request("add apples to my Shopping list", principal_id="alice")
    )

    assert isinstance(result, IntentResult)
    assert [task.summary for task in application.task_service.list_tasks(
        "alice",
        list_id=alice_list.id,
    )] == ["apples"]
    assert application.task_service.list_tasks(
        "bob",
        list_id=bob_list.id,
    ) == ()
