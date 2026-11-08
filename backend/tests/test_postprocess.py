"""Step 21: postprocess (draft -> itinerary).

Specified by plan step 21 and contracts §2.2, §2.3, §3: a good draft -> a valid itinerary with the
expected letters; a v2 draft -> `updated_in_version` only on the changed item; a bad draft ->
errors, no exception. Also checks the fields code owns (ids, version, null coordinates,
cost_source, default source, weather null, bookings []).
"""

import copy
import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from app.agent.postprocess import build_itinerary
from app.llm.fake_provider import load_fake_data
from app.schemas.itinerary import Itinerary, ItineraryDraft, itinerary_errors
from app.schemas.profile import TripProfile

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BUDGET_ASSUMPTION = "Budget level assumed (none given)"


# ---- Helpers ----

def load_raw(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_draft(name: str) -> ItineraryDraft:
    return ItineraryDraft.model_validate(load_raw(name))


def v1_draft() -> ItineraryDraft:
    # The San Jose v1 draft is the fake LLM's default reply, kept once in llm/fake_data/.
    return ItineraryDraft.model_validate(load_fake_data("draft_sanjose_v1"))


def budget_profile() -> TripProfile:
    return TripProfile(budget_level="budget")


def build_ok(
    draft: ItineraryDraft,
    previous: list[Itinerary] | None = None,
    profile: TripProfile | None = None,
) -> Itinerary:
    result = build_itinerary(draft, previous or [], profile or budget_profile())
    assert isinstance(result, Itinerary), f"expected an Itinerary, got errors: {result}"
    return result


def all_items(itinerary: Itinerary) -> list[Any]:
    return [item for day in itinerary.days for item in day.items]


def tags_by_day(itinerary: Itinerary) -> list[list[str | None]]:
    return [[item.stop_tag for item in day.items] for day in itinerary.days]


@pytest.fixture
def v1() -> Itinerary:
    return build_ok(v1_draft())


@pytest.fixture
def v2(v1: Itinerary) -> Itinerary:
    return build_ok(load_draft("draft_sanjose_v2.json"), [v1])


# ---- Good draft -> valid itinerary with expected letters ----

def test_v1_is_a_valid_itinerary(v1: Itinerary) -> None:
    assert v1.version == 1
    uuid.UUID(v1.id)  # a real uuid
    assert itinerary_errors(v1) == []
    # Round-trips through the schema (validation runs again).
    Itinerary.model_validate(v1.model_dump(mode="json"))


def test_v1_letters_follow_day_and_time_order(v1: Itinerary) -> None:
    assert tags_by_day(v1) == [
        ["A", "B", "C", "D", "E"],
        ["F", "G", "H", "I"],
        ["J", "K", "C"],  # flying out of the arrival airport again reuses C
    ]


def test_v1_stops_one_per_place_sorted_by_letter(v1: Itinerary) -> None:
    assert [stop.tag for stop in v1.stops] == list("ABCDEFGHIJK")
    names = {stop.tag: stop.name for stop in v1.stops}
    assert names["A"] == "Home"
    assert names["C"] == "San Jose Airport"
    assert names["D"] == "San Jose Marriott"
    assert names["F"] == "Baconhouse"


def test_v1_stops_have_no_tool_data(v1: Itinerary) -> None:
    for stop in v1.stops:
        assert stop.lat is None and stop.lng is None
        assert stop.place_id is None
        assert stop.map_url is None
    for city in v1.cities:
        assert city.lat is None and city.lng is None


def test_v1_item_ids_follow_draft_order(v1: Itinerary) -> None:
    ids = [[item.id for item in day.items] for day in v1.days]
    assert ids == [
        ["d1-i1", "d1-i2", "d1-i3", "d1-i4", "d1-i5"],
        ["d2-i1", "d2-i2", "d2-i3", "d2-i4"],
        ["d3-i1", "d3-i2", "d3-i3"],
    ]


def test_v1_code_owned_fields(v1: Itinerary) -> None:
    assert v1.bookings == []
    assert v1.weather_summary is None
    assert all(day.weather is None for day in v1.days)
    for item in all_items(v1):
        assert item.updated_in_version is None
        assert item.transit_from_previous is None
        assert item.booking_id is None


def test_lodging_points_at_the_hotel_tag(v1: Itinerary) -> None:
    assert len(v1.lodging) == 1
    assert v1.lodging[0].stop_tag == "D"
    assert v1.lodging[0].nights == 2


def test_cost_source_and_default_source(v1: Itinerary) -> None:
    items = {item.id: item for item in all_items(v1)}
    # est_cost given -> ai_estimate; no est_cost -> no cost_source.
    assert items["d1-i2"].est_cost is not None
    assert items["d1-i2"].cost_source == "ai_estimate"
    assert items["d3-i2"].est_cost is not None  # 0 USD still counts as a cost
    assert items["d3-i2"].cost_source == "ai_estimate"
    assert items["d3-i3"].est_cost is None
    assert items["d3-i3"].cost_source is None
    # Code owns the source (contracts §2.3): every item says "AI suggestion" until tools exist.
    assert all(item.source == "AI suggestion" for item in all_items(v1))


def test_llm_written_source_is_ignored() -> None:
    raw = load_fake_data("draft_sanjose_v1")
    raw["days"][0]["items"][0]["source"] = "Official Google rating"
    itinerary = build_ok(ItineraryDraft.model_validate(raw))
    assert itinerary.days[0].items[0].source == "AI suggestion"


def test_draft_fields_are_copied(v1: Itinerary) -> None:
    raw = load_fake_data("draft_sanjose_v1")
    assert v1.title == raw["title"]
    assert v1.summary == raw["summary"]
    assert v1.travelers == raw["travelers"]
    assert [city.name for city in v1.cities] == ["San Jose"]
    assert [day.title for day in v1.days] == [day["title"] for day in raw["days"]]
    first = v1.days[0].items[1]
    raw_first = raw["days"][0]["items"][1]
    assert first.description == raw_first["description"]
    assert first.start_time == raw_first["start_time"]
    assert first.why == raw_first["why"]
    assert first.booking_required is True


def test_same_place_under_two_keys_becomes_one_stop() -> None:
    raw = load_fake_data("draft_sanjose_v1")
    raw["stops"].append(
        {"key": "s99", "name": "san jose airport!", "kind": "airport", "address": None, "place_ref": None}
    )
    raw["days"][2]["items"][2]["stop_key"] = "s99"
    itinerary = build_ok(ItineraryDraft.model_validate(raw))
    assert itinerary.days[2].items[2].stop_tag == "C"
    assert [stop.tag for stop in itinerary.stops].count("C") == 1
    assert itinerary_errors(itinerary) == []


# ---- Budget assumption (D17) ----

def test_budget_assumption_added_when_no_budget_level() -> None:
    result = build_ok(v1_draft(), profile=TripProfile())
    assert result.assumptions[0] == BUDGET_ASSUMPTION
    assert "Rideshare for local trips" in result.assumptions


def test_no_budget_assumption_when_budget_level_given(v1: Itinerary) -> None:
    assert BUDGET_ASSUMPTION not in v1.assumptions
    assert v1.assumptions == ["Rideshare for local trips"]


# ---- v2: versions, kept letters, updated_in_version ----

def test_v2_keeps_plan_id_and_bumps_version(v1: Itinerary, v2: Itinerary) -> None:
    assert v2.version == 2
    assert v2.id == v1.id
    assert itinerary_errors(v2) == []


def test_v2_new_stop_gets_next_letter_and_removed_letter_is_gone(v2: Itinerary) -> None:
    assert tags_by_day(v2) == [
        ["A", "B", "C", "D", "E"],
        ["L", "G", "H", "I"],
        ["J", "K", "C"],
    ]
    tags = [stop.tag for stop in v2.stops]
    assert tags == list("ABCDE") + list("GHIJKL")
    assert "F" not in tags


def test_v2_updated_in_version_only_on_changed_item(v2: Itinerary) -> None:
    updated = {item.id: item.updated_in_version for item in all_items(v2)}
    assert updated.pop("d2-i1") == 2
    assert all(value is None for value in updated.values()), updated


def test_v3_keeps_previous_updated_in_version() -> None:
    # Unchanged since v2 -> keeps 2 (not 3, not null).
    v1 = build_ok(v1_draft())
    v2 = build_ok(load_draft("draft_sanjose_v2.json"), [v1])
    v3 = build_ok(load_draft("draft_sanjose_v2.json"), [v1, v2])
    assert v3.version == 3
    assert v3.id == v1.id
    updated = {item.id: item.updated_in_version for item in all_items(v3)}
    assert updated.pop("d2-i1") == 2
    assert all(value is None for value in updated.values()), updated


def test_updated_in_version_compares_with_previous_version_only() -> None:
    # v3 goes back to the v1 brunch: it differs from v2, so it is marked 3 even though v1 had it.
    v1 = build_ok(v1_draft())
    v2 = build_ok(load_draft("draft_sanjose_v2.json"), [v1])
    v3 = build_ok(v1_draft(), [v1, v2])
    brunch = v3.days[1].items[0]
    assert brunch.stop_tag == "F"  # the old stop keeps its old letter
    assert brunch.updated_in_version == 3


def test_description_change_alone_marks_item_updated(v1: Itinerary) -> None:
    raw = load_fake_data("draft_sanjose_v1")
    raw["days"][1]["items"][2]["description"] = "Self-guided mansion tour."
    v2 = build_ok(ItineraryDraft.model_validate(raw), [v1])
    updated = {item.id: item.updated_in_version for item in all_items(v2)}
    assert updated.pop("d2-i3") == 2
    assert all(value is None for value in updated.values()), updated


def test_previous_versions_order_does_not_matter() -> None:
    v1 = build_ok(v1_draft())
    v2 = build_ok(load_draft("draft_sanjose_v2.json"), [v1])
    v3 = build_ok(load_draft("draft_sanjose_v2.json"), [v2, v1])
    assert v3.version == 3
    assert v3.days[1].items[0].updated_in_version == 2


# ---- Bad drafts -> errors, no exception ----

def test_bad_draft_returns_errors_without_raising() -> None:
    result = build_itinerary(load_draft("draft_bad.json"), [], budget_profile())
    assert isinstance(result, list)
    assert result and all(isinstance(line, str) and line for line in result)
    text = " | ".join(result).lower()
    assert "sorted" in text  # day 1 items out of order
    assert "day_number" in text  # day 2 numbered 3


def test_bad_draft_as_v2_still_returns_errors(v1: Itinerary) -> None:
    result = build_itinerary(load_draft("draft_bad.json"), [v1], budget_profile())
    assert isinstance(result, list) and result


def test_day_count_mismatch_returns_errors() -> None:
    raw = load_fake_data("draft_sanjose_v1")
    raw["end_date"] = "2027-03-08"  # 4 days of dates, 3 days of plan
    result = build_itinerary(ItineraryDraft.model_validate(raw), [], budget_profile())
    assert isinstance(result, list) and result


def test_wrong_day_date_returns_errors() -> None:
    raw = load_fake_data("draft_sanjose_v1")
    raw["days"][1]["date"] = "2027-03-09"
    result = build_itinerary(ItineraryDraft.model_validate(raw), [], budget_profile())
    assert isinstance(result, list) and result


def test_build_does_not_modify_previous_versions(v1: Itinerary) -> None:
    before = copy.deepcopy(v1.model_dump(mode="json"))
    build_ok(load_draft("draft_sanjose_v2.json"), [v1])
    assert v1.model_dump(mode="json") == before
