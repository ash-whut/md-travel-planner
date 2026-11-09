"""Step 39: the hotel in the plan.

Specified by plan step 39, contracts §2.3 (hotel refs) and D29/D30: the planner calls
`search_hotels` (one search per city per plan, a second gets "skipped: limit"); compose sees the
found hotels as refs (h1…) and picks one; postprocess builds the `lodging` entry with prices and
`price_as_of` from the tool, never from the draft (total = per night × nights); the hotel is a
lettered stop with the tool's coordinates, and its item shows nights + the per-night cost with
the source "SerpApi Google Hotels · as of …". A no-price fallback result gives null prices
(the UI shows "check link"). An edit that keeps the hotel keeps its tool price.

All offline: mock tool mode, the fake LLM (or a scripted one), a temp DB (conftest).
"""

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest
from sqlmodel import Session

from app.agent import pipeline, planner
from app.agent.planner import Finding, run_planner
from app.agent.postprocess import HotelPrice, StopPlace, build_itinerary, hotel_source
from app.core.config import Settings
from app.db import repo
from app.llm.base import Message, ToolCall, ToolRound, ToolSpec
from app.llm.fake_provider import FakeProvider, cite_found_places, load_fake_data
from app.schemas.itinerary import Itinerary, ItineraryDraft, Money, itinerary_errors
from app.schemas.profile import TripProfile
from app.tools import hotels, places, registry
from app.tools.common import ToolResult, load_mock, tool_ok

TODAY = date(2027, 2, 1)
START, END = date(2027, 3, 5), date(2027, 3, 7)
AS_OF = "2026-11-09T01:30:00Z"
AS_OF_SOURCE = "SerpApi Google Hotels · as of Nov 9, 1:30 AM UTC"
REQUEST: list[Message] = [{"role": "user", "content": planner.PLANNER_REQUEST}]

PACIFIC = {
    "id": "serpapi:mock_pacific_inn",
    "name": "Pacific Inn San Jose",
    "address": None,
    "lat": 37.3398,
    "lng": -121.881,
    "rating": 3.6,
    "price_per_night": {"amount": 79, "currency": "USD"},
    "total_price": {"amount": 158, "currency": "USD"},
    "price_source": "serpapi_google_hotels",
    "price_as_of": AS_OF,
    "link": "https://www.example.com/pacific-inn-san-jose",
}
# A places-lodging fallback result (no SerpApi key or quota): no price.
UNPRICED = {
    "id": "geoapify:mock_hotel_de_anza",
    "name": "Hotel De Anza",
    "address": "233 West Santa Clara Street, San Jose, CA 95113",
    "lat": 37.3307,
    "lng": -121.8936,
    "rating": None,
    "price_per_night": None,
    "total_price": None,
    "price_source": "none",
    "price_as_of": None,
    "link": None,
}


@pytest.fixture(autouse=True)
def offline_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    # backend/.env may hold real GEOAPIFY / SERPAPI keys: force mock mode in both tools.
    settings = Settings(_env_file=None, llm_provider="fake", tool_provider_mode="mock")
    for module in (places, hotels):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
        monkeypatch.setattr(module, "is_mock", lambda: True)


# --- helpers --------------------------------------------------------------------------------


def _profile(**updates: Any) -> TripProfile:
    fields: dict[str, Any] = dict(
        budget_level="budget", cities=["San Jose, CA"], travelers=1,
        start_date=START, end_date=END, interests=["food"], origin="College Station, TX",
    )
    fields.update(updates)
    return TripProfile(**fields)


def _raw_v1(hotel_ref: str | None = None) -> dict[str, Any]:
    """The fake v1 draft: its hotel is stop s4 "Pacific Inn San Jose" with a $120 estimate."""
    raw = load_fake_data("draft_sanjose_v1")
    if hotel_ref is not None:
        _stop(raw, "s4")["place_ref"] = hotel_ref
    return raw


def _stop(raw: dict[str, Any], key: str) -> dict[str, Any]:
    return next(stop for stop in raw["stops"] if stop["key"] == key)


def _hotel(ref: str, data: dict[str, Any]) -> Finding:
    return Finding(ref=ref, tool="search_hotels", data=dict(data))


