"""Step 34: real places in the plan.

Specified by plan step 34, contracts §2.3 (place_ref) and §3 (tags match by place_id), and D27:
the planner's places feed compose as refs (p1, p2…); a stop citing a ref gets that place's
place_id, address, coordinates and rating, and its items get source "Geoapify"; home, airports
and the hotel are geocoded; an unknown ref is ignored (no coordinates); numbers in the draft and
the weather's city coordinates are never used; tags stay stable by place_id across versions.

All offline: mock tool mode, no GEOAPIFY_KEY, the fake LLM, a temp DB (conftest).
"""

import asyncio
import copy
import json
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agent import pipeline
from app.agent.planner import Finding
from app.agent.postprocess import CityWeather, StopPlace, build_itinerary
from app.agent.tags import assign_tags
from app.agent.turn import TurnLlms
from app.api.chat import get_llm
from app.core.config import Settings
from app.llm.fake_provider import FakeProvider, load_fake_data
from app.schemas.itinerary import Itinerary, ItineraryDraft, itinerary_errors
from app.schemas.profile import TripProfile
from app.tools import places
from app.tools.common import ToolResult, tool_error, tool_ok

TODAY = date(2027, 2, 1)
TECH = {
    "id": "geoapify:mock_tech_interactive",
    "name": "The Tech Interactive",
    "address": "201 South Market Street, San Jose, CA 95113, United States of America",
    "lat": 37.3316,
    "lng": -121.8901,
    "category": "entertainment.museum",
    "rating": 4.6,
}
WINCHESTER = {
    "id": "geoapify:mock_winchester_mystery_house",
    "name": "Winchester Mystery House",
    "address": "525 South Winchester Boulevard, San Jose, CA 95128",
    "lat": 37.3184,
    "lng": -121.9511,
    "category": "tourism.sights",
    "rating": None,
}
FIXED_KINDS = {"home", "airport", "lodging"}
TRIP_MESSAGE = "San Jose, first weekend of March, just me. I like tech, food and gardens."

Event = tuple[str, dict[str, Any]]


@pytest.fixture(autouse=True)
def offline_places(monkeypatch: pytest.MonkeyPatch) -> None:
    # backend/.env may hold a real GEOAPIFY_KEY: force mock mode with no key in the places tool.
    monkeypatch.setattr(
        places, "get_settings",
        lambda: Settings(_env_file=None, llm_provider="fake", tool_provider_mode="mock"),
    )
    monkeypatch.setattr(places, "is_mock", lambda: True)


# --- helpers --------------------------------------------------------------------------------


def _profile(**updates: Any) -> TripProfile:
    fields: dict[str, Any] = dict(
        budget_level="budget", cities=["San Jose, CA"], travelers=1,
        start_date=date(2027, 3, 5), end_date=date(2027, 3, 7), origin="College Station, TX",
    )
    fields.update(updates)
    return TripProfile(**fields)


def _raw_v1() -> dict[str, Any]:
    return load_fake_data("draft_sanjose_v1")


def _stop(raw: dict[str, Any], key: str) -> dict[str, Any]:
    return next(stop for stop in raw["stops"] if stop["key"] == key)


def _found(ref: str, data: dict[str, Any], tool: str = "search_places") -> Finding:
    return Finding(ref=ref, tool=tool, data=dict(data))


def _compose(
    raw: dict[str, Any],
    findings: list[Finding] | None = None,
    previous: list[Itinerary] | None = None,
    profile: TripProfile | None = None,
    weather: list[CityWeather] | None = None,
) -> Itinerary:
    plan = asyncio.run(
        pipeline.compose(
            FakeProvider(drafts=[raw]), profile or _profile(), [], previous or [], TODAY,
            weather=weather, findings=findings or [],
        )
    )
    assert itinerary_errors(plan) == []
    return plan


def _stop_named(plan: Itinerary, name: str) -> Any:
    return next(stop for stop in plan.stops if stop.name == name)


def _items_at(plan: Itinerary, tag: str) -> list[Any]:
    return [item for day in plan.days for item in day.items if item.stop_tag == tag]


