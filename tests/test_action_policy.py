import pytest

from porter.core.exceptions import ActionNotAuthorized
from porter.core.models import Message, RequestContext, RequestSource
from porter.policy import ActionEffect, ActionPolicy, action_effect_for_intent


def _request(source: RequestSource) -> RequestContext:
    return RequestContext(
        messages=(Message(role="user", content="test"),),
        principal_id="test-user",
        source=source,
    )


def test_current_intents_have_expected_effect_classes() -> None:
    assert action_effect_for_intent("PorterStorageLayout") is ActionEffect.READ
    assert action_effect_for_intent("HassListAddItem") is ActionEffect.LOCAL_WRITE
    assert action_effect_for_intent("PorterPlexRestart") is ActionEffect.SYSTEM_WRITE
    assert action_effect_for_intent("PorterTimerCreate") is ActionEffect.LOCAL_WRITE
    assert action_effect_for_intent("PorterTimerList") is ActionEffect.READ
    assert action_effect_for_intent("PorterTimerCancel") is ActionEffect.LOCAL_WRITE


@pytest.mark.parametrize("source", tuple(RequestSource))
def test_read_actions_are_allowed_from_current_sources(source: RequestSource) -> None:
    ActionPolicy().authorize(
        _request(source),
        action_name="PorterRead",
        effect=ActionEffect.READ,
    )


@pytest.mark.parametrize(
    "effect",
    (ActionEffect.LOCAL_WRITE, ActionEffect.SYSTEM_WRITE),
)
def test_writes_are_allowed_from_cli(effect: ActionEffect) -> None:
    ActionPolicy().authorize(
        _request(RequestSource.CLI),
        action_name="PorterWrite",
        effect=effect,
    )


@pytest.mark.parametrize(
    "source",
    (
        RequestSource.VOICE,
        RequestSource.AUTOMATION,
        RequestSource.HOME_ASSISTANT,
        RequestSource.WEB,
    ),
)
@pytest.mark.parametrize(
    "effect",
    (ActionEffect.LOCAL_WRITE, ActionEffect.SYSTEM_WRITE),
)
def test_writes_fail_closed_from_other_sources(
    source: RequestSource,
    effect: ActionEffect,
) -> None:
    with pytest.raises(
        ActionNotAuthorized,
        match=f"{effect.value}.*not authorized",
    ):
        ActionPolicy().authorize(
            _request(source),
            action_name="PorterWrite",
            effect=effect,
        )


def test_unclassified_intent_fails_closed() -> None:
    with pytest.raises(ValueError, match="no action classification"):
        action_effect_for_intent("PorterFutureDangerousAction")
