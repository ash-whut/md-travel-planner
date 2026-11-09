"""Step 35: travel estimates between stops.

Specified by plan step 35, contracts §2.2 (`transit_from_previous`: null for the first item;
mode walk|transit|drive|rideshare|flight; set by code) and D28: postprocess fills each item's
leg from the haversine distance to the previous item's stop and a speed per mode (walk 3 mph,
transit 12 mph, drive/rideshare 25 mph), with `estimated: true`, when both stops have
coordinates. Legs up to 1 mi are walked; longer legs use the profile's transport (car → drive,
transit → transit, rideshare/mixed → rideshare, none → rideshare). The leg after a flight item
is the flight (distance known, duration null). The leg is null for a day's first item, when
either item has no stop or no coordinates, and when both items are at the same stop.

All offline: mock tool mode, the fake LLM, a temp DB (conftest).
"""

import copy
import json
import math
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agent.postprocess import (
    StopPlace,
    build_itinerary,
    estimate_leg,
    haversine_mi,
    travel_mode,
)
from app.agent.turn import TurnLlms
from app.api.chat import get_llm
from app.core.config import Settings
from app.llm.fake_provider import FakeProvider, load_fake_data
from app.schemas.itinerary import Itinerary, ItineraryDraft, Stop, itinerary_errors
from app.schemas.profile import TripProfile
from app.tools import places

ONE_DEGREE_AT_EQUATOR_MI = 2 * math.pi * 3958.8 / 360  # ≈ 69.09 mi
TRIP_MESSAGE = "San Jose, first weekend of March, just me. I like tech, food and gardens."


@pytest.fixture(autouse=True)
def offline_places(monkeypatch: pytest.MonkeyPatch) -> None:
    # backend/.env may hold a real GEOAPIFY_KEY: force mock mode with no key in the places tool.
    monkeypatch.setattr(
        places, "get_settings",
        lambda: Settings(_env_file=None, llm_provider="fake", tool_provider_mode="mock"),
    )
    monkeypatch.setattr(places, "is_mock", lambda: True)


# --- helpers --------------------------------------------------------------------------------


def _stop(tag: str, lat: float | None, lng: float | None) -> Stop:
    return Stop(tag=tag, name=f"Stop {tag}", kind="sight", lat=lat, lng=lng)


def _profile(**updates: Any) -> TripProfile:
    fields: dict[str, Any] = dict(
        budget_level="budget", cities=["San Jose, CA"], travelers=1,
        start_date=date(2027, 3, 5), end_date=date(2027, 3, 7), origin="College Station, TX",
    )
    fields.update(updates)
    return TripProfile(**fields)


def _at(lat: float, lng: float) -> StopPlace:
    return StopPlace(lat=lat, lng=lng, address="somewhere", place_id=f"p:{lat},{lng}")


# Every stop of draft_sanjose_v1 on the equator, so the distances are exact multiples of
# ONE_DEGREE_AT_EQUATOR_MI. Day 1 is s1 → s2 (flight) → s3 → s4 → s5; day 2 is s6 → s7 → s8 → s9;
# day 3 is s10 → s11 → s3 (flight).
EQUATOR_PLACES: dict[str, StopPlace] = {
    "s1": _at(0, 0),       # home
    "s2": _at(0, 1),       # IAH: 1° from home
    "s3": _at(0, 2),       # SJC: 1° from IAH (the flight)
    "s4": _at(0, 2.01),    # hotel: 0.01° (≈ 0.69 mi) from SJC
    "s5": _at(0, 2.03),    # 0.02° (≈ 1.38 mi) from the hotel
    "s6": _at(0, 2.5),
    "s7": _at(0, 2.51),
    "s8": _at(0, 2.6),
    "s9": _at(0, 2.61),
    "s10": _at(0, 3),
    "s11": _at(0, 3.01),
}


