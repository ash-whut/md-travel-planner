"""Step 52 batch (step 49 fix): an edit keeps the flight fare.

Specified by D35: an edit with no fresh `search_flights` result keeps the previous version's
tool fare on its flight items (`est_cost`, `cost_source`, source "SerpApi Google Flights · as of
…"), the flight booking estimate and the flight leg's tool duration, like D30 for hotels, as
long as the dates and the flight route (departure and arrival airport stops) are unchanged. A
changed route or dates drops it ("check link"); a fresh fare on the edit wins.

All offline: mock tool mode, the fake LLM with scripted drafts, a temp DB (conftest).
"""

import asyncio
import copy
from datetime import date, timedelta
from typing import Any

import pytest

from app.agent import pipeline
from app.agent.planner import Finding
from app.core.config import Settings
from app.llm.fake_provider import FakeProvider, load_fake_data
from app.schemas.itinerary import Itinerary, Money, itinerary_errors
from app.schemas.profile import TripProfile
from app.tools import flights, hotels, places

TODAY = date(2027, 2, 1)
CHANGE = "replace [F] with something vegan"


@pytest.fixture(autouse=True)
def offline_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    # backend/.env may hold real keys: force mock mode in the tools.
    settings = Settings(_env_file=None, llm_provider="fake", tool_provider_mode="mock")
    for module in (places, hotels, flights):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
        monkeypatch.setattr(module, "is_mock", lambda: True)
    monkeypatch.setattr(places, "NOMINATIM_INTERVAL_SECONDS", 0.0)


def _profile() -> TripProfile:
    return TripProfile(
        budget_level="budget", cities=["San Jose, CA"], travelers=1,
        start_date=date(2027, 3, 5), end_date=date(2027, 3, 7), origin="College Station, TX",
    )


def _flight(price: float, duration: int) -> Finding:
    result = flights.search("IAH", "SJC", "2027-03-05", "2027-03-07")
    assert result.ok, result.error
    data = {**result.data[0], "price": {"amount": price, "currency": "USD"},
            "duration_min": duration}
    return Finding(ref="f1", tool="search_flights", data=data)


def _compose(raw: dict[str, Any], findings: list[Finding],
             previous: list[Itinerary] | None = None) -> Itinerary:
    plan = asyncio.run(
        pipeline.compose(
            FakeProvider(drafts=[raw]), _profile(), [], previous or [], TODAY,
            change_request=CHANGE if previous else None, findings=findings,
        )
    )
    assert isinstance(plan, Itinerary), plan
    assert itinerary_errors(plan) == []
    return plan


def _v1() -> Itinerary:
    return _compose(copy.deepcopy(load_fake_data("draft_sanjose_v1")), [_flight(189, 245)])


def _v2_draft() -> dict[str, Any]:
    return copy.deepcopy(load_fake_data("draft_sanjose_v2"))


def _departure(plan: Itinerary) -> Any:
    return next(item for day in plan.days for item in day.items if item.kind == "flight")


def _leg_after_departure(plan: Itinerary) -> Any:
    for day in plan.days:
        for item, after in zip(day.items, day.items[1:]):
            if item.kind == "flight":
                return after.transit_from_previous
    return None


def _flight_booking(plan: Itinerary) -> Any:
    return next(booking for booking in plan.bookings if booking.kind == "flight")


def test_v1_has_the_tool_fare_and_duration() -> None:
    v1 = _v1()

    assert _departure(v1).est_cost == Money(amount=189, currency="USD")
    assert _flight_booking(v1).estimate == Money(amount=189, currency="USD")
    leg = _leg_after_departure(v1)
    assert leg is not None and leg.mode == "flight" and leg.duration_min == 245


def test_edit_without_a_flight_search_keeps_the_fare() -> None:
    v1 = _v1()

    v2 = _compose(_v2_draft(), [], previous=[v1])

    before, after = _departure(v1), _departure(v2)
    assert after.stop_tag == before.stop_tag
    assert (after.est_cost, after.cost_source, after.source) == (
        before.est_cost, before.cost_source, before.source
    )
    assert after.source.startswith("SerpApi Google Flights · as of ")
    assert _flight_booking(v2).estimate == _flight_booking(v1).estimate
    assert _flight_booking(v2).price_as_of == _flight_booking(v1).price_as_of
    assert _leg_after_departure(v2).duration_min == 245
    # Every priced flight item (the return leg too) keeps its fare.
    v1_fares = [(i.stop_tag, i.est_cost) for d in v1.days for i in d.items if i.kind == "flight"]
    v2_fares = [(i.stop_tag, i.est_cost) for d in v2.days for i in d.items if i.kind == "flight"]
    assert v2_fares == v1_fares


def test_edit_with_changed_route_drops_the_fare() -> None:
    v1 = _v1()
    raw = _v2_draft()
    arrival = next(stop for stop in raw["stops"] if stop["name"] == "San Jose Airport")
    arrival["name"], arrival["address"] = "Oakland Airport", "1 Airport Dr, Oakland, CA"

    v2 = _compose(raw, [], previous=[v1])

    item = _departure(v2)
    assert (item.est_cost, item.cost_source, item.source) == (None, None, "AI suggestion")
    assert _flight_booking(v2).estimate is None


def _shift_dates(raw: dict[str, Any], days: int) -> dict[str, Any]:
    def shift(value: str) -> str:
        return (date.fromisoformat(value) + timedelta(days=days)).isoformat()

    raw["start_date"], raw["end_date"] = shift(raw["start_date"]), shift(raw["end_date"])
    for day in raw["days"]:
        day["date"] = shift(day["date"])
    for stay in raw["lodging"]:
        stay["check_in"], stay["check_out"] = shift(stay["check_in"]), shift(stay["check_out"])
    return raw


def test_edit_with_changed_dates_drops_the_fare() -> None:
    v1 = _v1()

    v2 = _compose(_shift_dates(_v2_draft(), 7), [], previous=[v1])

    assert _departure(v2).est_cost is None
    assert _flight_booking(v2).estimate is None
    assert _leg_after_departure(v2).duration_min is None


def test_fresh_fare_on_the_edit_replaces_the_old_one() -> None:
    v1 = _v1()

    v2 = _compose(_v2_draft(), [_flight(159, 230)], previous=[v1])

    assert _departure(v2).est_cost == Money(amount=159, currency="USD")
    assert _flight_booking(v2).estimate == Money(amount=159, currency="USD")
    assert _leg_after_departure(v2).duration_min == 230
