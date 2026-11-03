"""agent/postprocess.py v0 (04-backend-design §5.0): ItineraryDraft → valid Itinerary."""

import datetime as dt
import uuid

import pytest

from app.agent.postprocess import _date_range, draft_to_itinerary, maps_search_url
from app.llm.fake_provider import FakeProvider
from app.schemas import Itinerary, ItineraryDraft

CREATED_AT = dt.datetime(2026, 11, 2, 18, 4, 5, tzinfo=dt.UTC)


def build(draft: dict, **kwargs) -> Itinerary:
    return draft_to_itinerary(ItineraryDraft.model_validate(draft), **kwargs)


def item(title: str, start: str, place: str | None = None, **extra) -> dict:
    """A minimal draft item; `place` is a place name (category "sight")."""
    return {
        "kind": "activity", "title": title, "description": "...", "start_time": start, "end_time": start,
        "place": {"name": place, "category": "sight"} if place else None,
    } | extra


# --- the fake fixture -----------------------------------------------------------------------


def test_fake_fixture_becomes_the_austin_itinerary(draft, austin):
    """Tags, IDs, maps links, checklist and Stage 1 nulls all match the hand-checked fixture."""
    itinerary = build(draft, itinerary_id=austin["id"], created_at=CREATED_AT)

    assert itinerary.model_dump(mode="json") == austin


@pytest.mark.asyncio
async def test_fake_provider_draft_runs_through_postprocess():
    provider = FakeProvider(delay=0)  # default fixtures dir: the real app/llm/fixtures

    draft = await provider.generate_json(system="Draft a plan.", messages=[], schema=ItineraryDraft)
    itinerary = draft_to_itinerary(draft)

    assert [p.tag for p in itinerary.places][:3] == ["A", "B", "C"]
    assert [h.tag for h in itinerary.lodging] == ["H1"]


def test_ids_version_and_created_at(draft):
    before = dt.datetime.now(dt.UTC)
    itinerary = build(draft, version=3)

    uuid.UUID(itinerary.id)  # a fresh uuid by default
    assert itinerary.version == 3
    assert itinerary.created_at >= before.replace(microsecond=0)
    assert [i.id for i in itinerary.days[1].items] == [f"d2-i{n}" for n in range(1, 8)]


# --- tags -------------------------------------------------------------------------------------


def test_items_are_sorted_and_tagged_by_start_time(draft):
    draft["days"][0]["items"].reverse()

    itinerary = build(draft)

    day1 = itinerary.days[0].items
    assert [i.start_time for i in day1] == ["08:30", "11:00", "13:00", "15:00", "16:30", "19:15"]
    assert [i.place_tag for i in day1] == [None, "A", "B", "H1", "C", "D"]
    assert itinerary.places[0].name == "Franklin Barbecue"


def test_repeated_place_keeps_its_letter_and_gains_an_address(draft):
    veracruz_day3 = draft["days"][2]["items"][2]["place"]
    veracruz_day3.update(name="veracruz  ALL natural", address="1704 E Cesar Chavez St")

    itinerary = build(draft)

    assert itinerary.days[2].items[2].place_tag == "E"
    assert len(itinerary.places) == 11
    assert itinerary.places[4].name == "Veracruz All Natural"  # first mention's name
    assert itinerary.places[4].address == "1704 E Cesar Chavez St"  # filled from the later mention


def test_letters_continue_with_aa_after_z(draft):
    times = [f"{6 + n // 3:02d}:{n % 3 * 20:02d}" for n in range(28)]  # 06:00, 06:20, ... 15:00
    draft["days"][0]["items"] = [item(f"Stop {n}", t, f"Stop {n}") for n, t in enumerate(times)]

    itinerary = build(draft)

    tags = [p.tag for p in itinerary.places]
    assert tags[:2] == ["A", "B"]
    assert tags[24:28] == ["Y", "Z", "AA", "AB"]
    assert itinerary.days[0].items[27].place_tag == "AB"
    assert itinerary.days[1].items[0].place_tag == "AC"  # Veracruz, the next new place