def _build(
    raw: dict[str, Any] | None = None,
    stop_places: dict[str, StopPlace] | None = None,
    profile: TripProfile | None = None,
) -> Itinerary:
    draft = ItineraryDraft.model_validate(raw or load_fake_data("draft_sanjose_v1"))
    plan = build_itinerary(
        draft, [], profile or _profile(), None,
        EQUATOR_PLACES if stop_places is None else stop_places,
    )
    assert isinstance(plan, Itinerary), plan
    assert itinerary_errors(plan) == []
    return plan


def _legs(plan: Itinerary, day_number: int) -> list[Any]:
    day = next(day for day in plan.days if day.day_number == day_number)
    return [item.transit_from_previous for item in day.items]


def _minutes(distance_mi: float, mph: float) -> int:
    return max(1, round(distance_mi / mph * 60))


# --- distance -------------------------------------------------------------------------------


def test_haversine_one_degree_of_longitude_at_the_equator() -> None:
    assert haversine_mi(0, 0, 0, 1) == pytest.approx(69.09, abs=0.01)


def test_haversine_one_degree_of_latitude_is_the_same_anywhere() -> None:
    assert haversine_mi(37, -122, 38, -122) == pytest.approx(ONE_DEGREE_AT_EQUATOR_MI, rel=1e-6)


def test_haversine_is_zero_for_the_same_point_and_symmetric() -> None:
    assert haversine_mi(37.33, -121.89, 37.33, -121.89) == 0
    there = haversine_mi(37.3316, -121.8901, 37.3184, -121.9511)
    back = haversine_mi(37.3184, -121.9511, 37.3316, -121.8901)
    assert there == pytest.approx(back)


def test_haversine_known_city_distance() -> None:
    # San Jose (SJC) to Los Angeles (LAX) is about 308 mi great-circle.
    assert haversine_mi(37.3639, -121.9289, 33.9416, -118.4085) == pytest.approx(308, abs=3)


# --- mode -----------------------------------------------------------------------------------


@pytest.mark.parametrize("transport", ["car", "transit", "rideshare", "mixed", None])
def test_legs_up_to_one_mile_are_walked_whatever_the_transport(transport: Any) -> None:
    assert travel_mode(0.2, transport) == "walk"
    assert travel_mode(1.0, transport) == "walk"


@pytest.mark.parametrize(
    ("transport", "mode"),
    [("car", "drive"), ("transit", "transit"), ("rideshare", "rideshare"),
     ("mixed", "rideshare"), (None, "rideshare")],
)
def test_longer_legs_use_the_profile_transport(transport: Any, mode: str) -> None:
    assert travel_mode(1.01, transport) == mode
    assert travel_mode(40, transport) == mode


# --- one leg --------------------------------------------------------------------------------


def test_leg_for_a_known_distance_by_rideshare() -> None:
    leg = estimate_leg(_stop("A", 0, 0), _stop("B", 0, 1), None)

    assert leg is not None
    assert leg.mode == "rideshare"
    assert leg.distance_mi == 69.1
    assert leg.duration_min == _minutes(ONE_DEGREE_AT_EQUATOR_MI, 25) == 166
    assert leg.estimated is True


@pytest.mark.parametrize(("transport", "mode", "mph"), [("car", "drive", 25), ("transit", "transit", 12)])
def test_leg_duration_uses_the_speed_of_its_mode(transport: Any, mode: str, mph: float) -> None:
    leg = estimate_leg(_stop("A", 0, 0), _stop("B", 0, 0.5), transport)

    distance = ONE_DEGREE_AT_EQUATOR_MI / 2
    assert leg is not None
    assert (leg.mode, leg.distance_mi) == (mode, round(distance, 1))
    assert leg.duration_min == _minutes(distance, mph)


