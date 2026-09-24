from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from porter.core.models import Message, RequestContext, RequestSource
from porter.tools.weather import WeatherTool
from porter.weather.geocoding import OpenMeteoGeocodingClient


def test_generic_geocoder_does_not_force_country() -> None:
    client = OpenMeteoGeocodingClient()
    query = parse_qs(urlparse(client.search_url("Toronto")).query)

    assert "countryCode" not in query


def test_geocoder_can_apply_explicit_country_scope() -> None:
    client = OpenMeteoGeocodingClient(country_code="us")
    query = parse_qs(urlparse(client.search_url("Hoboken")).query)

    assert query["countryCode"] == ["US"]


def test_weather_tool_only_considers_latest_user_turn() -> None:
    request = RequestContext(
        messages=(
            Message(role="user", content="weather in Hoboken"),
            Message(role="assistant", content="old weather response"),
            Message(role="user", content="explain ARP"),
        ),
        principal_id="local-user",
        source=RequestSource.CLI,
    )

    assert not WeatherTool().supports(request)
