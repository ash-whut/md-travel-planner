"""Step 52 through the chat API, offline (Done when: "make the plan" → "swap the hotel for an
Airbnb" shows a rental in v2).

Specified by plan step 52, contracts §2.2 (bookings: ids come from tags, `status` carries over
by id, new → "todo"; "Rental Booking"), §3 (a different place gets a new letter, the old one is
retired), §6 (rental links: Google Hotels + Airbnb search, no Booking.com) and D35 (an edit
without a fresh flight result keeps the fare while route and dates are unchanged).

Fake LLM, mock tools (conftest sets TOOL_PROVIDER_MODE=mock), temp DB.
"""

import json
from typing import Any

from fastapi.testclient import TestClient

from app.agent.turn import TurnLlms
from app.api.chat import get_llm
from app.llm.fake_provider import FakeProvider
from app.schemas.itinerary import Itinerary, itinerary_errors

TRIP_MESSAGE = (
    "San Jose from College Station, first weekend of March, just me. "
    "I like tech, food and gardens."
)
SWAP_MESSAGE = "swap the hotel for an Airbnb"
VEGAN_MESSAGE = "replace [F] with something vegan"


def _start(client: TestClient) -> str:
    provider = FakeProvider()
    client.app.dependency_overrides[get_llm] = lambda: TurnLlms(provider, provider)  # type: ignore[attr-defined]
    session_id = client.post("/api/sessions").json()["id"]
    assert client.post(f"/api/sessions/{session_id}/messages",
                       json={"content": TRIP_MESSAGE}).status_code == 200
    return session_id


def _say(client: TestClient, session_id: str, text: str) -> Itinerary:
    """Send a chat message; the last itinerary in its SSE stream (it must have one)."""
    response = client.post(f"/api/sessions/{session_id}/messages", json={"content": text})
    assert response.status_code == 200
    plans = [
        json.loads(line[len("data:"):])
        for block in response.text.replace("\r\n", "\n").split("\n\n")
        if "event: itinerary" in block
        for line in block.split("\n")
        if line.startswith("data:")
    ]
    assert plans, response.text
    plan = Itinerary.model_validate(plans[-1])
    assert itinerary_errors(plan) == []
    return plan


def _saved(client: TestClient, session_id: str) -> Itinerary:
    return Itinerary.model_validate(client.get(f"/api/sessions/{session_id}").json()["itinerary"])


def _book(client: TestClient, session_id: str, booking_id: str) -> None:
    response = client.patch(f"/api/sessions/{session_id}/bookings/{booking_id}",
                            json={"status": "booked"})
    assert response.status_code == 200, response.text


def _lodging_stop(plan: Itinerary) -> Any:
    return next(stop for stop in plan.stops if stop.kind == "lodging")


def _booking(plan: Itinerary, kind: str) -> Any:
    return next(booking for booking in plan.bookings if booking.kind == kind)


def _flight_item(plan: Itinerary) -> Any:
    return next(item for day in plan.days for item in day.items if item.kind == "flight")


def test_make_the_plan_then_swap_for_an_airbnb_shows_a_rental(client: TestClient) -> None:
    session_id = _start(client)
    v1 = _say(client, session_id, "make the plan")
    assert v1.version == 1
    assert v1.lodging[0].type == "hotel"
    assert _booking(v1, "lodging").title == "Hotel Booking"

    v2 = _say(client, session_id, SWAP_MESSAGE)

    assert v2.version == 2
    assert _saved(client, session_id) == v2  # the streamed v2 is the saved latest version
    lodging = v2.lodging[0]
    assert lodging.type == "vacation_rental"
    assert lodging.price_source == "serpapi_google_hotels"
    assert lodging.price_per_night is not None
    assert lodging.price_per_night != v1.lodging[0].price_per_night
    labels = [link.label for link in lodging.links]
    assert "Airbnb" in labels and "Booking.com" not in labels
    airbnb = next(link.url for link in lodging.links if link.label == "Airbnb")
    assert airbnb.startswith("https://www.airbnb.com/s/")
    assert "checkin=2027-03-05" in airbnb and "checkout=2027-03-07" in airbnb
    assert _booking(v2, "lodging").title == "Rental Booking"
    assert _lodging_stop(v2).tag != _lodging_stop(v1).tag


def test_swap_gives_a_new_lodging_booking_and_keeps_other_statuses(client: TestClient) -> None:
    session_id = _start(client)
    v1 = _say(client, session_id, "make the plan")
    old_hotel_id = _booking(v1, "lodging").id
    _book(client, session_id, old_hotel_id)
    _book(client, session_id, "bk-flight")

    v2 = _say(client, session_id, SWAP_MESSAGE)

    # The rental is a new place with a new tag, so its booking is new → "todo"; the old
    # hotel booking id is gone.
    new_booking = _booking(v2, "lodging")
    assert new_booking.id == f"bk-hotel-{_lodging_stop(v2).tag}"
    assert new_booking.id != old_hotel_id
    assert new_booking.status == "todo"
    assert old_hotel_id not in {booking.id for booking in v2.bookings}
    # The flight booking keeps its id and status ("booked").
    assert _booking(v2, "flight").status == "booked"
    # Every booking id the edit didn't touch keeps its status.
    v1_status = {booking.id: booking.status for booking in v1.bookings}
    for booking in v2.bookings:
        if booking.id in v1_status and booking.id not in (old_hotel_id, "bk-flight"):
            assert booking.status == v1_status[booking.id], booking.id


def test_swap_keeps_the_flight_fare(client: TestClient) -> None:
    # D35: a stay edit runs no flight search; route and dates are unchanged, so the fare stays.
    session_id = _start(client)
    v1 = _say(client, session_id, "make the plan")
    before = _flight_item(v1)
    assert before.est_cost is not None and before.cost_source == "tool"

    v2 = _say(client, session_id, SWAP_MESSAGE)

    after = _flight_item(v2)
    assert (after.est_cost, after.cost_source, after.source) == (
        before.est_cost, before.cost_source, before.source
    )
    assert _booking(v2, "flight").estimate == _booking(v1, "flight").estimate


def test_vegan_edit_keeps_the_booked_lodging_booking(client: TestClient) -> None:
    session_id = _start(client)
    v1 = _say(client, session_id, "make the plan")
    hotel_id = _booking(v1, "lodging").id
    _book(client, session_id, hotel_id)

    v2 = _say(client, session_id, VEGAN_MESSAGE)

    assert v2.version == 2
    booking = _booking(v2, "lodging")
    assert (booking.id, booking.status, booking.title) == (hotel_id, "booked", "Hotel Booking")
    assert v2.lodging == v1.lodging


def test_swap_after_a_rental_v1_keeps_a_rental(client: TestClient) -> None:
    # Edge case: a rental plan asked for an Airbnb again stays a valid rental plan.
    session_id = _start(client)
    assert client.post(f"/api/sessions/{session_id}/messages",
                       json={"content": "We'd like an Airbnb"}).status_code == 200
    v1 = _say(client, session_id, "make the plan")
    assert v1.lodging[0].type == "vacation_rental"

    v2 = _say(client, session_id, SWAP_MESSAGE)

    assert v2.lodging[0].type == "vacation_rental"
    assert _booking(v2, "lodging").title == "Rental Booking"
