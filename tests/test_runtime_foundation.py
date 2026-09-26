from __future__ import annotations

from datetime import UTC
from zoneinfo import ZoneInfo

from porter.core.clock import local_now, system_timezone, utc_now
from porter.core.models import Message, RequestContext, RequestSource


def test_clock_helpers_return_aware_zoneinfo_datetimes() -> None:
    utc_value = utc_now()
    local_value = local_now()

    assert utc_value.tzinfo is UTC
    assert isinstance(system_timezone(), ZoneInfo)
    assert isinstance(local_value.tzinfo, ZoneInfo)
    assert local_value.utcoffset() is not None


def test_request_context_exposes_only_latest_user_text() -> None:
    request = RequestContext(
        messages=(
            Message(role="user", content="old request"),
            Message(role="assistant", content="old response"),
            Message(role="user", content="current request"),
        ),
        principal_id="local-user",
        source=RequestSource.CLI,
    )

    assert request.latest_user_text == "current request"


def test_request_context_without_user_message_returns_none() -> None:
    request = RequestContext(
        messages=(Message(role="system", content="system only"),),
        principal_id="local-user",
        source=RequestSource.AUTOMATION,
    )

    assert request.latest_user_text is None
