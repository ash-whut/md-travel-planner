"""Step 52: lodging edits ("swap the hotel for an Airbnb").

Specified by plan step 52, contracts §2.2/§2.3/§3 and D29/D30/D34: a change about the stay
makes the planner run one `search_hotels` for the city (from the cache when it's warm, so no
SerpApi call); compose cites an `h` ref, and the cited hotel or rental replaces the lodging
entry (price, `type`, links, booking title). Other edits run no hotel search and keep the
lodging as it was (D30), also after a rental v1.

Tags follow §3 as written: the new hotel or rental is a different place (another place_id and
name), so its stop gets the next new letter and the old hotel's letter is retired, like
"replace [F]" → [L]. The lodging entry, the lodging item and the booking all follow the new
stop's letter.

All offline: mock tool mode (or live hotels over a patched `get_json`), the fake LLM, a temp
DB (conftest).
"""

import asyncio
import copy
import json
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.agent import pipeline
from app.agent.turn import TurnLlms
from app.api.chat import get_llm
from app.core.config import Settings
from app.db import repo
from app.llm.base import ToolSpec
from app.llm.fake_provider import (
    FakeProvider,
    cheaper_hotel,
    is_stay_change,
    load_fake_data,
    scripted_turn_analysis,
)
from app.schemas.itinerary import Itinerary, Money, itinerary_errors
from app.schemas.profile import TripProfile
from app.tools import hotels, places
from app.tools.common import ToolResult, load_mock

TODAY = date(2027, 2, 1)
START, END = date(2027, 3, 5), date(2027, 3, 7)
SWAP_MESSAGE = "swap the hotel for an Airbnb"
CHEAPER_MESSAGE = "find a cheaper hotel"
VEGAN_MESSAGE = "replace [F] with something vegan"
TRIP_MESSAGE = "San Jose, first weekend of March, just me. I like tech, food and gardens."
# The mock recordings (tools/mocks/hotels_search.json, rentals_search.json): after the rating
# filter the hotels are h1 Pacific Inn ($79), h2 Hotel De Anza ($119), h3 Westin ($164), then
# the rentals, the first being the Oversize Loft ($74).
DEMO_HOTEL = "Pacific Inn San Jose"
WESTIN = "Westin San Jose"
FIRST_RENTAL_PREFIX = "Oversize Loft"


@pytest.fixture(autouse=True)
def offline_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    # backend/.env may hold real GEOAPIFY / SERPAPI keys: force mock mode in both tools.
    settings = Settings(_env_file=None, llm_provider="fake", tool_provider_mode="mock")
    for module in (places, hotels):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
        monkeypatch.setattr(module, "is_mock", lambda: True)
    monkeypatch.setattr(places, "NOMINATIM_INTERVAL_SECONDS", 0.0)


# --- helpers --------------------------------------------------------------------------------


def _profile() -> TripProfile:
    return TripProfile(
        budget_level="budget", cities=["San Jose, CA"], travelers=1,
        start_date=START, end_date=END, interests=["food"], origin="College Station, TX",
    )


def _run(db: Session, session_id: str, llm: FakeProvider, message: str,
         change_request: str | None = None) -> Itinerary:
    """One generation (or an edit with `change_request`) through the pipeline; the saved plan."""
    messages = [{"role": "user", "content": message}]

    async def run() -> None:
        async for _ in pipeline.run_generation(
            db, session_id, llm, _profile(), messages, on_saved=lambda _: None, today=TODAY,
            change_request=change_request,
        ):
            pass

    asyncio.run(run())
    plan = repo.get_latest_itinerary(db, session_id)
    assert plan is not None
    assert itinerary_errors(plan) == []
    return plan


def _v1_and_edit(db: Session, change: str, v1_message: str = "A weekend in San Jose please",
                 llm: FakeProvider | None = None) -> tuple[Itinerary, Itinerary]:
    llm = llm or FakeProvider()
    session_id = repo.create_session(db).id
    v1 = _run(db, session_id, llm, v1_message)
    v2 = _run(db, session_id, llm, change, change_request=change)
    assert v2.version == 2
    return v1, v2