def _record_geocode(
    monkeypatch: pytest.MonkeyPatch, precise_flags: dict[str, bool] | None = None
) -> list[str]:
    """Replace the geocoder with one that records its queries (and, into `precise_flags`, each
    query's `precise` argument) and puts every place at 1, 2."""
    queries: list[str] = []

    def fake_geocode(query: str, client: Any = None, precise: bool = False) -> ToolResult:
        queries.append(query)
        if precise_flags is not None:
            precise_flags[query] = precise
        return tool_ok({"name": query, "address": f"geo: {query}", "lat": 1.0, "lng": 2.0,
                        "source": "Geoapify"})

    monkeypatch.setattr(pipeline.places_tool, "geocode", fake_geocode)
    return queries


def _build(
    raw: dict[str, Any],
    previous: list[Itinerary] | None = None,
    stop_places: dict[str, StopPlace] | None = None,
) -> Itinerary:
    plan = build_itinerary(
        ItineraryDraft.model_validate(raw), previous or [], _profile(), None, stop_places
    )
    assert isinstance(plan, Itinerary), plan
    assert itinerary_errors(plan) == []
    return plan


def _place(place_id: str, lat: float = 37.0, lng: float = -121.0) -> StopPlace:
    return StopPlace(lat=lat, lng=lng, address="somewhere", place_id=place_id, source="Geoapify")


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


# --- the compose prompt lists the found places by ref ---------------------------------------


def test_compose_system_lists_found_places_with_refs() -> None:
    system = pipeline.build_system(
        _profile(), TODAY, findings=[_found("p1", TECH), _found("p2", WINCHESTER)]
    )

    assert "## Places found" in system
    assert "- p1 · The Tech Interactive · entertainment.museum · " in system
    assert TECH["address"] in system and "rating 4.6" in system
    assert "- p2 · Winchester Mystery House · tourism.sights · " in system


def test_compose_system_lists_a_place_found_twice_once() -> None:
    system = pipeline.build_system(_profile(), TODAY, findings=[_found("p1", TECH), _found("p4", TECH)])

    assert system.count("The Tech Interactive") == 1
    assert "- p1 · " in system and "- p4 · " not in system


def test_compose_system_has_no_places_section_without_findings() -> None:
    assert "## Places found" not in pipeline.build_system(_profile(), TODAY, findings=[])


# --- coordinates come from tools, never from the draft or the weather -----------------------


def test_referenced_stop_gets_the_tool_place_even_if_the_draft_has_numbers() -> None:
    raw = _raw_v1()
    tech = _stop(raw, "s7")
    tech.update(place_ref="p1", lat=1.5, lng=2.5, address="Made-up 1 St", place_id="llm:fake",
                rating=1.0)

    plan = _compose(raw, [_found("p1", TECH)])
    stop = _stop_named(plan, "The Tech Interactive")

    assert (stop.lat, stop.lng) == (TECH["lat"], TECH["lng"])
    assert stop.place_id == TECH["id"]
    assert stop.address == TECH["address"]
    assert stop.rating == 4.6


def test_unreferenced_ordinary_stop_ignores_draft_numbers() -> None:
    raw = _raw_v1()
    _stop(raw, "s8").update(lat=37.3, lng=-121.9)  # Winchester, no ref

    plan = _compose(raw, [_found("p1", TECH)])
    stop = _stop_named(plan, "Winchester Mystery House")

    assert stop.lat is None and stop.lng is None and stop.place_id is None


def test_weather_city_coordinates_never_become_stop_coordinates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _record_geocode(monkeypatch)  # every geocoded stop lands at 1, 2
    weather = [CityWeather(name="San Jose, CA", lat=37.33939, lng=-121.89496)]

    plan = _compose(_raw_v1(), [], weather=weather)

    assert all((s.lat, s.lng) != (37.33939, -121.89496) for s in plan.stops)
    # Since step 34a every stop without a ref is geocoded (D27), so all coordinates are the
    # geocoder's, none the weather's.
    assert all((s.lat, s.lng) == (1.0, 2.0) for s in plan.stops)


def test_items_at_found_places_have_source_geoapify() -> None:
    raw = _raw_v1()
    _stop(raw, "s7")["place_ref"] = "p1"

    plan = _compose(raw, [_found("p1", TECH)])
    tech_tag = _stop_named(plan, "The Tech Interactive").tag
    others = [item for day in plan.days for item in day.items if item.stop_tag != tech_tag]

    assert _items_at(plan, tech_tag) and all(i.source == "Geoapify" for i in _items_at(plan, tech_tag))
    assert others and all(item.source == "AI suggestion" for item in others)


