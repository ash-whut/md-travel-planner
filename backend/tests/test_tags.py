"""Step 19: letter tags (contracts §3).

Specified by plan step 19: v1 order by day/time; the same stop twice -> one tag; a kept stop
keeps its letter in v2; a new stop gets the next letter after the highest used; a removed letter
is never reused; Z -> AA; a place_id match beats a name difference.
"""

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from app.agent.tags import (
    assign_tags,
    index_for_tag,
    normalize_name,
    same_place,
    tag_for_index,
)
from app.schemas.itinerary import Itinerary, ItineraryDraft

FIXTURES = Path(__file__).resolve().parents[2] / "frontend" / "src" / "fixtures"
START = date(2026, 3, 13)


# ---- Helpers ----

def make_draft(
    stops: list[tuple[str, str]],
    days: list[list[tuple[str, str | None]]],
    lodging_key: str | None = None,
) -> ItineraryDraft:
    """stops = [(key, name)], days = [[(start_time, stop_key), ...], ...] in the given order."""
    lodging = []
    if lodging_key is not None:
        lodging.append(
            {
                "stop_key": lodging_key,
                "check_in": START.isoformat(),
                "check_out": (START + timedelta(days=1)).isoformat(),
                "nights": 1,
            }
        )
    return ItineraryDraft.model_validate(
        {
            "title": "Test trip",
            "summary": "A test trip",
            "start_date": START.isoformat(),
            "end_date": (START + timedelta(days=len(days) - 1)).isoformat(),
            "travelers": 1,
            "cities": [{"name": "San Jose"}],
            "stops": [{"key": key, "name": name} for key, name in stops],
            "lodging": lodging,
            "days": [
                {
                    "day_number": index + 1,
                    "date": (START + timedelta(days=index)).isoformat(),
                    "title": f"Day {index + 1}",
                    "city": "San Jose",
                    "items": [
                        {
                            "kind": "activity",
                            "stop_key": stop_key,
                            "description": f"Visit {stop_key}",
                            "start_time": start_time,
                        }
                        for start_time, stop_key in items
                    ],
                }
                for index, items in enumerate(days)
            ],
        }
    )


def make_version(version: int, stops: list[tuple[str, str, str | None]]) -> Itinerary:
    """A minimal valid earlier version. stops = [(tag, name, place_id)]."""
    return Itinerary.model_validate(
        {
            "id": f"it-{version}",
            "version": version,
            "title": "Test trip",
            "summary": "A test trip",
            "start_date": START.isoformat(),
            "end_date": START.isoformat(),
            "travelers": 1,
            "cities": [{"name": "San Jose"}],
            "stops": [
                {"tag": tag, "name": name, "kind": "sight", "place_id": place_id}
                for tag, name, place_id in stops
            ],
            "days": [
                {
                    "day_number": 1,
                    "date": START.isoformat(),
                    "title": "Day 1",
                    "city": "San Jose",
                    "items": [],
                }
            ],
            "created_at": datetime(2026, 3, 1, tzinfo=timezone.utc).isoformat(),
        }
    )


def single_day_draft(names: list[str]) -> ItineraryDraft:
    """One stop per name, visited in list order on day 1."""
    stops = [(f"s{index + 1}", name) for index, name in enumerate(names)]
    items = [(f"{8 + index // 4:02d}:{(index % 4) * 15:02d}", key) for index, (key, _) in enumerate(stops)]
    return make_draft(stops, [items])


def draft_from_fixture(data: dict[str, Any]) -> tuple[ItineraryDraft, dict[str, str]]:
    """Turn a stored itinerary back into a draft (tags -> keys). Returns the draft and key -> tag.

    Stops are listed in reverse so the draft's stop order can't explain the result.
    """
    key_for_tag = {stop["tag"]: f"k{index}" for index, stop in enumerate(data["stops"])}
    stops = [(key_for_tag[stop["tag"]], stop["name"]) for stop in reversed(data["stops"])]
    days = [
        [(item["start_time"], key_for_tag.get(item["stop_tag"])) for item in day["items"]]
        for day in data["days"]
    ]
    draft = make_draft(stops, days, lodging_key=key_for_tag[data["lodging"][0]["stop_tag"]])
    return draft, {key: tag for tag, key in key_for_tag.items()}


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# ---- Letter sequence ----