def _compose(
    raw: dict[str, Any], findings: list[Finding], previous: list[Itinerary] | None = None
) -> Itinerary:
    plan = asyncio.run(
        pipeline.compose(
            FakeProvider(drafts=[raw]), _profile(), [], previous or [], TODAY, findings=findings
        )
    )
    assert itinerary_errors(plan) == []
    return plan


def _hotel_stop(plan: Itinerary) -> Any:
    stops = [stop for stop in plan.stops if stop.kind == "lodging"]
    assert len(stops) == 1
    return stops[0]


def _lodging_item(plan: Itinerary) -> Any:
    items = [item for day in plan.days for item in day.items if item.kind == "lodging"]
    assert len(items) == 1
    return items[0]


def _usd(amount: float) -> Money:
    return Money(amount=amount, currency="USD")


# --- what compose sees: the found hotels as h refs ------------------------------------------


def test_render_hotels_lists_each_hotel_with_ref_price_and_rating() -> None:
    text = pipeline.render_hotels([_hotel("h1", PACIFIC), _hotel("h2", UNPRICED)])

    assert "Hotels found" in text
    assert "- h1 · Pacific Inn San Jose · $79/night · rating 3.6" in text
    assert "- h2 · Hotel De Anza · no price" in text


def test_render_hotels_ignores_places_and_is_empty_without_hotels() -> None:
    place = Finding(ref="p1", tool="search_places", data={"name": "The Tech Interactive"})

    assert pipeline.render_hotels([place]) == ""
    assert pipeline.render_hotels([]) == ""


def test_compose_system_lists_found_hotels() -> None:
    system = pipeline.build_system(_profile(), TODAY, findings=[_hotel("h1", PACIFIC)])

    assert "- h1 · Pacific Inn San Jose · $79/night" in system


# --- price helpers --------------------------------------------------------------------------


def test_hotel_price_from_a_priced_result() -> None:
    price = pipeline.hotel_price(PACIFIC)

    assert price.per_night == _usd(79)
    assert price.source == "serpapi_google_hotels"
    assert price.as_of == datetime(2026, 11, 9, 1, 30, tzinfo=timezone.utc)


def test_hotel_price_from_a_fallback_result_has_no_price() -> None:
    price = pipeline.hotel_price(UNPRICED)

    assert price.per_night is None
    assert price.source == "none"


def test_hotel_price_ignores_a_price_without_the_serpapi_source() -> None:
    # Only a SerpApi result counts as a tool price.
    price = pipeline.hotel_price({**UNPRICED, "price_per_night": {"amount": 50, "currency": "USD"}})

    assert price.per_night is None and price.source == "none"


def test_hotel_source_names_serpapi_and_the_time_in_utc() -> None:
    as_of = datetime(2026, 11, 9, 1, 30, tzinfo=timezone.utc)
    other_zone = as_of.astimezone(timezone(timedelta(hours=-6)))

    assert hotel_source(HotelPrice(_usd(79), "serpapi_google_hotels", as_of)) == AS_OF_SOURCE
    assert hotel_source(HotelPrice(_usd(79), "serpapi_google_hotels", other_zone)) == AS_OF_SOURCE


def test_hotel_source_of_a_fallback_hotel_is_geoapify() -> None:
    assert hotel_source(HotelPrice(None, "none")) == "Geoapify"


# --- postprocess: the tool price wins over the draft ----------------------------------------


def test_build_itinerary_tool_price_wins_over_the_draft_price() -> None:
    as_of = datetime(2026, 11, 9, 1, 30, tzinfo=timezone.utc)
    hotel = HotelPrice(per_night=_usd(79), source="serpapi_google_hotels", as_of=as_of)
    stop_places = {
        "s4": StopPlace(lat=37.3398, lng=-121.881, place_id="serpapi:x", rating=3.6,
                        source=hotel_source(hotel), hotel=hotel)
    }

    plan = build_itinerary(
        ItineraryDraft.model_validate(_raw_v1()), [], _profile(), None, stop_places
    )
    assert isinstance(plan, Itinerary), plan
    assert itinerary_errors(plan) == []
    lodging = plan.lodging[0]
    item = _lodging_item(plan)

    assert lodging.stop_tag == _hotel_stop(plan).tag
    assert lodging.price_per_night == _usd(79)  # not the draft's $120
    assert lodging.total_price == _usd(158)  # 79 × 2 nights
    assert lodging.price_source == "serpapi_google_hotels"
    assert lodging.price_as_of == as_of
    assert item.est_cost == _usd(79)
    assert item.cost_source == "tool"
    assert item.nights == 2
    assert item.source == AS_OF_SOURCE