def test_a_ref_from_a_non_places_tool_is_not_used_as_a_place() -> None:
    raw = _raw_v1()
    # Places (p…) and, since step 39, hotels (h…) can be cited; any other tool's result can't.
    _stop(raw, "s4")["place_ref"] = "r1"

    plan = _compose(raw, [_found("r1", {**TECH, "id": "other:1"}, tool="search_flights")])

    assert _stop_named(plan, "Pacific Inn San Jose").place_id is None


# --- fixed points are geocoded --------------------------------------------------------------


def test_airport_without_ref_is_geocoded_from_its_address() -> None:
    plan = _compose(_raw_v1(), [])  # the mock geocoder matches a comma part ("Houston")
    iah = _stop_named(plan, "IAH")

    assert (iah.lat, iah.lng) == (29.7589382, -95.3676974)
    assert iah.place_id is None
    assert all(item.source == "AI suggestion" for item in _items_at(plan, iah.tag))


def test_fixed_points_geocode_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    queries = _record_geocode(monkeypatch)
    raw = _raw_v1()
    _stop(raw, "s3")["address"] = None  # San Jose Airport without an address → name + day city

    plan = _compose(raw, [], profile=_profile(origin="College Station, TX"))

    # Since step 34a ordinary stops are geocoded too, always by "name, day city", never by the
    # address the LLM wrote for them (D27). Since step 39 a hotel without a hotel ref is one of
    # them ("Pacific Inn San Jose, San Jose").
    by_address = {"home", "airport"}
    ordinary = [f"{s['name']}, San Jose" for s in raw["stops"] if s["kind"] not in by_address]
    assert sorted(queries) == sorted([
        "College Station, TX",              # home → the profile's origin
        "2800 N Terminal Rd, Houston, TX",  # IAH → its address
        "San Jose Airport, San Jose",       # no address → name, city of its day
        *ordinary,
    ])
    assert "525 S Winchester Blvd, San Jose, CA" not in queries
    assert all((s.lat, s.lng) == (1.0, 2.0) for s in plan.stops)


def test_airport_and_hotel_geocode_precisely_but_home_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A city-level match is right for home (the origin city) but would pin an airport or the
    # hotel at the city centre (D27).
    flags: dict[str, bool] = {}
    _record_geocode(monkeypatch, flags)

    _compose(_raw_v1(), [], profile=_profile(origin="College Station, TX"))

    assert flags["College Station, TX"] is False
    assert flags["2800 N Terminal Rd, Houston, TX"] is True
    assert flags["Pacific Inn San Jose, San Jose"] is True  # by name since step 39


def test_home_without_origin_uses_its_address(monkeypatch: pytest.MonkeyPatch) -> None:
    queries = _record_geocode(monkeypatch)

    _compose(_raw_v1(), [], profile=_profile(origin=None))

    assert "College Station, TX" in queries  # the draft's home address


def test_referenced_airport_uses_the_place_not_the_geocoder(monkeypatch: pytest.MonkeyPatch) -> None:
    queries = _record_geocode(monkeypatch)
    raw = _raw_v1()
    _stop(raw, "s3")["place_ref"] = "p1"
    airport = {**TECH, "id": "geoapify:sjc", "name": "San Jose Airport", "lat": 37.36, "lng": -121.93}

    plan = _compose(raw, [_found("p1", airport)])

    assert _stop_named(plan, "San Jose Airport").place_id == "geoapify:sjc"
    assert "1701 Airport Blvd, San Jose, CA" not in queries


def test_failed_geocode_leaves_the_stop_off_the_map(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pipeline.places_tool, "geocode",
        lambda query, **_: tool_error("Place lookup failed: HTTP 500"),
    )

    plan = _compose(_raw_v1(), [])

    assert all(stop.lat is None and stop.lng is None for stop in plan.stops)


# --- a bad ref is handled -------------------------------------------------------------------