def test_two_hotels_get_h1_h2_in_check_in_order(draft):
    draft["lodging"] = [
        {"name": "Second Inn", "city": "Austin", "check_in": "2027-03-07", "check_out": "2027-03-08"},
        {"name": "First Inn", "city": "Austin", "check_in": "2027-03-06", "check_out": "2027-03-07"},
    ]
    draft["days"][0]["items"][3]["lodging_ref"] = "first inn"  # matched by normalized name
    draft["days"][2]["items"][0]["lodging_ref"] = "Second Inn"

    itinerary = build(draft)

    assert [(h.tag, h.name, h.nights) for h in itinerary.lodging] == [("H1", "First Inn", 1), ("H2", "Second Inn", 1)]
    assert [d.lodging_tag for d in itinerary.days] == ["H1", "H2", None]  # no hotel on the departure night
    assert itinerary.days[0].items[3].place_tag == "H1"
    assert itinerary.days[2].items[0].place_tag == "H2"
    lodging_checklist = [(c.id, c.title, c.details, c.date) for c in itinerary.checklist if c.category == "lodging"]
    assert lodging_checklist == [
        ("chk-lodging-H1", "Book First Inn (H1)", "1 night, Mar 6–7.", dt.date(2027, 3, 6)),
        ("chk-lodging-H2", "Book Second Inn (H2)", "1 night, Mar 7–8.", dt.date(2027, 3, 7)),
    ]


def test_place_named_like_a_hotel_uses_the_hotel_tag(draft):
    check_in = draft["days"][0]["items"][3]
    check_in["lodging_ref"] = None
    check_in["place"] = {"name": "Hampton Inn & Suites Austin-Downtown/Convention Center", "category": "other"}

    itinerary = build(draft)

    assert itinerary.days[0].items[3].place_tag == "H1"
    assert len(itinerary.places) == 11  # not added as a lettered place


def test_llm_supplied_tags_are_ignored(draft):
    draft["days"][0]["items"][1]["place"]["tag"] = "Q"  # extra keys on nested objects are dropped
    draft["days"][0]["items"][1]["id"] = "x"

    itinerary = build(draft)

    assert itinerary.places[0].tag == "A"
    assert itinerary.days[0].items[1].id == "d1-i2"


# --- checklist --------------------------------------------------------------------------------


def test_each_booking_required_item_gets_a_checklist_item(draft):
    draft["days"][0]["items"][2]["booking_required"] = True  # Capitol tour, d1-i3

    itinerary = build(draft)

    booked = [i for d in itinerary.days for i in d.items if i.booking_required]
    assert [(i.id, i.checklist_item_id) for i in booked] == [
        ("d1-i3", "chk-booking-d1-i3"),
        ("d2-i7", "chk-booking-d2-i7"),
    ]
    chk = {c.id: c for c in itinerary.checklist}
    assert list(chk) == ["chk-lodging-H1", "chk-booking-d1-i3", "chk-booking-d2-i7"]
    capitol = chk["chk-booking-d1-i3"]
    assert (capitol.category, capitol.title, capitol.date) == (
        "activities", "Book Tour the Texas State Capitol", dt.date(2027, 3, 6)
    )
    assert (capitol.links, capitol.bookable_by_us, capitol.status) == ([], False, "todo")


def test_booking_a_hotel_item_links_its_lodging_checklist_item(draft):
    draft["days"][0]["items"][3]["booking_required"] = True  # hotel check-in, d1-i4

    itinerary = build(draft)

    assert itinerary.days[0].items[3].checklist_item_id == "chk-lodging-H1"
    assert [c.id for c in itinerary.checklist] == ["chk-lodging-H1", "chk-booking-d2-i7"]


def test_no_lodging_means_no_hotel_tags(draft):
    draft["lodging"] = []
    for day in draft["days"]:
        day["items"] = [i for i in day["items"] if i["kind"] != "lodging"]

    itinerary = build(draft)

    assert itinerary.lodging == []
    assert [d.lodging_tag for d in itinerary.days] == [None, None, None]
    assert [c.id for c in itinerary.checklist] == ["chk-booking-d2-i7"]


# --- small helpers ----------------------------------------------------------------------------


def test_maps_search_url_encodes_name_and_city():
    assert maps_search_url("Torchy's Tacos", "Austin") == (
        "https://www.google.com/maps/search/?api=1&query=Torchy%27s%20Tacos%20Austin"
    )


def test_date_range_across_months():
    assert _date_range(dt.date(2027, 3, 6), dt.date(2027, 3, 8)) == "Mar 6–8"
    assert _date_range(dt.date(2027, 3, 30), dt.date(2027, 4, 1)) == "Mar 30–Apr 1"