def test_build_itinerary_without_a_hotel_keeps_the_ai_estimate() -> None:
    plan = build_itinerary(ItineraryDraft.model_validate(_raw_v1()), [], _profile(), None, {})
    assert isinstance(plan, Itinerary), plan

    assert plan.lodging[0].price_per_night == _usd(120)
    assert plan.lodging[0].price_source == "ai_estimate"
    assert plan.lodging[0].price_as_of is None
    assert _lodging_item(plan).cost_source == "ai_estimate"


# --- compose: a stop citing an h ref --------------------------------------------------------


def test_hotel_ref_gives_the_stop_the_hotels_place_and_price() -> None:
    plan = _compose(_raw_v1("h1"), [_hotel("h1", PACIFIC)])
    stop = _hotel_stop(plan)
    lodging = plan.lodging[0]
    item = _lodging_item(plan)

    assert (stop.lat, stop.lng) == (37.3398, -121.881)
    assert stop.place_id == "serpapi:mock_pacific_inn"
    assert stop.rating == 3.6
    assert lodging.price_per_night == _usd(79)
    assert lodging.price_source == "serpapi_google_hotels"
    assert lodging.price_as_of == datetime(2026, 11, 9, 1, 30, tzinfo=timezone.utc)
    assert (item.est_cost, item.cost_source, item.nights) == (_usd(79), "tool", 2)
    assert item.source == AS_OF_SOURCE


def test_total_is_per_night_times_nights_not_the_tools_total() -> None:
    odd_total = {**PACIFIC, "total_price": {"amount": 999, "currency": "USD"}}

    plan = _compose(_raw_v1("h1"), [_hotel("h1", odd_total)])

    assert plan.lodging[0].total_price == _usd(158)


def test_draft_prices_are_never_used_at_a_found_hotel() -> None:
    raw = _raw_v1("h1")
    raw["lodging"][0]["price_per_night"] = {"amount": 5, "currency": "USD"}
    for day in raw["days"]:
        for item in day["items"]:
            if item["kind"] == "lodging":
                item["est_cost"] = {"amount": 5, "currency": "USD"}

    plan = _compose(raw, [_hotel("h1", PACIFIC)])

    assert plan.lodging[0].price_per_night == _usd(79)
    assert _lodging_item(plan).est_cost == _usd(79)


def test_no_price_fallback_gives_null_prices_not_the_draft_estimate() -> None:
    plan = _compose(_raw_v1("h1"), [_hotel("h1", UNPRICED)])
    stop = _hotel_stop(plan)
    lodging = plan.lodging[0]
    item = _lodging_item(plan)

    # The draft said $120; with no tool price the plan shows "check link" (null), never $120.
    assert lodging.price_per_night is None
    assert lodging.total_price is None
    assert lodging.price_source == "none"
    assert lodging.price_as_of is None
    assert item.est_cost is None and item.cost_source is None
    assert item.source == "Geoapify"
    assert (stop.lat, stop.lng, stop.place_id) == (37.3307, -121.8936, "geoapify:mock_hotel_de_anza")


def test_serpapi_hotel_without_a_rate_gives_null_prices_and_the_serpapi_source() -> None:
    # A SerpApi property with no rate_per_night, normalized as the hotels tool does.
    prop = {
        "name": "Pacific Inn San Jose", "property_token": "mock_pacific_inn",
        "gps_coordinates": {"latitude": 37.3398, "longitude": -121.881}, "overall_rating": 3.6,
    }
    unrated = hotels.normalize_hotel(prop, AS_OF)
    assert unrated["price_source"] == "serpapi_google_hotels"
    assert unrated["price_per_night"] is None and unrated["total_price"] is None

    plan = _compose(_raw_v1("h1"), [_hotel("h1", unrated)])
    stop = _hotel_stop(plan)
    lodging = plan.lodging[0]
    item = _lodging_item(plan)

    assert lodging.price_per_night is None and lodging.total_price is None
    assert lodging.price_source == "none"
    assert item.est_cost is None and item.cost_source is None
    assert item.source == "SerpApi Google Hotels"  # no "as of", and not "Geoapify"
    assert (stop.lat, stop.lng, stop.place_id) == (37.3398, -121.881, "serpapi:mock_pacific_inn")
    # The places-search fallback hotel still reads "Geoapify".
    fallback = _compose(_raw_v1("h1"), [_hotel("h1", UNPRICED)])
    assert _lodging_item(fallback).source == "Geoapify"