@pytest.mark.parametrize(
    ("index", "tag"),
    [(0, "A"), (1, "B"), (25, "Z"), (26, "AA"), (27, "AB"), (51, "AZ"), (52, "BA"), (701, "ZZ"), (702, "AAA")],
)
def test_letter_sequence(index: int, tag: str) -> None:
    assert tag_for_index(index) == tag
    assert index_for_tag(tag) == index


def test_letter_sequence_round_trips() -> None:
    for index in range(1000):
        assert index_for_tag(tag_for_index(index)) == index


# ---- Name normalization / matching ----

def test_normalize_name_ignores_case_punctuation_and_spaces() -> None:
    assert normalize_name("  St. Mary's   Church ") == "st marys church"
    assert normalize_name("SAN JOSE AIRPORT") == normalize_name("San Jose Airport.")


def test_same_place_by_name_when_place_id_missing() -> None:
    assert same_place("San Pedro Square", None, "san pedro  square!", None)
    assert same_place("San Pedro Square", "geo:1", "san pedro square", None)
    assert not same_place("San Pedro Square", None, "Santana Row", None)


def test_same_place_by_place_id_beats_name_difference() -> None:
    assert same_place("SJC", "geo:sjc", "Norman Y. Mineta San Jose International Airport", "geo:sjc")


# ---- Version 1 ----

def test_v1_order_follows_days_and_start_times_not_draft_order() -> None:
    # Stops listed backwards, days listed backwards and items within a day unsorted.
    stops = [("s5", "Five"), ("s4", "Four"), ("s3", "Three"), ("s2", "Two"), ("s1", "One")]
    draft = ItineraryDraft.model_validate(
        {
            **make_draft(stops, [[("09:00", "s1")], [("09:00", "s4")]]).model_dump(mode="json"),
            "end_date": (START + timedelta(days=1)).isoformat(),
            "days": [
                {
                    "day_number": 2,
                    "date": (START + timedelta(days=1)).isoformat(),
                    "title": "Day 2",
                    "city": "San Jose",
                    "items": [
                        {"kind": "activity", "stop_key": "s5", "description": "x", "start_time": "15:00"},
                        {"kind": "activity", "stop_key": "s4", "description": "x", "start_time": "09:00"},
                    ],
                },
                {
                    "day_number": 1,
                    "date": START.isoformat(),
                    "title": "Day 1",
                    "city": "San Jose",
                    "items": [
                        {"kind": "activity", "stop_key": "s3", "description": "x", "start_time": "18:00"},
                        {"kind": "activity", "stop_key": "s1", "description": "x", "start_time": "07:30"},
                        {"kind": "activity", "stop_key": "s2", "description": "x", "start_time": "12:00"},
                    ],
                },
            ],
        }
    )

    assert assign_tags(draft, []) == {"s1": "A", "s2": "B", "s3": "C", "s4": "D", "s5": "E"}


def test_v1_matches_the_san_jose_fixture() -> None:
    data = load_fixture("sanjose-v1.json")
    draft, expected = draft_from_fixture(data)

    assert assign_tags(draft, []) == expected


def test_every_stop_gets_a_tag_including_unreferenced_lodging() -> None:
    draft = make_draft(
        [("s1", "Museum"), ("hotel", "Hotel"), ("s2", "Park")],
        [[("09:00", "s1"), ("11:00", "s2")]],
        lodging_key="hotel",
    )

    tags = assign_tags(draft, [])

    assert set(tags) == {"s1", "hotel", "s2"}
    assert tags["s1"] == "A" and tags["s2"] == "B"
    assert tags["hotel"] == "C"


def test_same_stop_twice_gets_one_tag() -> None:
    # One key used twice, and a second key whose name only differs by case/punctuation.
    draft = make_draft(
        [("s1", "San Jose Airport"), ("s2", "Hotel"), ("s3", "san jose airport.")],
        [[("09:00", "s1"), ("12:00", "s2")], [("08:00", "s2"), ("14:00", "s1"), ("15:00", "s3")]],
    )

    tags = assign_tags(draft, [])

    assert tags == {"s1": "A", "s2": "B", "s3": "A"}


def test_same_place_id_in_one_draft_gets_one_tag() -> None:
    draft = single_day_draft(["SJC", "Hotel", "Mineta San Jose Airport"])

    tags = assign_tags(draft, [], place_ids={"s1": "geo:sjc", "s3": "geo:sjc"})

    assert tags == {"s1": "A", "s2": "B", "s3": "A"}


