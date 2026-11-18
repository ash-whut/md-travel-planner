"""Step 34a: edits look up new stops.

Specified by plan step 34a and D27: an edit that adds or replaces a stop runs one places search
(the fake planner matches prompts/planner.md), the new stop cites a found place and gets its
coordinates and place_id, and the other stops keep their letters and coordinates; an edit that
only moves or removes stops runs no search. A stop with no usable ref (and no same-named earlier
stop) is geocoded by "name, day city" with precise=True: a specific match gives a pin, a
city-level match gives none.

All offline: mock tool mode (or live mode over an httpx MockTransport), the fake LLM, a temp DB.
"""

import asyncio
import json
from datetime import date
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agent import pipeline
from app.agent.turn import TurnLlms
from app.api.chat import get_llm
from app.core.config import Settings
from app.llm.fake_provider import FakeProvider, load_fake_data
from app.schemas.itinerary import Itinerary, itinerary_errors
from app.schemas.profile import TripProfile
from app.tools import places
from app.tools.common import ToolResult, tool_ok

TODAY = date(2027, 2, 1)
TRIP_MESSAGE = "San Jose, first weekend of March, just me. I like tech, food and gardens."
REPLACE_MESSAGE = "replace [F] with something vegan"
MOVE_MESSAGE = "move [E] to day 2"
FIXED_KINDS = {"home", "airport", "lodging"}
# The recorded Good Karma Kitchen in tools/mocks/places_search.json.
GOOD_KARMA_ID = "geoapify:mock_good_karma_kitchen"
GOOD_KARMA_LAT, GOOD_KARMA_LNG = 37.3357, -121.8899

Event = tuple[str, dict[str, Any]]


@pytest.fixture(autouse=True)
def offline_places(monkeypatch: pytest.MonkeyPatch) -> None:
    # backend/.env may hold a real GEOAPIFY_KEY: force mock mode with no key in the places tool.
    monkeypatch.setattr(
        places, "get_settings",
        lambda: Settings(_env_file=None, llm_provider="fake", tool_provider_mode="mock"),
    )
    monkeypatch.setattr(places, "is_mock", lambda: True)
    monkeypatch.setattr(places, "NOMINATIM_INTERVAL_SECONDS", 0.0)


# --- helpers --------------------------------------------------------------------------------


def _profile() -> TripProfile:
    return TripProfile(
        budget_level="budget", cities=["San Jose, CA"], travelers=1,
        start_date=date(2027, 3, 5), end_date=date(2027, 3, 7), origin="College Station, TX",
    )


def _compose(
    raw: dict[str, Any], previous: list[Itinerary] | None = None,
    change_request: str | None = None,
) -> Itinerary:
    plan = asyncio.run(
        pipeline.compose(
            FakeProvider(drafts=[raw]), _profile(), [], previous or [], TODAY,
            change_request=change_request, findings=[],
        )
    )
    assert itinerary_errors(plan) == []
    return plan


def _stop_named(plan: Itinerary, name: str) -> Any:
    return next(stop for stop in plan.stops if stop.name == name)


def _items_at(plan: Itinerary, tag: str) -> list[Any]:
    return [item for day in plan.days for item in day.items if item.stop_tag == tag]


def _record_geocode(monkeypatch: pytest.MonkeyPatch) -> dict[str, bool]:
    """Replace the geocoder with one that puts every place at 1, 2 and records each query with
    its `precise` argument, in call order."""
    calls: dict[str, bool] = {}

    def fake_geocode(query: str, client: Any = None, precise: bool = False) -> ToolResult:
        calls[query] = precise
        return tool_ok({"name": query, "address": f"geo: {query}", "lat": 1.0, "lng": 2.0,
                        "source": "Geoapify"})

    monkeypatch.setattr(pipeline.places_tool, "geocode", fake_geocode)
    return calls


def _parse_sse(text: str) -> list[Event]:
    events: list[Event] = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        name, data = "message", []
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data.append(line[len("data:"):].lstrip(" "))
        if data:
            events.append((name, json.loads("\n".join(data))))
    return events


def _plan_from(events: list[Event]) -> Itinerary:
    plans = [data for name, data in events if name == "itinerary"]
    assert plans, f"no itinerary event in {events}"
    return Itinerary.model_validate(plans[-1])