def test_unknown_hotel_ref_keeps_the_draft_estimate() -> None:
    plan = _compose(_raw_v1("h9"), [_hotel("h1", PACIFIC)])

    assert plan.lodging[0].price_source == "ai_estimate"
    assert plan.lodging[0].price_as_of is None


def test_edit_that_keeps_the_hotel_keeps_its_tool_price() -> None:
    v1 = _compose(_raw_v1("h1"), [_hotel("h1", PACIFIC)])

    # An edit copies stops by letter with no refs and gets no new hotel findings.
    v2 = _compose(pipeline.as_draft(v1).model_dump(mode="json"), [], previous=[v1])

    assert _hotel_stop(v2).tag == _hotel_stop(v1).tag
    assert v2.lodging[0].price_per_night == _usd(79)
    assert v2.lodging[0].price_source == "serpapi_google_hotels"
    assert v2.lodging[0].price_as_of == v1.lodging[0].price_as_of
    assert _lodging_item(v2).source == AS_OF_SOURCE


# --- the fake planner's hotel call reaches compose as an h ref ------------------------------


class RecordingFake(FakeProvider):
    """The fake LLM, recording the compose system text."""

    def __init__(self) -> None:
        super().__init__()
        self.compose_systems: list[str] = []

    async def complete_json(self, system: str, messages: list[Message], schema: Any) -> Any:
        if schema is ItineraryDraft:
            self.compose_systems.append(system)
        return await super().complete_json(system, messages, schema)


def test_fake_planner_hotel_search_reaches_compose_and_prices_the_plan(db: Session) -> None:
    session_id = repo.create_session(db).id
    llm = RecordingFake()

    async def run() -> None:
        async for _ in pipeline.run_generation(
            db, session_id, llm, _profile(), [], on_saved=lambda _: None, today=TODAY
        ):
            pass

    asyncio.run(run())
    plan = repo.get_latest_itinerary(db, session_id)
    assert plan is not None
    assert itinerary_errors(plan) == []

    assert len(llm.compose_systems) == 1
    assert "- h1 · Pacific Inn San Jose · $79/night" in llm.compose_systems[0]
    stop = _hotel_stop(plan)
    # Name, coordinates and price all belong to the same mock hotel (Pacific Inn San Jose).
    mock_hotel = next(
        h for h in load_mock("hotels_search")["properties"] if h.get("name") == stop.name
    )
    assert stop.name == "Pacific Inn San Jose" == PACIFIC["name"]
    assert mock_hotel["rate_per_night"]["extracted_lowest"] == 79
    assert stop.place_id == "serpapi:mock_pacific_inn"
    assert (stop.lat, stop.lng) == (37.3398, -121.881)
    lodging = plan.lodging[0]
    assert lodging.stop_tag == stop.tag
    assert lodging.price_per_night == _usd(79)  # the fake draft says $120
    assert lodging.total_price == _usd(158)
    assert lodging.price_source == "serpapi_google_hotels"
    assert lodging.price_as_of is not None
    item = _lodging_item(plan)
    assert (item.est_cost, item.cost_source, item.nights) == (_usd(79), "tool", 2)
    assert item.source.startswith("SerpApi Google Hotels · as of ") and item.source.endswith(" UTC")