def test_unknown_ref_is_ignored_and_the_stop_has_no_coordinates() -> None:
    raw = _raw_v1()
    _stop(raw, "s7")["place_ref"] = "p99"
    _stop(raw, "s8")["place_ref"] = "not-a-ref"

    plan = _compose(raw, [_found("p1", TECH)])

    for name in ("The Tech Interactive", "Winchester Mystery House"):
        stop = _stop_named(plan, name)
        assert stop.lat is None and stop.lng is None and stop.place_id is None
        assert all(item.source == "AI suggestion" for item in _items_at(plan, stop.tag))


def test_ref_to_a_place_without_coordinates_is_ignored() -> None:
    raw = _raw_v1()
    _stop(raw, "s7")["place_ref"] = "p1"

    plan = _compose(raw, [_found("p1", {**TECH, "lat": None, "lng": None})])

    assert _stop_named(plan, "The Tech Interactive").lat is None


# --- postprocess copies the tool place ------------------------------------------------------


def test_postprocess_copies_place_fields_and_sets_source() -> None:
    plan = _build(_raw_v1(), stop_places={
        "s7": StopPlace(lat=37.3316, lng=-121.8901, address="201 S Market", place_id="geoapify:t",
                        rating=4.6, source="Geoapify"),
        "s1": StopPlace(lat=30.6, lng=-96.3),  # a geocoded home: no place, default source
    })
    tech = _stop_named(plan, "The Tech Interactive")
    home = _stop_named(plan, "Home")

    assert (tech.lat, tech.lng, tech.address, tech.place_id, tech.rating) == (
        37.3316, -121.8901, "201 S Market", "geoapify:t", 4.6
    )
    assert all(item.source == "Geoapify" for item in _items_at(plan, tech.tag))
    assert (home.lat, home.lng, home.place_id) == (30.6, -96.3, None)
    assert home.address == "College Station, TX"  # no tool address → the draft's
    assert all(item.source == "AI suggestion" for item in _items_at(plan, home.tag))


# --- v2 tag stability by place_id -----------------------------------------------------------


def test_renamed_stop_with_the_same_place_id_keeps_its_letter() -> None:
    v1 = _build(_raw_v1(), stop_places={"s7": _place("geoapify:tech")})
    tech_tag = _stop_named(v1, "The Tech Interactive").tag
    raw2 = _raw_v1()
    _stop(raw2, "s7")["name"] = "Tech Interactive Museum"

    v2 = _build(raw2, [v1], {"s7": _place("geoapify:tech")})

    assert _stop_named(v2, "Tech Interactive Museum").tag == tech_tag
    assert [s.tag for s in v2.stops] == [s.tag for s in v1.stops]


def test_same_name_with_a_different_place_id_gets_a_new_letter() -> None:
    v1 = _build(_raw_v1(), stop_places={"s7": _place("geoapify:tech")})
    tech_tag = _stop_named(v1, "The Tech Interactive").tag

    v2 = _build(_raw_v1(), [v1], {"s7": _place("geoapify:other-tech")})
    new_tech = _stop_named(v2, "The Tech Interactive")

    assert new_tech.tag != tech_tag
    assert new_tech.tag not in {s.tag for s in v1.stops}  # removed letters are never reused


def test_two_new_same_name_stops_with_different_place_ids_get_different_letters() -> None:
    # v1 has one "Philz Coffee" without a place_id; v2 has two, at different places. Both may
    # name-match the old stop, but its letter can go to only one of them, and neither is dropped.
    raw1 = _raw_v1()
    _stop(raw1, "s6")["name"] = "Philz Coffee"
    v1 = _build(raw1)
    old_tag = _stop_named(v1, "Philz Coffee").tag
    raw2 = copy.deepcopy(raw1)
    _stop(raw2, "s9")["name"] = "Philz Coffee"
    stop_places = {"s6": _place("geoapify:philz-a"), "s9": _place("geoapify:philz-b")}

    tags = assign_tags(ItineraryDraft.model_validate(raw2), [v1], {"s6": "geoapify:philz-a",
                                                                  "s9": "geoapify:philz-b"})
    v2 = _build(raw2, [v1], stop_places)
    philz = [s for s in v2.stops if s.name == "Philz Coffee"]

    assert tags["s6"] != tags["s9"]
    assert old_tag in (tags["s6"], tags["s9"])
    assert len(philz) == 2
    assert {s.place_id for s in philz} == {"geoapify:philz-a", "geoapify:philz-b"}
    assert len({s.tag for s in v2.stops}) == len(v2.stops)