def test_v1_past_z_continues_with_aa() -> None:
    draft = single_day_draft([f"Place {index}" for index in range(28)])

    tags = assign_tags(draft, [])

    assert tags["s1"] == "A"
    assert tags["s26"] == "Z"
    assert tags["s27"] == "AA"
    assert tags["s28"] == "AB"


# ---- Version N > 1 ----

def test_kept_stop_keeps_its_letter_in_v2() -> None:
    v1 = make_version(1, [("A", "Home", None), ("B", "Museum", None), ("C", "Park", None)])
    # v2 visits the same places in a different order and renamed by case only.
    draft = single_day_draft(["park", "Home", "MUSEUM"])

    assert assign_tags(draft, [v1]) == {"s1": "C", "s2": "A", "s3": "B"}


def test_v2_matches_the_san_jose_fixture() -> None:
    v1 = Itinerary.model_validate(load_fixture("sanjose-v1.json"))
    data = load_fixture("sanjose-v2.json")
    draft, expected = draft_from_fixture(data)

    tags = assign_tags(draft, [v1])

    assert tags == expected
    assert "F" not in tags.values()  # Baconhouse was replaced; its letter stays retired
    assert "L" in tags.values()


def test_new_stop_gets_next_letter_after_highest_used() -> None:
    v1 = make_version(1, [("A", "Home", None), ("B", "Museum", None), ("C", "Park", None)])
    draft = single_day_draft(["Home", "Cafe", "Museum"])

    assert assign_tags(draft, [v1]) == {"s1": "A", "s2": "D", "s3": "B"}


def test_highest_letter_counts_across_all_versions() -> None:
    v1 = make_version(1, [("A", "Home", None), ("B", "Museum", None), ("C", "Park", None), ("D", "Zoo", None)])
    v2 = make_version(2, [("A", "Home", None), ("B", "Museum", None)])  # C and D removed
    draft = single_day_draft(["Home", "Beach"])

    assert assign_tags(draft, [v1, v2]) == {"s1": "A", "s2": "E"}


def test_removed_letter_is_never_reused() -> None:
    v1 = make_version(1, [("A", "Home", None), ("B", "Museum", None), ("C", "Park", None)])
    v2 = make_version(2, [("A", "Home", None), ("B", "Museum", None), ("D", "Cafe", None)])
    v3 = make_version(3, [("A", "Home", None), ("B", "Museum", None)])
    draft = single_day_draft(["Home", "Museum", "Beach", "Bar"])

    tags = assign_tags(draft, [v1, v2, v3])

    assert tags == {"s1": "A", "s2": "B", "s3": "E", "s4": "F"}
    assert "C" not in tags.values() and "D" not in tags.values()


def test_previous_versions_order_does_not_matter() -> None:
    v1 = make_version(1, [("A", "Home", None), ("B", "Museum", None), ("C", "Park", None)])
    v2 = make_version(2, [("A", "Home", None), ("D", "Cafe", None)])
    draft = single_day_draft(["Home", "Beach"])

    assert assign_tags(draft, [v2, v1]) == assign_tags(draft, [v1, v2]) == {"s1": "A", "s2": "E"}


def test_stop_from_any_earlier_version_gets_its_old_letter_back() -> None:
    v1 = make_version(1, [("A", "Home", None), ("B", "Museum", None), ("C", "Park", None)])
    v2 = make_version(2, [("A", "Home", None), ("B", "Museum", None)])  # Park dropped
    draft = single_day_draft(["Home", "Park"])

    assert assign_tags(draft, [v1, v2]) == {"s1": "A", "s2": "C"}


def test_new_stop_after_z_gets_aa() -> None:
    previous = [(tag_for_index(index), f"Place {index}", None) for index in range(26)]  # A..Z
    v1 = make_version(1, previous)
    draft = single_day_draft(["Place 0", "Brand new place"])

    assert assign_tags(draft, [v1]) == {"s1": "A", "s2": "AA"}


def test_place_id_match_beats_name_difference() -> None:
    v1 = make_version(
        1,
        [("A", "Home", None), ("B", "SJC", "geo:sjc"), ("C", "San Pedro Square", "geo:sps")],
    )
    draft = single_day_draft(["Home", "Norman Y. Mineta San Jose International Airport", "Cafe"])

    tags = assign_tags(draft, [v1], place_ids={"s2": "geo:sjc", "s3": "geo:cafe"})

    assert tags == {"s1": "A", "s2": "B", "s3": "D"}
