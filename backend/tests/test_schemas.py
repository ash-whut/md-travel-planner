"""Schemas from 03-contracts §2 and §4, and the Itinerary validation rules."""

import copy
import re
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.schemas import (
    DoneData,
    ErrorData,
    Itinerary,
    ItineraryDraft,
    Message,
    MessageStartData,
    SessionDetail,
    SessionSummary,
    StatusData,
    TokenData,
    TripProfile,
)

# --- Itinerary: valid shapes ---------------------------------------------------------------


def test_good_fixture_is_valid_and_round_trips(austin):
    itinerary = Itinerary.model_validate(austin)

    assert itinerary.places[0].tag == "A"
    assert itinerary.lodging[0].tag == "H1"
    assert itinerary.model_dump(mode="json") == austin


def test_bare_h_is_a_place_tag_not_lodging(austin):
    # Torchy's Tacos is place "H" (d2-i4); it must resolve against places, not lodging.
    austin["places"] = [p for p in austin["places"] if p["tag"] != "H"]

    with pytest.raises(ValidationError, match=re.escape("item d2-i4: place_tag 'H' not found in places")):
        Itinerary.model_validate(austin)


def test_later_stage_fields_are_accepted(austin):
    """Coordinates (Stage 2), prices, weather and transit (Stage 3) fit the same model."""
    austin["cities"][0].update(lat=30.2672, lng=-97.7431)
    austin["places"][0].update(lat=30.2701, lng=-97.7312, place_id="ChIJ-franklin", rating=4.7)
    austin["lodging"][0].update(
        lat=30.26,
        lng=-97.74,
        place_id="ChIJ-hampton",
        rating=4.1,
        price_per_night={"amount": 89, "currency": "USD"},
        total_price={"amount": 178, "currency": "USD"},
        price_as_of="2026-11-01T18:04:05+00:00",
        price_source="serpapi_google_hotels",
        alternatives=[
            {"name": "Other Inn", "total_price": {"amount": 199}, "rating": 4.3, "link": "https://x"},
            {"name": "Unrated Inn", "total_price": {"amount": 210}, "rating": None, "link": "https://y"},
        ],
        links=[{"label": "Booking.com", "url": "https://www.booking.com/"}],
    )
    austin["days"][0]["weather"] = {
        "high_f": 72, "low_f": 51, "condition": "sunny", "precip_chance": 10, "source": "forecast"
    }
    austin["days"][1]["weather"] = {
        "high_f": None, "low_f": None, "condition": None, "precip_chance": None, "source": "unavailable"
    }
    austin["days"][2]["weather"] = {"high_f": 70, "low_f": 49, "source": "climate"}  # condition/precip may be null
    austin["days"][0]["items"][1]["transit_from_previous"] = {"mode": "drive", "duration_min": 12, "distance_mi": 3.4}

    dumped = Itinerary.model_validate(austin).model_dump(mode="json")

    assert dumped["lodging"][0]["price_as_of"] == "2026-11-01T18:04:05Z"
    assert dumped["lodging"][0]["alternatives"][0]["total_price"]["currency"] == "USD"


# --- Itinerary: validation rules (03 §2.2) --------------------------------------------------


def _set(path: tuple, value):
    """Mutation that sets austin[path[0]][path[1]]... = value."""

    def mutate(data: dict) -> None:
        target = data
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return mutate


def _swap_first_items(data: dict) -> None:
    items = data["days"][0]["items"]
    items[1], items[2] = items[2], items[1]


def _eight_days(data: dict) -> None:
    template = data["days"][0]
    start = datetime.fromisoformat(data["start_date"]).date()
    data["days"] = []
    for i in range(8):
        day = copy.deepcopy(template)
        day["day_number"] = i + 1
        day["date"] = (start + timedelta(days=i)).isoformat()
        for item in day["items"]:
            item["id"] = f"d{i + 1}-{item['id']}"
        data["days"].append(day)
    data["end_date"] = (start + timedelta(days=7)).isoformat()


def _three_cities(data: dict) -> None:
    data["cities"] += [
        {"name": "San Antonio", "region": "TX", "country": "USA"},
        {"name": "Houston", "region": "TX", "country": "USA"},
    ]


def _three_lodging(data: dict) -> None:
    hotel = data["lodging"][0]
    data["lodging"] = [hotel, {**hotel, "tag": "H2"}, {**hotel, "tag": "H2"}]


def _duplicate_checklist_id(data: dict) -> None:
    data["checklist"][1]["id"] = data["checklist"][0]["id"]


