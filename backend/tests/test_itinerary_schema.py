"""Step 18: Itinerary + ItineraryDraft schemas and the contracts §2.2 validation rules.

Specified by plan step 18 and contracts §2.2 (Itinerary + validation list) and §2.3 (draft).
The shared fixtures in frontend/src/fixtures/ are the reference itineraries.
"""

import copy
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.itinerary import Itinerary, ItineraryDraft, itinerary_errors

FIXTURES = Path(__file__).resolve().parents[2] / "frontend" / "src" / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def v1() -> dict[str, Any]:
    return load_fixture("sanjose-v1.json")


def expect_invalid(data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Itinerary.model_validate(data)


# ---- The shared fixtures are valid ----

@pytest.mark.parametrize("name", ["sanjose-v1.json", "sanjose-v2.json"])
def test_shared_fixtures_validate(name: str) -> None:
    itinerary = Itinerary.model_validate(load_fixture(name))
    assert itinerary_errors(itinerary) == []
    assert len(itinerary.days) == (itinerary.end_date - itinerary.start_date).days + 1


def test_fixture_round_trips_through_json(v1: dict[str, Any]) -> None:
    itinerary = Itinerary.model_validate(v1)
    again = Itinerary.model_validate_json(itinerary.model_dump_json())
    assert again == itinerary


# ---- Days: count, numbering, dates ----

def test_day_number_gap_fails(v1: dict[str, Any]) -> None:
    v1["days"][1]["day_number"] = 3
    v1["days"][2]["day_number"] = 4
    expect_invalid(v1)


def test_missing_middle_day_fails(v1: dict[str, Any]) -> None:
    # Day 2 removed: day numbers jump 1 -> 3 and the count no longer matches the dates.
    del v1["days"][1]
    expect_invalid(v1)


def test_day_date_mismatch_fails(v1: dict[str, Any]) -> None:
    v1["days"][1]["date"] = v1["days"][2]["date"]
    expect_invalid(v1)


def test_day_count_must_match_date_range(v1: dict[str, Any]) -> None:
    end = date.fromisoformat(v1["end_date"]) + timedelta(days=1)
    v1["end_date"] = end.isoformat()
    expect_invalid(v1)


def test_zero_days_fails(v1: dict[str, Any]) -> None:
    v1["days"] = []
    v1["end_date"] = v1["start_date"]
    expect_invalid(v1)


def _stretch_to(data: dict[str, Any], n_days: int) -> dict[str, Any]:
    """Copy the last day until there are n_days, keeping numbers and dates consistent."""
    start = date.fromisoformat(data["start_date"])
    template = data["days"][-1]
    while len(data["days"]) < n_days:
        day = copy.deepcopy(template)
        index = len(data["days"])
        day["day_number"] = index + 1
        day["date"] = (start + timedelta(days=index)).isoformat()
        for i, item in enumerate(day["items"]):
            item["id"] = f"d{index + 1}-i{i + 1}"
        data["days"].append(day)
    data["end_date"] = (start + timedelta(days=n_days - 1)).isoformat()
    return data


def test_seven_days_is_allowed(v1: dict[str, Any]) -> None:
    Itinerary.model_validate(_stretch_to(v1, 7))


def test_more_than_seven_days_fails(v1: dict[str, Any]) -> None:
    expect_invalid(_stretch_to(v1, 8))


def test_single_day_trip_is_allowed(v1: dict[str, Any]) -> None:
    v1["days"] = v1["days"][:1]
    v1["end_date"] = v1["start_date"]
    v1["lodging"] = []
    Itinerary.model_validate(v1)


# ---- Items sorted by start_time ----

def test_unsorted_items_fail(v1: dict[str, Any]) -> None:
    items = v1["days"][0]["items"]
    assert len(items) >= 2
    items[0], items[1] = items[1], items[0]
    expect_invalid(v1)


@pytest.mark.parametrize("bad_time", ["9:15", "24:00", "12:60", "noon", ""])
def test_bad_start_time_fails(v1: dict[str, Any], bad_time: str) -> None:
    v1["days"][0]["items"][0]["start_time"] = bad_time
    expect_invalid(v1)


# ---- References resolve ----

def test_unknown_item_stop_tag_fails(v1: dict[str, Any]) -> None:
    v1["days"][0]["items"][0]["stop_tag"] = "ZZ"
    expect_invalid(v1)


def test_null_item_stop_tag_is_allowed(v1: dict[str, Any]) -> None:
    v1["days"][0]["items"][0]["stop_tag"] = None
    Itinerary.model_validate(v1)


def test_unknown_lodging_stop_tag_fails(v1: dict[str, Any]) -> None:
    assert v1["lodging"], "fixture should have a lodging entry"
    v1["lodging"][0]["stop_tag"] = "ZZ"
    expect_invalid(v1)


def test_unknown_booking_id_fails(v1: dict[str, Any]) -> None:
    v1["days"][0]["items"][0]["booking_id"] = "bk-does-not-exist"
    expect_invalid(v1)


def test_removing_a_used_stop_fails(v1: dict[str, Any]) -> None:
    used = v1["days"][0]["items"][0]["stop_tag"]
    v1["stops"] = [stop for stop in v1["stops"] if stop["tag"] != used]
    expect_invalid(v1)


# ---- Cities and lodging limits ----

def test_more_than_two_cities_fails(v1: dict[str, Any]) -> None:
    v1["cities"] = [
        {"name": "San Jose"}, {"name": "San Francisco"}, {"name": "Oakland"},
    ]
    expect_invalid(v1)


def test_two_cities_is_allowed(v1: dict[str, Any]) -> None:
    v1["cities"].append({"name": "San Francisco", "lat": None, "lng": None})
    Itinerary.model_validate(v1)


def test_more_than_two_lodging_entries_fails(v1: dict[str, Any]) -> None:
    v1["lodging"] = [copy.deepcopy(v1["lodging"][0]) for _ in range(3)]
    expect_invalid(v1)


# ---- Lat/lng ranges ----

@pytest.mark.parametrize(
    ("field", "value"),
    [("lat", 90.5), ("lat", -91), ("lng", 180.1), ("lng", -181)],
)
def test_bad_stop_coordinates_fail(v1: dict[str, Any], field: str, value: float) -> None:
    v1["stops"][0][field] = value
    expect_invalid(v1)


@pytest.mark.parametrize(("field", "value"), [("lat", 100), ("lng", -200)])
def test_bad_city_coordinates_fail(v1: dict[str, Any], field: str, value: float) -> None:
    v1["cities"][0][field] = value
    expect_invalid(v1)


def test_null_and_edge_coordinates_are_allowed(v1: dict[str, Any]) -> None:
    v1["stops"][0]["lat"] = None
    v1["stops"][0]["lng"] = None
    v1["stops"][1]["lat"] = 90
    v1["stops"][1]["lng"] = -180
    Itinerary.model_validate(v1)


# ---- All broken rules are reported together ----

def test_itinerary_errors_lists_every_broken_rule(v1: dict[str, Any]) -> None:
    itinerary = Itinerary.model_validate(v1)
    items = itinerary.days[0].items
    items[0], items[1] = items[1], items[0]  # unsorted
    items[0].stop_tag = "ZZ"  # unknown tag
    errors = itinerary_errors(itinerary)
    assert len(errors) >= 2


# ---- ItineraryDraft (contracts §2.3) ----

def make_draft(n_days: int = 2) -> dict[str, Any]:
    start = date(2027, 3, 5)
    return {
        "title": "San Jose weekend",
        "summary": "Short trip.",
        "start_date": start.isoformat(),
        "end_date": (start + timedelta(days=n_days - 1)).isoformat(),
        "travelers": 1,
        "cities": [{"name": "San Jose", "region": "CA", "country": "USA"}],
        "assumptions": [],
        "stops": [
            {"key": "s1", "name": "Hotel Clariana", "kind": "lodging"},
            {"key": "s2", "name": "Tacos El Gordo", "kind": "food"},
        ],
        "lodging": [
            {
                "stop_key": "s1",
                "check_in": start.isoformat(),
                "check_out": (start + timedelta(days=n_days - 1)).isoformat(),
                "nights": max(n_days - 1, 1),
            }
        ],
        "days": [
            {
                "day_number": i + 1,
                "date": (start + timedelta(days=i)).isoformat(),
                "title": f"Day {i + 1}",
                "city": "San Jose",
                "items": [
                    {"kind": "meal", "stop_key": "s2", "description": "Lunch", "start_time": "12:00"},
                    {"kind": "free_time", "description": "Wander", "start_time": "15:00"},
                ],
            }
            for i in range(n_days)
        ],
    }


def test_valid_draft_parses() -> None:
    draft = ItineraryDraft.model_validate(make_draft())
    assert [stop.key for stop in draft.stops] == ["s1", "s2"]
    assert draft.days[0].items[0].stop_key == "s2"


def test_draft_has_no_code_owned_fields() -> None:
    # §2.3: the draft is the Itinerary minus ids, version, tags, coordinates, bookings, etc.
    fields = set(ItineraryDraft.model_fields)
    for owned in ("id", "version", "created_at", "bookings", "weather_summary"):
        assert owned not in fields
    stop_fields = set(ItineraryDraft.model_fields["stops"].annotation.__args__[0].model_fields)
    assert "key" in stop_fields
    assert not {"tag", "lat", "lng"} & stop_fields


def test_draft_unknown_stop_key_fails() -> None:
    data = make_draft()
    data["days"][0]["items"][0]["stop_key"] = "s99"
    with pytest.raises(ValidationError):
        ItineraryDraft.model_validate(data)


def test_draft_unknown_lodging_stop_key_fails() -> None:
    data = make_draft()
    data["lodging"][0]["stop_key"] = "s99"
    with pytest.raises(ValidationError):
        ItineraryDraft.model_validate(data)


def test_draft_more_than_two_cities_fails() -> None:
    data = make_draft()
    data["cities"] = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
    with pytest.raises(ValidationError):
        ItineraryDraft.model_validate(data)


def test_draft_more_than_seven_days_fails() -> None:
    with pytest.raises(ValidationError):
        ItineraryDraft.model_validate(make_draft(n_days=8))


def test_draft_bad_start_time_fails() -> None:
    data = make_draft()
    data["days"][0]["items"][0]["start_time"] = "25:00"
    with pytest.raises(ValidationError):
        ItineraryDraft.model_validate(data)