def _finding_statuses(events: list[Event]) -> list[dict[str, Any]]:
    return [
        data for name, data in events
        if name == "status" and str(data.get("label", "")).startswith("Finding")
    ]


def _use_fake(client: TestClient) -> None:
    provider = FakeProvider()
    client.app.dependency_overrides[get_llm] = lambda: TurnLlms(provider, provider)  # type: ignore[attr-defined]


def _v1(client: TestClient) -> tuple[str, Itinerary]:
    session_id = client.post("/api/sessions").json()["id"]
    client.post(f"/api/sessions/{session_id}/messages", json={"content": TRIP_MESSAGE})
    response = client.post(f"/api/sessions/{session_id}/generate", json={})
    assert response.status_code == 200
    return session_id, _plan_from(_parse_sse(response.text))


def _send(client: TestClient, session_id: str, content: str) -> list[Event]:
    response = client.post(f"/api/sessions/{session_id}/messages", json={"content": content})
    assert response.status_code == 200
    return _parse_sse(response.text)


# --- the fake LLM through the API -----------------------------------------------------------


def test_replace_edit_runs_one_search(client: TestClient) -> None:
    _use_fake(client)
    session_id, _ = _v1(client)

    events = _send(client, session_id, REPLACE_MESSAGE)
    finding = _finding_statuses(events)

    assert len({status["label"] for status in finding}) == 1, finding
    assert [status["state"] for status in finding] == ["start", "end"]
    assert "Finding hotels" not in finding[0]["label"]


def test_replace_edit_new_stop_gets_the_found_place(client: TestClient) -> None:
    _use_fake(client)
    session_id, _ = _v1(client)

    v2 = _plan_from(_send(client, session_id, REPLACE_MESSAGE))
    karma = _stop_named(v2, "Good Karma Kitchen")

    assert itinerary_errors(v2) == []
    assert v2.version == 2
    assert karma.tag == "L"
    assert karma.place_id == GOOD_KARMA_ID
    assert (karma.lat, karma.lng) == (GOOD_KARMA_LAT, GOOD_KARMA_LNG)
    assert karma.address and "South 1st Street" in karma.address
    items = _items_at(v2, karma.tag)
    assert items and all(item.source == "Geoapify" for item in items)


def test_replace_edit_other_stops_keep_letters_and_coordinates(client: TestClient) -> None:
    _use_fake(client)
    session_id, v1 = _v1(client)

    v2 = _plan_from(_send(client, session_id, REPLACE_MESSAGE))

    for stop in v1.stops:
        if stop.name == "Baconhouse":
            assert stop.tag not in {s.tag for s in v2.stops}
            continue
        same = _stop_named(v2, stop.name)
        assert (same.tag, same.lat, same.lng, same.place_id) == (
            stop.tag, stop.lat, stop.lng, stop.place_id
        ), stop.name


def test_move_edit_runs_no_search(client: TestClient) -> None:
    _use_fake(client)
    session_id, _ = _v1(client)

    events = _send(client, session_id, MOVE_MESSAGE)

    assert _finding_statuses(events) == []
    assert _plan_from(events).version == 2


def test_move_edit_new_stop_without_a_place_stays_off_the_map(client: TestClient) -> None:
    # The fake's edit draft always has Good Karma Kitchen; with no search it cites no ref, and in
    # mock mode a precise lookup of a place name is a city-level miss, so it gets no pin.
    _use_fake(client)
    session_id, _ = _v1(client)

    v2 = _plan_from(_send(client, session_id, MOVE_MESSAGE))
    karma = _stop_named(v2, "Good Karma Kitchen")

    assert karma.lat is None and karma.lng is None and karma.place_id is None
    assert all(item.source == "AI suggestion" for item in _items_at(v2, karma.tag))


# --- the fallback geocode: queries ----------------------------------------------------------