INVALID_CASES = [
    # (case id, mutation, expected text in the error)
    ("unresolved place tag", _set(("days", 1, "items", 2, "place_tag"), "Q"),
     "day 2 item d2-i3: place_tag 'Q' not found in places"),
    ("unresolved lodging place_tag", _set(("days", 0, "items", 3, "place_tag"), "H2"),
     "day 1 item d1-i4: place_tag 'H2' not found in lodging"),
    ("unresolved day lodging_tag", _set(("days", 0, "lodging_tag"), "H2"),
     "day 1: lodging_tag 'H2' not found in lodging"),
    ("unresolved checklist id", _set(("days", 1, "items", 6, "checklist_item_id"), "chk-nope"),
     "day 2 item d2-i7: checklist_item_id 'chk-nope' not found in checklist"),
    ("booking item without checklist item", _set(("days", 1, "items", 6, "checklist_item_id"), None),
     "day 2 item d2-i7: booking_required is true but checklist_item_id is null"),
    ("items not sorted", _swap_first_items,
     "day 1: items not sorted by start_time (d1-i2 at 11:00 is listed after d1-i3 at 13:00)"),
    ("day count != date range", _set(("end_date",), "2027-03-09"),
     "3 days given, but 2027-03-06 to 2027-03-09 is 4 days"),
    ("end before start", _set(("end_date",), "2027-03-05"),
     "end_date 2027-03-05 is before start_date 2027-03-06"),
    ("day_number not contiguous", _set(("days", 2, "day_number"), 4),
     "days[2]: day_number is 4, expected 3"),
    ("day date mismatch", _set(("days", 1, "date"), "2027-03-08"),
     "day 2: date is 2027-03-08, expected 2027-03-07"),
    ("more than 7 days", _eight_days, "List should have at most 7 items"),
    ("no days", _set(("days",), []), "List should have at least 1 item"),
    ("more than 2 cities", _three_cities, "List should have at most 2 items"),
    ("more than 2 lodging", _three_lodging, "List should have at most 2 items"),
    ("lat out of range", _set(("places", 0, "lat"), 91), "less than or equal to 90"),
    ("lng out of range", _set(("lodging", 0, "lng"), -181), "greater than or equal to -180"),
    ("lowercase place tag", _set(("places", 0, "tag"), "a"), "String should match pattern"),
    ("place tag with digit", _set(("places", 0, "tag"), "A1"), "String should match pattern"),
    ("lodging tag H3", _set(("lodging", 0, "tag"), "H3"), "String should match pattern"),
    ("duplicate place tag", _set(("places", 1, "tag"), "A"), "places tag 'A' is used more than once"),
    ("duplicate item id", _set(("days", 0, "items", 1, "id"), "d1-i1"), "item id 'd1-i1' is used more than once"),
    ("duplicate checklist id", _duplicate_checklist_id, "checklist id 'chk-lodging-H1' is used more than once"),
    ("price with price_source none", _set(("lodging", 0, "total_price"), {"amount": 178, "currency": "USD"}),
     "lodging H1: price_source is 'none'"),
    ("time not HH:MM", _set(("days", 0, "items", 0, "start_time"), "8:30"), "String should match pattern"),
    ("unknown place category", _set(("places", 0, "category"), "bar"), "Input should be"),
    ("unknown item kind", _set(("days", 0, "items", 0, "kind"), "drive"), "Input should be"),
    ("weather numbers with source unavailable",
     _set(("days", 0, "weather"), {"high_f": 70, "low_f": 50, "source": "unavailable"}),
     "weather: source is 'unavailable', so high_f, low_f, condition and precip_chance must be null"),
    ("forecast weather without temperatures",
     _set(("days", 0, "weather"), {"condition": "sunny", "source": "forecast"}),
     "weather: source is 'forecast', so high_f and low_f are required"),
]


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [case[1:] for case in INVALID_CASES],
    ids=[case[0] for case in INVALID_CASES],
)
def test_invalid_itinerary_is_rejected(austin, mutate, expected):
    mutate(austin)

    with pytest.raises(ValidationError, match=re.escape(expected)):
        Itinerary.model_validate(austin)


def test_bad_fixture_reports_every_problem(austin_bad):
    with pytest.raises(ValidationError) as excinfo:
        Itinerary.model_validate(austin_bad)

    message = str(excinfo.value)
    for expected in [
        "3 days given, but 2027-03-06 to 2027-03-09 is 4 days",
        "day 1: items not sorted by start_time",
        "day 2 item d2-i3: place_tag 'Q' not found in places",
        "day 2 item d2-i7: booking_required is true but checklist_item_id is null",
    ]:
        assert expected in message