def test_short_leg_is_walked_at_three_mph() -> None:
    leg = estimate_leg(_stop("A", 0, 0), _stop("B", 0, 0.01), "car")

    distance = ONE_DEGREE_AT_EQUATOR_MI / 100  # ≈ 0.69 mi
    assert leg is not None
    assert (leg.mode, leg.distance_mi, leg.duration_min) == ("walk", 0.7, _minutes(distance, 3))
    assert leg.duration_min == 14
    assert leg.estimated is True


def test_very_short_leg_takes_at_least_one_minute() -> None:
    leg = estimate_leg(_stop("A", 0, 0), _stop("B", 0, 0.0001), None)

    assert leg is not None
    assert leg.mode == "walk"
    assert leg.duration_min == 1


@pytest.mark.parametrize(
    ("origin", "destination"),
    [((None, 0), (0, 1)), ((0, None), (0, 1)), ((0, 0), (None, 1)), ((0, 0), (0, None)),
     ((None, None), (None, None))],
)
def test_missing_coordinate_gives_no_leg(
    origin: tuple[Any, Any], destination: tuple[Any, Any]
) -> None:
    assert estimate_leg(_stop("A", *origin), _stop("B", *destination), "car") is None


def test_leg_after_a_flight_is_the_flight_with_distance_but_no_duration() -> None:
    leg = estimate_leg(_stop("A", 0, 0), _stop("B", 0, 1), "car", after_flight=True)

    assert leg is not None
    assert leg.mode == "flight"
    assert leg.distance_mi == 69.1
    assert leg.duration_min is None
    assert leg.estimated is True


# --- legs in a built itinerary --------------------------------------------------------------


def test_first_item_of_every_day_has_no_leg() -> None:
    plan = _build()

    for day in plan.days:
        assert day.items[0].transit_from_previous is None, day.day_number


def test_first_item_has_no_leg_even_when_the_previous_day_ends_nearby() -> None:
    # Day 1 ends at s5 (0, 2.03); put day 2's first stop right next to it.
    stop_places = dict(EQUATOR_PLACES, s6=_at(0, 2.031))
    plan = _build(stop_places=stop_places)

    assert _legs(plan, 2)[0] is None


def test_day_one_legs_from_known_distances() -> None:
    home_to_iah, flight, sjc_to_hotel, hotel_to_meal = _legs(_build(), 1)[1:]

    # Home → IAH: 1°, no transport given → rideshare.
    assert home_to_iah is not None
    assert (home_to_iah.mode, home_to_iah.distance_mi) == ("rideshare", 69.1)
    assert home_to_iah.duration_min == _minutes(ONE_DEGREE_AT_EQUATOR_MI, 25)
    # The item after the flight item: the flight itself, IAH → SJC.
    assert flight is not None
    assert (flight.mode, flight.distance_mi, flight.duration_min) == ("flight", 69.1, None)
    # SJC → hotel: ≈ 0.69 mi → walk.
    assert sjc_to_hotel is not None
    assert (sjc_to_hotel.mode, sjc_to_hotel.distance_mi, sjc_to_hotel.duration_min) == (
        "walk", 0.7, 14
    )
    # Hotel → meal: ≈ 1.38 mi → rideshare.
    assert hotel_to_meal is not None
    assert (hotel_to_meal.mode, hotel_to_meal.distance_mi) == ("rideshare", 1.4)
    assert hotel_to_meal.duration_min == _minutes(ONE_DEGREE_AT_EQUATOR_MI * 0.02, 25) == 3
    assert all(leg.estimated is True for leg in (home_to_iah, flight, sjc_to_hotel, hotel_to_meal))


def test_profile_transport_sets_the_mode_of_long_legs() -> None:
    plan = _build(profile=_profile(transport="transit"))

    legs = [leg for day in plan.days for leg in _legs(plan, day.day_number) if leg is not None]
    assert {leg.mode for leg in legs} == {"walk", "transit", "flight"}
    hotel_to_meal = _legs(plan, 1)[4]
    assert hotel_to_meal is not None
    assert hotel_to_meal.mode == "transit"
    assert hotel_to_meal.duration_min == _minutes(ONE_DEGREE_AT_EQUATOR_MI * 0.02, 12) == 7


