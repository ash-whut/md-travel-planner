"""Step 42: bookings in the plan + PATCH.

Specified by plan step 42 and contracts §2.2 (bookings rules), §4 and §6: postprocess builds
one round-trip flight booking (departure → arrival airport tags, Google Flights link, no
estimate), one "Hotel Booking" per lodging (total, as of, links) and one booking per
booking-required activity stop (est_cost, "Find tickets" link). Booking-required items get the
`booking_id` of their booking. Ids come from tags, so `status` carries over from the previous
version by id (new → "todo"). `PATCH /api/sessions/{id}/bookings/{booking_id}` changes the
status in the latest version in place (no new version); unknown session/booking → 404, bad
body → 422.

For the fake San Jose draft the tags are: A Home, B IAH, C San Jose Airport, D Pacific Inn,
E San Pedro Square, F Baconhouse, G The Tech Interactive, H Winchester Mystery House, …

All offline: the fake draft, mock tool mode, a temp DB.
"""

import copy
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session

from app.agent.postprocess import HotelPrice, StopPlace, build_itinerary, hotel_source
from app.db import repo
from app.llm.fake_provider import load_fake_data
from app.schemas.itinerary import Booking, Itinerary, ItineraryDraft, Money, itinerary_errors
from app.schemas.profile import TripProfile

START, END = date(2027, 3, 5), date(2027, 3, 7)
HOTEL_SITE = "https://www.example.com/pacific-inn-san-jose"
EXPECTED_IDS = {"bk-flight", "bk-hotel-D", "bk-activity-G", "bk-activity-H"}


# --- helpers --------------------------------------------------------------------------------


def _profile() -> TripProfile:
    return TripProfile(
        budget_level="budget", cities=["San Jose, CA"], travelers=1,
        start_date=START, end_date=END, interests=["food"], origin="College Station, TX",
    )


def _raw() -> dict[str, Any]:
    return copy.deepcopy(load_fake_data("draft_sanjose_v1"))


def _build(
    raw: dict[str, Any] | None = None,
    previous: list[Itinerary] | None = None,
    places_by_key: dict[str, StopPlace] | None = None,
) -> Itinerary:
    plan = build_itinerary(
        ItineraryDraft.model_validate(raw or _raw()), previous or [], _profile(), None,
        places_by_key or {},
    )
    assert isinstance(plan, Itinerary), plan
    assert itinerary_errors(plan) == []
    return plan


def _booking(plan: Itinerary, booking_id: str) -> Booking:
    matches = [booking for booking in plan.bookings if booking.id == booking_id]
    assert len(matches) == 1, [booking.id for booking in plan.bookings]
    return matches[0]


def _items_by_id(plan: Itinerary) -> dict[str, Any]:
    return {item.id: item for day in plan.days for item in day.items}


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)


def _draft_item(raw: dict[str, Any], stop_key: str) -> dict[str, Any]:
    return next(item for day in raw["days"] for item in day["items"]
                if item["stop_key"] == stop_key)


@pytest.fixture
def v1() -> Itinerary:
    return _build()


# --- the expected bookings for the fixture --------------------------------------------------


def test_fixture_gives_exactly_the_expected_bookings(v1: Itinerary) -> None:
    ids = [booking.id for booking in v1.bookings]

    assert sorted(ids) == sorted(EXPECTED_IDS)
    assert all(booking.status == "todo" for booking in v1.bookings)


def test_flight_booking_is_a_round_trip_from_departure_to_arrival(v1: Itinerary) -> None:
    flight = _booking(v1, "bk-flight")

    assert flight.kind == "flight"
    assert flight.tags == ["B", "C"]
    assert flight.title == "Flight Booking"
    assert flight.details == "IAH → San Jose Airport round trip · Mar 5 – Mar 7"
    assert flight.estimate is None
    assert flight.price_as_of is None
    assert [link.label for link in flight.links] == ["Google Flights"]
    url = flight.links[0].url
    assert url.startswith("https://www.google.com/travel/flights?")
    assert _query(url)["q"] == [
        "Flights from IAH to San Jose Airport on 2027-03-05 returning 2027-03-07"
    ]