# --- TripProfile ----------------------------------------------------------------------------


def test_trip_profile_defaults_are_empty():
    profile = TripProfile()

    assert profile.cities == []
    assert profile.budget_level == "budget"
    assert profile.missing_required == []
    assert TripProfile.model_validate({}) == profile


def test_trip_profile_contract_example():
    profile = TripProfile.model_validate(
        {
            "cities": ["Austin"], "start_date": "2027-03-06", "end_date": "2027-03-08",
            "duration_days": 3, "origin": "College Station, TX", "travelers": 3,
            "budget_level": "budget", "interests": ["food", "live music"], "pace": "balanced",
            "transport": "car", "missing_required": ["interests"],
        }
    )

    assert profile.model_dump(mode="json")["start_date"] == "2027-03-06"


def test_trip_profile_null_budget_falls_back_to_default():
    assert TripProfile.model_validate({"budget_level": None}).budget_level == "budget"


@pytest.mark.parametrize(
    "bad",
    [
        {"cities": ["Austin", "Dallas", "Houston"]},
        {"travelers": 7},
        {"duration_days": 8},
        {"budget_level": "cheap"},
        {"missing_required": ["hotel"]},
    ],
)
def test_trip_profile_rejects_out_of_range(bad):
    with pytest.raises(ValidationError):
        TripProfile.model_validate(bad)


# --- Session DTOs ---------------------------------------------------------------------------


def test_session_detail_serializes_utc_timestamps(austin):
    naive = datetime(2026, 11, 2, 18, 4, 5, 123456)  # SQLite returns naive UTC datetimes
    detail = SessionDetail(
        id="s1",
        title="New trip",
        status="planned",
        trip_profile={},
        messages=[Message(id="m1", role="assistant", content="Hi!", created_at=naive)],
        itinerary=austin,
        created_at=naive,
        updated_at=datetime(2026, 11, 2, 13, 4, 5, tzinfo=timezone(timedelta(hours=-5))),
    )

    dumped = detail.model_dump(mode="json")

    assert dumped["created_at"] == "2026-11-02T18:04:05Z"
    assert dumped["updated_at"] == "2026-11-02T18:04:05Z"  # converted to UTC
    assert dumped["messages"][0] == {
        "id": "m1", "role": "assistant", "content": "Hi!", "itinerary_version": None,
        "created_at": "2026-11-02T18:04:05Z",
    }
    assert dumped["chat_enabled"] is True
    assert dumped["itinerary"]["id"] == austin["id"]


def test_session_summary_shape():
    summary = SessionSummary(id="s1", title="Austin · Mar 6–8", status="intake", updated_at=datetime(2026, 11, 2))

    assert summary.model_dump(mode="json") == {
        "id": "s1", "title": "Austin · Mar 6–8", "status": "intake", "updated_at": "2026-11-02T00:00:00Z"
    }


def test_message_rejects_unknown_role():
    with pytest.raises(ValidationError):
        Message(id="m1", role="system", content="x", created_at=datetime(2026, 11, 2))


# --- SSE payloads (03 §4) -------------------------------------------------------------------


def test_sse_payload_shapes():
    assert MessageStartData(message_id="m1").model_dump() == {"message_id": "m1"}
    assert TokenData(text="Hel").model_dump() == {"text": "Hel"}
    assert StatusData(label="Drafting your itinerary…", state="start").model_dump() == {
        "label": "Drafting your itinerary…", "tool": None, "state": "start"
    }
    assert ErrorData(message="Something went wrong.", retryable=True).model_dump() == {
        "message": "Something went wrong.", "retryable": True
    }
    assert DoneData(message_id="m1").model_dump() == {"message_id": "m1"}


def test_status_state_is_limited():
    with pytest.raises(ValidationError):
        StatusData(label="x", state="running")


# --- ItineraryDraft (04 §5.0) -----------------------------------------------------------------


def test_draft_fixture_is_valid(draft):
    parsed = ItineraryDraft.model_validate(draft)

    assert parsed.days[0].items[1].place.name == "Franklin Barbecue"


@pytest.mark.parametrize(
    "inner",
    [
        {"name": "Franklin Barbecue", "category": "food", "address": "900 E 11th St"},
        {"day_number": 1, "date": "2027-03-06", "title": "Arrival", "city": "Austin", "items": []},
        {"currency": "USD", "low": 230, "high": 340, "breakdown": []},
    ],
    ids=["place", "day", "cost-estimate"],
)
def test_bare_inner_object_is_not_a_draft(inner):
    """`extract_json` can return an inner object from a truncated reply; it must not pass."""
    with pytest.raises(ValidationError):
        ItineraryDraft.model_validate(inner)