def test_missing_coordinate_on_a_stop_gives_no_leg_to_or_from_it() -> None:
    # Day 2 is s6 → s7 → s8 → s9; s8 has no place, so it stays off the map.
    stop_places = {key: place for key, place in EQUATOR_PLACES.items() if key != "s8"}
    legs = _legs(_build(stop_places=stop_places), 2)

    assert legs[1] is not None  # s6 → s7 still has both coordinates
    assert legs[2] is None  # s7 → s8
    assert legs[3] is None  # s8 → s9


def test_no_coordinates_anywhere_gives_no_legs() -> None:
    plan = _build(stop_places={})

    assert all(item.transit_from_previous is None for day in plan.days for item in day.items)


def test_item_without_a_stop_gives_no_leg_to_or_from_it() -> None:
    raw = copy.deepcopy(load_fake_data("draft_sanjose_v1"))
    day2 = next(day for day in raw["days"] if day["day_number"] == 2)
    day2["items"][1]["stop_key"] = None  # s6 → (no stop) → s8 → s9

    legs = _legs(_build(raw), 2)

    assert legs[1] is None
    assert legs[2] is None
    assert legs[3] is not None  # s8 → s9 is unaffected


def test_two_items_at_the_same_stop_have_no_leg_between_them() -> None:
    raw = copy.deepcopy(load_fake_data("draft_sanjose_v1"))
    day2 = next(day for day in raw["days"] if day["day_number"] == 2)
    day2["items"][1]["stop_key"] = day2["items"][0]["stop_key"]  # s6 → s6 → s8 → s9

    legs = _legs(_build(raw), 2)

    assert legs[1] is None
    assert legs[2] is not None  # s6 → s8


# --- end to end with the fake LLM -----------------------------------------------------------


def _parse_sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
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


def test_generated_plan_has_legs_between_referenced_stops(client: TestClient) -> None:
    provider = FakeProvider()
    client.app.dependency_overrides[get_llm] = lambda: TurnLlms(provider, provider)  # type: ignore[attr-defined]
    session_id = client.post("/api/sessions").json()["id"]
    client.post(f"/api/sessions/{session_id}/messages", json={"content": TRIP_MESSAGE})
    response = client.post(f"/api/sessions/{session_id}/generate", json={})
    assert response.status_code == 200
    plans = [data for name, data in _parse_sse(response.text) if name == "itinerary"]
    assert plans
    plan = Itinerary.model_validate(plans[-1])
    assert itinerary_errors(plan) == []

    stops = {stop.tag: stop for stop in plan.stops}
    legs_found = 0
    for day in plan.days:
        assert day.items[0].transit_from_previous is None
        for previous, item in zip(day.items, day.items[1:]):
            leg = item.transit_from_previous
            origin = stops.get(previous.stop_tag) if previous.stop_tag else None
            destination = stops.get(item.stop_tag) if item.stop_tag else None
            located = (
                origin is not None and destination is not None
                and origin.tag != destination.tag
                and None not in (origin.lat, origin.lng, destination.lat, destination.lng)
            )
            if not located:
                assert leg is None, item.id
                continue
            assert origin is not None and destination is not None  # for the type checker
            distance = haversine_mi(origin.lat, origin.lng, destination.lat, destination.lng)  # type: ignore[arg-type]
            assert leg is not None, item.id
            assert leg.estimated is True
            assert leg.distance_mi == round(distance, 1)
            if previous.kind == "flight":
                assert (leg.mode, leg.duration_min) == ("flight", None)
            else:
                assert leg.mode == travel_mode(distance, None)
                speed = {"walk": 3, "rideshare": 25}[leg.mode]
                assert leg.duration_min == _minutes(distance, speed)
            legs_found += 1
    assert legs_found >= 1