def test_fake_lodging_stop_matching_no_found_hotel_cites_no_h_ref() -> None:
    # A priced hotel with another name: the fake's lodging stop (Pacific Inn San Jose) must not
    # borrow its price or coordinates; it keeps the draft's AI estimate.
    other = {**PACIFIC, "id": "serpapi:mock_other", "name": "Hotel De Anza",
             "lat": 37.3307, "lng": -121.8936, "price_per_night": {"amount": 99, "currency": "USD"}}
    system = pipeline.render_hotels([_hotel("h1", other)])

    draft = cite_found_places(load_fake_data("draft_sanjose_v1"), system)
    assert _stop(draft, "s4")["place_ref"] is None

    plan = asyncio.run(
        pipeline.compose(FakeProvider(), _profile(), [], [], TODAY, findings=[_hotel("h1", other)])
    )
    assert itinerary_errors(plan) == []
    stop = _hotel_stop(plan)
    assert stop.name == "Pacific Inn San Jose"
    assert stop.place_id is None and (stop.lat, stop.lng) == (None, None)
    assert plan.lodging[0].price_per_night == _usd(120)
    assert plan.lodging[0].price_source == "ai_estimate"
    assert plan.lodging[0].price_as_of is None
    assert _lodging_item(plan).cost_source == "ai_estimate"


# --- one hotel search per city per plan -----------------------------------------------------


class ScriptedPlanner(FakeProvider):
    """`tool_turn` gives the scripted calls, one list per round, and records the rounds."""

    def __init__(self, script: list[list[ToolCall]]) -> None:
        super().__init__()
        self.script = list(script)
        self.seen_rounds: list[list[ToolRound]] = []

    async def tool_turn(
        self, system: str, messages: list[Message], rounds: list[ToolRound], tools: list[ToolSpec]
    ) -> list[ToolCall]:
        self.seen_rounds.append(list(rounds))
        index = len(self.seen_rounds) - 1
        return list(self.script[index]) if index < len(self.script) else []


def _hotel_call(n: int, city: str) -> ToolCall:
    return ToolCall(
        id=f"call_h{n}", name="search_hotels",
        arguments={"city": city, "check_in": "2027-03-05", "check_out": "2027-03-07"},
    )


def _count_hotel_searches(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    cities: list[str] = []

    def fake_search(city: str, check_in: str, check_out: str, *args: Any, **kwargs: Any) -> ToolResult:
        cities.append(city)
        return tool_ok([dict(PACIFIC)])

    monkeypatch.setattr(registry.hotels, "search", fake_search)
    return cities


def _run_planner(llm: FakeProvider) -> list[Finding]:
    async def collect() -> list[Finding]:
        findings: list[Finding] = []
        async for item in run_planner(llm, _profile(), REQUEST, today=TODAY):
            if isinstance(item, list):
                findings = item
        return findings

    return asyncio.run(asyncio.wait_for(collect(), timeout=30))


def test_second_hotel_search_for_a_city_in_one_plan_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    searched = _count_hotel_searches(monkeypatch)
    llm = ScriptedPlanner([
        [_hotel_call(1, "San Jose, CA"), _hotel_call(2, "san jose")],  # same city, same round
        [_hotel_call(3, "San Jose, CA")],  # and again in a later round
    ])

    findings = _run_planner(llm)

    assert len(searched) == 1
    assert [f.ref for f in findings] == ["h1"]
    round_one = llm.seen_rounds[1][0].results
    round_two = llm.seen_rounds[2][1].results
    assert sum(registry.LIMIT_REPLY in reply for reply in round_one) == 1
    assert registry.LIMIT_REPLY in round_two[0]


def test_hotel_searches_for_different_cities_both_run(monkeypatch: pytest.MonkeyPatch) -> None:
    searched = _count_hotel_searches(monkeypatch)
    llm = ScriptedPlanner([[_hotel_call(1, "San Jose, CA"), _hotel_call(2, "San Francisco, CA")]])

    findings = _run_planner(llm)

    assert sorted(searched) == ["San Francisco, CA", "San Jose, CA"]
    assert [f.ref for f in findings] == ["h1", "h2"]


def test_each_plan_gets_its_own_hotel_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    searched = _count_hotel_searches(monkeypatch)

    first = _run_planner(ScriptedPlanner([[_hotel_call(1, "San Jose, CA")]]))
    second = _run_planner(ScriptedPlanner([[_hotel_call(1, "San Jose, CA")]]))

    assert len(searched) == 2
    assert [f.ref for f in first] == [f.ref for f in second] == ["h1"]


def test_planner_prompt_asks_for_one_hotel_search_per_city() -> None:
    system = planner.build_system(_profile(), TODAY)

    assert "search_hotels" in system
    assert "once per city" in system