def test_unreferenced_stop_is_geocoded_by_name_and_day_city_precisely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _record_geocode(monkeypatch)

    plan = _compose(load_fake_data("draft_sanjose_v1"))

    assert calls["Winchester Mystery House, San Jose"] is True
    assert "525 S Winchester Blvd, San Jose, CA" not in calls  # never the LLM's address
    assert all(precise for query, precise in calls.items() if query != "College Station, TX")
    winchester = _stop_named(plan, "Winchester Mystery House")
    assert (winchester.lat, winchester.lng, winchester.place_id) == (1.0, 2.0, None)
    assert all(item.source == "AI suggestion" for item in _items_at(plan, winchester.tag))


def test_edit_geocodes_only_the_new_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _record_geocode(monkeypatch)
    v1 = _compose(load_fake_data("draft_sanjose_v1"))
    calls.clear()

    v2 = _compose(load_fake_data("draft_sanjose_v2"), [v1], change_request=REPLACE_MESSAGE)

    # Unchanged stops copy their place from v1 by name; only the new stop is looked up.
    assert calls == {"Good Karma Kitchen, San Jose": True}
    assert (_stop_named(v2, "Good Karma Kitchen").lat, _stop_named(v2, "Good Karma Kitchen").lng) == (1.0, 2.0)


# --- the fallback geocode: specific vs city-level match (live path, fake transport) ---------


def _live_geocoder(
    monkeypatch: pytest.MonkeyPatch, specific: dict[str, tuple[float, float]]
) -> None:
    """Live mode with a Geoapify key over a fake transport. A query naming a place in `specific`
    gets a specific (amenity) match there; every other query gets only a city-level match for
    San Jose, from both Geoapify and Nominatim."""
    settings = Settings(_env_file=None, tool_provider_mode="live", geoapify_key="test-key")
    monkeypatch.setattr(places, "get_settings", lambda: settings)
    monkeypatch.setattr(places, "is_mock", lambda: False)

    def handler(request: httpx.Request) -> httpx.Response:
        text = request.url.params.get("text") or request.url.params.get("q") or ""
        hit = next((point for name, point in specific.items() if text.startswith(name)), None)
        if request.url.host == "api.geoapify.com":
            if hit is not None:
                result = {"name": text.split(",")[0], "formatted": f"{text}, CA, USA",
                          "lat": hit[0], "lon": hit[1], "result_type": "amenity"}
            else:
                result = {"name": "San Jose", "city": "San Jose", "formatted": "San Jose, CA, USA",
                          "lat": 37.3361663, "lon": -121.890591, "result_type": "city"}
            return httpx.Response(200, json={"results": [result]})
        # Nominatim (the fallback when Geoapify finds nothing usable): a city-level match only.
        return httpx.Response(200, json=[{
            "name": "San Jose", "display_name": "San Jose, Santa Clara County, California",
            "lat": "37.3361663", "lon": "-121.890591", "addresstype": "city", "type": "city",
        }])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    real_geocode = places.geocode

    def geocode(query: str, client_: Any = None, precise: bool = False) -> ToolResult:
        return real_geocode(query, client=client, precise=precise)

    monkeypatch.setattr(pipeline.places_tool, "geocode", geocode)


def test_fallback_specific_match_gives_a_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    _live_geocoder(monkeypatch, {"Winchester Mystery House": (37.3184, -121.9511)})

    plan = _compose(load_fake_data("draft_sanjose_v1"))
    winchester = _stop_named(plan, "Winchester Mystery House")

    assert (winchester.lat, winchester.lng) == (37.3184, -121.9511)
    assert winchester.place_id is None
    assert all(item.source == "AI suggestion" for item in _items_at(plan, winchester.tag))


def test_fallback_city_level_match_gives_no_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    _live_geocoder(monkeypatch, {"Winchester Mystery House": (37.3184, -121.9511)})

    plan = _compose(load_fake_data("draft_sanjose_v1"))

    # Every other ordinary stop only matched the city: no pin at the city centre.
    others = [s for s in plan.stops if s.kind not in FIXED_KINDS and s.name != "Winchester Mystery House"]
    assert others
    for stop in others:
        assert stop.lat is None and stop.lng is None, stop.name
    assert all((s.lat, s.lng) != (37.3361663, -121.890591) for s in plan.stops if s.kind != "home")
    # Home is the origin city, so a city-level match still pins it.
    assert _stop_named(plan, "Home").lat is not None