def test_same_place_id_under_two_keys_is_one_stop() -> None:
    plan = _build(_raw_v1(), stop_places={"s7": _place("geoapify:x"), "s8": _place("geoapify:x")})

    assert [s.place_id for s in plan.stops].count("geoapify:x") == 1
    tech_tag = next(s.tag for s in plan.stops if s.place_id == "geoapify:x")
    # Both keys' items point at that one stop (Tech's and Winchester's items).
    assert len(_items_at(plan, tech_tag)) == 2


def test_edit_keeps_coordinates_of_unchanged_stops_by_name() -> None:
    raw = _raw_v1()
    _stop(raw, "s7")["place_ref"] = "p1"
    v1 = _compose(raw, [_found("p1", TECH)])

    # An edit copies stops with their letter tags as keys and no refs; no new findings.
    v2 = _compose(pipeline.as_draft(v1).model_dump(mode="json"), [], previous=[v1])
    tech1 = _stop_named(v1, "The Tech Interactive")
    tech2 = _stop_named(v2, "The Tech Interactive")

    assert (tech2.tag, tech2.lat, tech2.lng, tech2.place_id) == (
        tech1.tag, tech1.lat, tech1.lng, tech1.place_id
    )
    assert all(item.source == "Geoapify" for item in _items_at(v2, tech2.tag))


# --- with the fake LLM through the API ------------------------------------------------------


def _use_fake(client: TestClient) -> FakeProvider:
    provider = FakeProvider()
    client.app.dependency_overrides[get_llm] = lambda: TurnLlms(provider, provider)  # type: ignore[attr-defined]
    return provider


def _generate_plan(client: TestClient) -> tuple[str, Itinerary]:
    session_id = client.post("/api/sessions").json()["id"]
    client.post(f"/api/sessions/{session_id}/messages", json={"content": TRIP_MESSAGE})
    response = client.post(f"/api/sessions/{session_id}/generate", json={})
    assert response.status_code == 200
    return session_id, _plan_from(_parse_sse(response.text))


def test_generated_plan_has_real_coordinates_on_referenced_stops(client: TestClient) -> None:
    _use_fake(client)
    mock_places = {
        place["name"]: place
        for interest in ("tech", "food", "gardens")
        for place in places.search(0, 0, interest).data
    }

    _, plan = _generate_plan(client)

    assert itinerary_errors(plan) == []
    # The fake cites found places by name ("San Pedro Square" ↔ "San Pedro Square Market").
    expected = {
        "The Tech Interactive": "The Tech Interactive",
        "San Pedro Square": "San Pedro Square Market",
        "Guadalupe River Park": "Guadalupe River Park",
    }
    for stop_name, place_name in expected.items():
        stop = _stop_named(plan, stop_name)
        place = mock_places[place_name]
        assert (stop.lat, stop.lng) == (place["lat"], place["lng"]), stop_name
        assert stop.place_id == place["id"] and stop.place_id.startswith("geoapify:")
        assert stop.address == place["address"]
        assert all(item.source == "Geoapify" for item in _items_at(plan, stop.tag))
    # Fixed points are geocoded; a stop with no found place stays off the map.
    assert all(s.lat is not None and s.lng is not None for s in plan.stops if s.kind in FIXED_KINDS)
    winchester = _stop_named(plan, "Winchester Mystery House")
    assert winchester.lat is None and winchester.place_id is None


def test_edit_through_the_api_keeps_letters_and_places(client: TestClient) -> None:
    _use_fake(client)
    session_id, v1 = _generate_plan(client)

    response = client.post(
        f"/api/sessions/{session_id}/messages", json={"content": "change [F] to something vegan"}
    )
    assert response.status_code == 200
    v2 = _plan_from(_parse_sse(response.text))

    assert v2.version == 2
    for stop in v1.stops:
        if stop.name == "Baconhouse":
            continue
        same = _stop_named(v2, stop.name)
        assert (same.tag, same.lat, same.lng, same.place_id) == (
            stop.tag, stop.lat, stop.lng, stop.place_id
        ), stop.name