def _count_hotel_searches(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    """Record every `search_hotels` tool call (the registry calls `hotels.search`)."""
    calls: list[tuple[Any, ...]] = []
    original = hotels.search

    def counting(*args: Any, **kwargs: Any) -> ToolResult:
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(hotels, "search", counting)
    return calls


def _lodging_stop(plan: Itinerary) -> Any:
    return next(stop for stop in plan.stops if stop.kind == "lodging")


def _lodging_item(plan: Itinerary) -> Any:
    return next(item for day in plan.days for item in day.items if item.kind == "lodging")


def _lodging_booking(plan: Itinerary) -> Any:
    return next(booking for booking in plan.bookings if booking.kind == "lodging")


def _labels(plan: Itinerary) -> list[str]:
    return [link.label for link in plan.lodging[0].links]


def _usd(amount: float) -> Money:
    return Money(amount=amount, currency="USD")


# --- "swap the hotel for an Airbnb" ---------------------------------------------------------


def test_swap_hotel_for_airbnb_gives_a_rental(db: Session) -> None:
    v1, v2 = _v1_and_edit(db, SWAP_MESSAGE)
    assert v1.lodging[0].type == "hotel" and _lodging_stop(v1).name == DEMO_HOTEL

    stop = _lodging_stop(v2)
    lodging = v2.lodging[0]
    assert stop.name.startswith(FIRST_RENTAL_PREFIX)
    assert lodging.type == "vacation_rental"
    assert lodging.price_source == "serpapi_google_hotels"
    assert lodging.price_per_night == _usd(74)  # the rental's tool price, not the hotel's $79
    assert lodging.total_price == _usd(148)  # D30: per night × nights
    assert lodging.price_as_of is not None
    assert _labels(v2) == ["Google Hotels", "Airbnb"]
    item = _lodging_item(v2)
    assert (item.est_cost, item.cost_source) == (_usd(74), "tool")
    assert item.source.startswith("SerpApi Google Hotels (vacation rental) · as of ")
    booking = _lodging_booking(v2)
    assert booking.title == "Rental Booking"
    assert booking.estimate == _usd(148)
    assert stop.name in booking.details


def test_swap_lodging_tag_follows_contract_section_3(db: Session) -> None:
    v1, v2 = _v1_and_edit(db, SWAP_MESSAGE)
    old_tag = _lodging_stop(v1).tag
    new_tag = _lodging_stop(v2).tag

    # A different place gets a new letter; the hotel's letter is retired, never reused.
    assert new_tag != old_tag
    assert old_tag not in {stop.tag for stop in v2.stops}
    assert v2.lodging[0].stop_tag == new_tag
    assert _lodging_item(v2).stop_tag == new_tag
    assert _lodging_booking(v2).id == f"bk-hotel-{new_tag}"
    assert _lodging_item(v2).booking_id == f"bk-hotel-{new_tag}"
    assert _lodging_item(v2).updated_in_version == 2
    # Stops the edit didn't touch keep their letters.
    v2_tags = {stop.name: stop.tag for stop in v2.stops}
    for stop in v1.stops:
        if stop.kind != "lodging" and stop.name in v2_tags:
            assert v2_tags[stop.name] == stop.tag, stop.name


def test_swap_runs_exactly_one_hotel_search(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _count_hotel_searches(monkeypatch)
    session_id = repo.create_session(db).id
    llm = FakeProvider()
    _run(db, session_id, llm, "A weekend in San Jose please")
    calls.clear()

    _run(db, session_id, llm, SWAP_MESSAGE, change_request=SWAP_MESSAGE)

    assert calls == [("San Jose, CA", "2027-03-05", "2027-03-07")]


def test_swap_with_a_warm_cache_makes_no_serpapi_call(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Live hotels over a patched get_json: v1 makes the hotels + rentals calls and caches them;
    # the edit's hotel search is answered from the cache.
    live = Settings(_env_file=None, tool_provider_mode="live", serpapi_key="test-key")
    monkeypatch.setattr(hotels, "get_settings", lambda: live)
    monkeypatch.setattr(hotels, "is_mock", lambda: False)
    serpapi_calls: list[dict[str, Any]] = []

    def fake_get_json(client: Any, url: str, params: dict[str, Any]) -> Any:
        serpapi_calls.append(params)
        mock = "rentals_search" if params.get("vacation_rentals") == "true" else "hotels_search"
        return copy.deepcopy(load_mock(mock))

    monkeypatch.setattr(hotels, "get_json", fake_get_json)
    searches = _count_hotel_searches(monkeypatch)
    session_id = repo.create_session(db).id
    llm = FakeProvider()
    _run(db, session_id, llm, "A weekend in San Jose please")
    assert len(serpapi_calls) == 2
    searches.clear()

    v2 = _run(db, session_id, llm, SWAP_MESSAGE, change_request=SWAP_MESSAGE)

    assert len(searches) == 1  # the tool ran once…
    assert len(serpapi_calls) == 2  # …from the cache: no new SerpApi search
    assert v2.lodging[0].type == "vacation_rental"


def _api_plans(text: str) -> list[Itinerary]:
    """The `itinerary` events of an SSE response."""
    return [
        Itinerary.model_validate(json.loads(line[len("data:"):]))
        for block in text.replace("\r\n", "\n").split("\n\n")
        if "event: itinerary" in block
        for line in block.split("\n")
        if line.startswith("data:")
    ]


def _api_v1(client: TestClient) -> tuple[str, Itinerary]:
    """A session with the fake demo v1 made through the chat API."""
    provider = FakeProvider()
    client.app.dependency_overrides[get_llm] = lambda: TurnLlms(provider, provider)  # type: ignore[attr-defined]
    session_id = client.post("/api/sessions").json()["id"]
    client.post(f"/api/sessions/{session_id}/messages", json={"content": TRIP_MESSAGE})
    response = client.post(f"/api/sessions/{session_id}/generate", json={})
    assert response.status_code == 200
    return session_id, _api_plans(response.text)[-1]


def test_swap_through_the_chat_api_shows_a_rental(client: TestClient) -> None:
    session_id, _ = _api_v1(client)

    response = client.post(f"/api/sessions/{session_id}/messages", json={"content": SWAP_MESSAGE})

    assert response.status_code == 200
    assert "Finding hotels in San Jose" in response.text
    v2 = _api_plans(response.text)[-1]
    assert v2.version == 2
    assert v2.lodging[0].type == "vacation_rental"


# --- "cheaper hotel" ------------------------------------------------------------------------


def test_cheaper_hotel_gives_a_cheaper_hotel(db: Session) -> None:
    # v1 stays at the Westin (h3, $164); the demo default is already the cheapest well-rated one.
    raw = copy.deepcopy(load_fake_data("draft_sanjose_v1"))
    lodging_stop = next(stop for stop in raw["stops"] if stop["kind"] == "lodging")
    lodging_stop["name"], lodging_stop["place_ref"] = WESTIN, "h3"
    v1, v2 = _v1_and_edit(db, CHEAPER_MESSAGE, llm=FakeProvider(drafts=[raw]))
    assert _lodging_stop(v1).name == WESTIN
    assert v1.lodging[0].price_per_night == _usd(164)

    old = v1.lodging[0].price_per_night
    new = v2.lodging[0].price_per_night
    assert old is not None and new is not None and new.amount < old.amount
    assert _lodging_stop(v2).name == DEMO_HOTEL
    assert v2.lodging[0].type == "hotel"
    assert v2.lodging[0].total_price == _usd(158)
    assert _labels(v2)[:2] == ["Google Hotels", "Booking.com"]
    assert _lodging_booking(v2).title == "Hotel Booking"


def test_cheaper_hotel_on_the_demo_is_an_edit_that_keeps_the_cheapest_hotel(
    client: TestClient,
) -> None:
    # The demo v1 already stays at the cheapest well-rated hotel ($79): nothing is cheaper.
    session_id, v1 = _api_v1(client)
    assert _lodging_stop(v1).name == DEMO_HOTEL

    response = client.post(
        f"/api/sessions/{session_id}/messages", json={"content": CHEAPER_MESSAGE}
    )

    assert response.status_code == 200
    assert "Finding hotels in San Jose" in response.text  # handled as an edit about the stay
    plans = _api_plans(response.text)
    assert plans and plans[-1].version == 2
    v2 = plans[-1]
    assert _lodging_stop(v2).name == DEMO_HOTEL
    assert _lodging_stop(v2).tag == _lodging_stop(v1).tag
    assert v2.lodging[0].price_per_night == v1.lodging[0].price_per_night == _usd(79)
    assert v2.lodging[0].type == "hotel"


def test_cheaper_hotel_needs_a_known_current_price() -> None:
    system = "- h1 · Pacific Inn San Jose · $79/night · rating 3.6"

    assert cheaper_hotel(system, WESTIN, None) is None
    assert cheaper_hotel(system, WESTIN, 79) is None  # not strictly cheaper
    assert cheaper_hotel(system, WESTIN, 80) == ("h1", DEMO_HOTEL)


@pytest.mark.parametrize(
    "message, action",
    [
        ("find a cheaper hotel", "edit"), ("a cheaper place to stay", "edit"),
        ("Is there a cheaper hotel?", "edit"), (SWAP_MESSAGE, "edit"),
        ("cheaper food please", "chat"), ("we like nice hotels", "chat"),
        ("where should we stay?", "chat"),
    ],
)
def test_fake_understand_classifies_cheaper_stay_requests_as_edits(
    message: str, action: str
) -> None:
    assert scripted_turn_analysis(message)["action"] == action


# --- other edits leave the lodging alone ----------------------------------------------------


@pytest.mark.parametrize(
    "v1_message, kind",
    [("A weekend in San Jose please", "hotel"), ("We'd like an Airbnb near downtown", "vacation_rental")],
    ids=["hotel-v1", "rental-v1"],
)
def test_vegan_replace_keeps_the_lodging_and_runs_no_hotel_search(
    db: Session, monkeypatch: pytest.MonkeyPatch, v1_message: str, kind: str
) -> None:
    calls = _count_hotel_searches(monkeypatch)
    session_id = repo.create_session(db).id
    llm = FakeProvider()
    v1 = _run(db, session_id, llm, v1_message)
    assert v1.lodging[0].type == kind
    calls.clear()

    v2 = _run(db, session_id, llm, VEGAN_MESSAGE, change_request=VEGAN_MESSAGE)

    assert calls == []
    assert _lodging_stop(v2).name == _lodging_stop(v1).name  # no rename to the demo hotel
    assert _lodging_stop(v2).tag == _lodging_stop(v1).tag
    assert v2.lodging == v1.lodging  # same type, tool price (D30), as-of and links
    assert _lodging_booking(v2).title == _lodging_booking(v1).title
    assert _lodging_item(v2).updated_in_version == _lodging_item(v1).updated_in_version


# --- the fake planner -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "change, about_stay",
    [
        (SWAP_MESSAGE, True), (CHEAPER_MESSAGE, True), ("a nicer place to stay", True),
        ("book an apartment instead", True), ("we want a vacation rental", True),
        (VEGAN_MESSAGE, False), ("move [E] to day 2", False), ("we'll get a car rental", False),
    ],
)
def test_is_stay_change(change: str, about_stay: bool) -> None:
    assert is_stay_change(change) is about_stay


def _planner_system(change: str, profile: TripProfile) -> str:
    return (
        f"Trip profile (JSON): {profile.model_dump_json()}\n\n"
        f"## The traveler's change\nChange request: {change}\n"
    )


TOOLS = [
    ToolSpec(name=name, description="", parameters={})
    for name in ("search_places", "search_hotels", "search_flights")
]


def test_fake_planner_stay_edit_asks_only_for_one_hotel_search() -> None:
    calls = asyncio.run(
        FakeProvider().tool_turn(_planner_system(SWAP_MESSAGE, _profile()), [], [], TOOLS)
    )

    assert [(call.name, call.arguments) for call in calls] == [
        ("search_hotels", {"city": "San Jose, CA", "check_in": "2027-03-05",
                           "check_out": "2027-03-07"}),
    ]


def test_fake_planner_stay_edit_without_dates_asks_for_nothing() -> None:
    profile = _profile().model_copy(update={"start_date": None, "end_date": None})

    calls = asyncio.run(
        FakeProvider().tool_turn(_planner_system(SWAP_MESSAGE, profile), [], [], TOOLS)
    )

    assert calls == []


def test_fake_planner_vegan_edit_still_searches_places_only() -> None:
    calls = asyncio.run(
        FakeProvider().tool_turn(_planner_system(VEGAN_MESSAGE, _profile()), [], [], TOOLS)
    )

    assert [call.name for call in calls] == ["search_places"]