def test_hotel_booking_from_the_draft_lodging(v1: Itinerary) -> None:
    hotel = _booking(v1, "bk-hotel-D")
    lodging = v1.lodging[0]

    assert hotel.kind == "lodging"
    assert hotel.tags == ["D"]
    assert hotel.title == "Hotel Booking"
    assert hotel.details == "Pacific Inn San Jose · 2 nights · Mar 5 – Mar 7"
    assert hotel.estimate == Money(amount=240, currency="USD")
    assert hotel.estimate == lodging.total_price
    assert hotel.price_as_of is None  # no tool price → no as-of
    assert hotel.links == lodging.links
    assert [link.label for link in hotel.links] == ["Google Hotels", "Booking.com"]


def test_hotel_booking_at_a_found_hotel_uses_the_tool_total_and_as_of() -> None:
    as_of = datetime(2026, 11, 9, 1, 30, tzinfo=timezone.utc)
    hotel = HotelPrice(Money(amount=79, currency="USD"), "serpapi_google_hotels", as_of,
                       link=HOTEL_SITE)
    stop_places = {"s4": StopPlace(lat=37.3398, lng=-121.881, place_id="serpapi:x",
                                   source=hotel_source(hotel), hotel=hotel)}

    plan = _build(places_by_key=stop_places)
    booking = _booking(plan, "bk-hotel-D")

    assert booking.estimate == Money(amount=158, currency="USD")  # 79 × 2 nights
    assert booking.price_as_of == as_of
    assert booking.links == plan.lodging[0].links
    assert any(link.label == "Hotel site" and link.url == HOTEL_SITE for link in booking.links)


def test_activity_bookings_for_booking_required_activities(v1: Itinerary) -> None:
    tech = _booking(v1, "bk-activity-G")
    mansion = _booking(v1, "bk-activity-H")

    assert tech.kind == "activity" and mansion.kind == "activity"
    assert tech.tags == ["G"] and mansion.tags == ["H"]
    assert tech.title == "The Tech Interactive"
    assert mansion.title == "Winchester Mystery House"
    # 2027-03-06 is a Saturday.
    assert tech.details == "Sat, Mar 6 · 1:00 PM"
    assert mansion.details == "Sat, Mar 6 · 4:00 PM"
    assert tech.estimate == Money(amount=32, currency="USD")
    assert mansion.estimate == Money(amount=46, currency="USD")
    assert [link.label for link in tech.links] == ["Find tickets"]
    url = tech.links[0].url
    assert url.startswith("https://www.google.com/search?")
    assert _query(url)["q"] == ["The Tech Interactive San Jose tickets"]


def test_free_activity_without_booking_gets_no_booking(v1: Itinerary) -> None:
    # Guadalupe River Park (K) is an activity, but booking_required is false.
    assert not any(booking.id == "bk-activity-K" for booking in v1.bookings)


def test_booking_required_items_point_at_their_booking(v1: Itinerary) -> None:
    items = _items_by_id(v1)

    assert items["d1-i2"].booking_id == "bk-flight"
    assert items["d1-i4"].booking_id == "bk-hotel-D"
    assert items["d2-i2"].booking_id == "bk-activity-G"
    assert items["d2-i3"].booking_id == "bk-activity-H"
    linked = {item_id for item_id, item in items.items() if item.booking_id is not None}
    assert linked == {"d1-i2", "d1-i4", "d2-i2", "d2-i3"}


def test_every_booking_id_resolves(v1: Itinerary) -> None:
    booking_ids = {booking.id for booking in v1.bookings}

    for item in _items_by_id(v1).values():
        assert item.booking_id is None or item.booking_id in booking_ids
        if item.booking_id is not None:
            assert item.booking_required