@pytest.mark.parametrize(
    "field",
    [
        "title", "summary", "start_date", "end_date", "travelers",
        "cities", "cost_estimate", "assumptions", "lodging", "days",
    ],
)
def test_draft_top_level_fields_are_required(draft, field):
    del draft[field]

    with pytest.raises(ValidationError, match=field):
        ItineraryDraft.model_validate(draft)


def test_draft_rejects_unknown_top_level_keys(draft):
    draft["places"] = []

    with pytest.raises(ValidationError, match="places"):
        ItineraryDraft.model_validate(draft)


def test_draft_cost_estimate_may_be_null(draft):
    draft["cost_estimate"] = None

    assert ItineraryDraft.model_validate(draft).cost_estimate is None


def test_draft_nested_optional_fields_default_to_null(draft):
    terse = {
        "kind": "free_time", "title": "Rest", "description": "Downtime.", "start_time": "15:00", "end_time": "18:00"
    }
    draft["days"][1]["items"][4] = terse

    parsed = ItineraryDraft.model_validate(draft).days[1].items[4]

    assert (parsed.place, parsed.lodging_ref, parsed.est_cost, parsed.booking_required, parsed.tips) == (
        None, None, None, False, None
    )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d["days"].pop(), "2 days given, but 2027-03-06 to 2027-03-08 is 3 days"),
        (lambda d: d["days"][1].update(date="2027-03-09"), "day 2: date is 2027-03-09, expected 2027-03-07"),
        (
            lambda d: d["days"][0]["items"][3].update(lodging_ref="Motel 6"),
            "day 1 items[3]: lodging_ref 'Motel 6' does not match the name of any lodging entry",
        ),
        (
            lambda d: d["lodging"][0].update(check_out="2027-03-06"),
            "check_out 2027-03-06 must be after check_in 2027-03-06",
        ),
        (lambda d: d["lodging"].append(dict(d["lodging"][0])), "lodging entries must have different names"),
        (lambda d: d["days"][0]["items"][0].update(start_time="8:30"), "start_time"),
        (
            lambda d: d["lodging"][0].update(check_in="2027-03-05"),
            "stay 2027-03-05 to 2027-03-08 must be within the trip "
            "(check_in on or after 2027-03-06, check_out on or before 2027-03-08)",
        ),
        (
            lambda d: d["lodging"][0].update(check_out="2027-03-09"),  # no hotel night after the departure day
            "stay 2027-03-06 to 2027-03-09 must be within the trip",
        ),
        (
            lambda d: d["lodging"].append(dict(d["lodging"][0], name="Second Inn", check_in="2027-03-07")),
            "lodging 'Second Inn': check_in 2027-03-07 is before check_out 2027-03-08 of "
            "'Hampton Inn & Suites Austin-Downtown/Convention Center'; hotel stays must not overlap",
        ),
    ],
    ids=[
        "day-count", "day-date", "lodging-ref", "check-out", "duplicate-hotel", "time-format",
        "check-in-before-trip", "check-out-after-trip", "overlapping-stays",
    ],
)
def test_draft_consistency_errors_say_what_and_where(draft, mutate, message):
    mutate(draft)

    with pytest.raises(ValidationError, match=re.escape(message)):
        ItineraryDraft.model_validate(draft)


def test_draft_allows_back_to_back_hotels(draft):
    draft["lodging"] = [
        {"name": "First Inn", "city": "Austin", "check_in": "2027-03-06", "check_out": "2027-03-07"},
        {"name": "Second Inn", "city": "Austin", "check_in": "2027-03-07", "check_out": "2027-03-08"},
    ]
    draft["days"][0]["items"][3]["lodging_ref"] = "First Inn"
    draft["days"][2]["items"][0]["lodging_ref"] = "Second Inn"

    assert len(ItineraryDraft.model_validate(draft).lodging) == 2


def test_draft_schema_has_no_code_owned_fields():
    """Hard rule 5: tags, IDs, links, coordinates, prices and weather never come from the LLM."""
    names: set[str] = set()

    def collect(node):
        if isinstance(node, dict):
            names.update(node.get("properties", {}))
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)

    collect(ItineraryDraft.model_json_schema())

    code_owned = {
        "id", "tag", "place_tag", "lodging_tag", "checklist_item_id", "maps_url", "links", "lat", "lng",
        "place_id", "rating", "price_per_night", "total_price", "price_as_of", "weather", "checklist",
    }
    assert names & code_owned == set()
    assert {"place", "lodging_ref", "booking_required"} <= names