def test_plan_without_a_flight_has_no_flight_booking() -> None:
    raw = _raw()
    for day in raw["days"]:
        day["items"] = [item for item in day["items"] if item["kind"] != "flight"]

    plan = _build(raw)

    # Tags shift (IAH is no longer a stop), so check by kind.
    assert "bk-flight" not in {booking.id for booking in plan.bookings}
    assert sorted(booking.kind for booking in plan.bookings) == ["activity", "activity", "lodging"]


def test_bookings_survive_the_saved_json_round_trip(v1: Itinerary) -> None:
    again = Itinerary.model_validate(v1.model_dump(mode="json"))

    assert again.bookings == v1.bookings


# --- status carry-over across v1 → v2 -------------------------------------------------------


def test_status_carries_over_by_id_from_v1_to_v2(v1: Itinerary) -> None:
    _booking(v1, "bk-hotel-D").status = "booked"
    _booking(v1, "bk-activity-G").status = "booked"

    v2 = _build(load_fake_data("draft_sanjose_v1"), previous=[v1])

    assert v2.version == 2
    assert _booking(v2, "bk-hotel-D").status == "booked"
    assert _booking(v2, "bk-activity-G").status == "booked"
    assert _booking(v2, "bk-flight").status == "todo"
    assert _booking(v2, "bk-activity-H").status == "todo"


def test_carry_over_uses_the_latest_version(v1: Itinerary) -> None:
    v2 = _build(previous=[v1])
    _booking(v2, "bk-flight").status = "booked"

    v3 = _build(previous=[v1, v2])

    assert v3.version == 3
    assert _booking(v3, "bk-flight").status == "booked"


def test_status_can_carry_back_to_todo(v1: Itinerary) -> None:
    _booking(v1, "bk-flight").status = "booked"
    v2 = _build(previous=[v1])
    _booking(v2, "bk-flight").status = "todo"

    v3 = _build(previous=[v1, v2])

    assert _booking(v3, "bk-flight").status == "todo"


def test_new_booking_in_v2_starts_as_todo_and_removed_one_is_dropped(v1: Itinerary) -> None:
    for booking in v1.bookings:
        booking.status = "booked"
    raw = _raw()
    # v2: the mansion tour no longer needs booking; the rose garden walk now does.
    _draft_item(raw, "s8")["booking_required"] = False
    _draft_item(raw, "s11")["booking_required"] = True

    v2 = _build(raw, previous=[v1])
    ids = {booking.id for booking in v2.bookings}

    assert "bk-activity-H" not in ids
    assert "bk-activity-K" in ids
    assert _booking(v2, "bk-activity-K").status == "todo"
    assert _booking(v2, "bk-activity-G").status == "booked"
    assert _booking(v2, "bk-hotel-D").status == "booked"
    assert _items_by_id(v2)["d2-i3"].booking_id is None


# --- PATCH /api/sessions/{id}/bookings/{booking_id} -----------------------------------------


def _create_session(client: TestClient) -> str:
    response = client.post("/api/sessions")
    assert response.status_code == 200
    return response.json()["id"]


def _save(engine: Engine, session_id: str, plan: Itinerary) -> Itinerary:
    with Session(engine) as db:
        return repo.save_itinerary(db, session_id, plan)


def _versions(engine: Engine, session_id: str) -> list[Itinerary]:
    with Session(engine) as db:
        return repo.list_itineraries(db, session_id)


def _patch(client: TestClient, session_id: str, booking_id: str, body: Any) -> Any:
    return client.patch(f"/api/sessions/{session_id}/bookings/{booking_id}", json=body)


def _latest_booking(client: TestClient, session_id: str, booking_id: str) -> dict[str, Any]:
    detail = client.get(f"/api/sessions/{session_id}").json()
    return next(b for b in detail["itinerary"]["bookings"] if b["id"] == booking_id)


@pytest.fixture
def planned(client: TestClient, db_engine: Engine) -> str:
    """A session with a saved v1 plan (the fake San Jose draft)."""
    session_id = _create_session(client)
    _save(db_engine, session_id, _build())
    return session_id


def test_patch_returns_the_updated_booking(client: TestClient, planned: str) -> None:
    response = _patch(client, planned, "bk-hotel-D", {"status": "booked"})

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "bk-hotel-D"
    assert body["status"] == "booked"
    assert body["kind"] == "lodging"
    assert body["title"] == "Hotel Booking"
    assert body["estimate"] == {"amount": 240, "currency": "USD"}


def test_patch_persists_in_the_latest_version_without_a_new_one(
    client: TestClient, db_engine: Engine, planned: str
) -> None:
    _patch(client, planned, "bk-activity-G", {"status": "booked"})

    versions = _versions(db_engine, planned)
    assert [plan.version for plan in versions] == [1]
    assert _booking(versions[0], "bk-activity-G").status == "booked"
    assert _booking(versions[0], "bk-flight").status == "todo"
    assert _latest_booking(client, planned, "bk-activity-G")["status"] == "booked"


def test_patch_back_to_todo(client: TestClient, planned: str) -> None:
    _patch(client, planned, "bk-flight", {"status": "booked"})

    response = _patch(client, planned, "bk-flight", {"status": "todo"})

    assert response.status_code == 200
    assert response.json()["status"] == "todo"
    assert _latest_booking(client, planned, "bk-flight")["status"] == "todo"


def test_patch_changes_only_the_latest_version(
    client: TestClient, db_engine: Engine
) -> None:
    session_id = _create_session(client)
    v1 = _save(db_engine, session_id, _build())
    _save(db_engine, session_id, _build(previous=[v1]))

    response = _patch(client, session_id, "bk-hotel-D", {"status": "booked"})

    assert response.status_code == 200
    first, second = _versions(db_engine, session_id)
    assert (first.version, second.version) == (1, 2)
    assert _booking(first, "bk-hotel-D").status == "todo"
    assert _booking(second, "bk-hotel-D").status == "booked"


def test_patched_status_carries_into_the_next_generated_version(
    client: TestClient, db_engine: Engine
) -> None:
    session_id = _create_session(client)
    first = client.post(f"/api/sessions/{session_id}/generate", json={})
    assert first.status_code == 200
    assert _patch(client, session_id, "bk-hotel-D", {"status": "booked"}).status_code == 200

    second = client.post(f"/api/sessions/{session_id}/generate", json={})
    assert second.status_code == 200

    versions = _versions(db_engine, session_id)
    assert [plan.version for plan in versions] == [1, 2]
    assert _booking(versions[1], "bk-hotel-D").status == "booked"
    assert _booking(versions[1], "bk-flight").status == "todo"


def test_patch_unknown_session_is_404(client: TestClient) -> None:
    response = _patch(client, "no-such-session", "bk-flight", {"status": "booked"})

    assert response.status_code == 404
    assert "detail" in response.json()


def test_patch_unknown_booking_is_404(client: TestClient, db_engine: Engine,
                                      planned: str) -> None:
    response = _patch(client, planned, "bk-hotel-Z", {"status": "booked"})

    assert response.status_code == 404
    assert "detail" in response.json()
    assert all(b.status == "todo" for b in _versions(db_engine, planned)[0].bookings)


def test_patch_session_without_a_plan_is_404(client: TestClient) -> None:
    session_id = _create_session(client)

    response = _patch(client, session_id, "bk-flight", {"status": "booked"})

    assert response.status_code == 404


@pytest.mark.parametrize("body", [{"status": "done"}, {"status": ""}, {}, {"status": None}])
def test_patch_bad_status_is_422(client: TestClient, db_engine: Engine, planned: str,
                                 body: dict[str, Any]) -> None:
    response = _patch(client, planned, "bk-flight", body)

    assert response.status_code == 422
    assert _booking(_versions(db_engine, planned)[0], "bk-flight").status == "todo"
