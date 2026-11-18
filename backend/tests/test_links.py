"""Step 40: deep links + flights as links.

Specified by plan step 40 and contracts §6: `tools/links.py` builds Google Flights, Google
Hotels, Booking.com, tickets and Google Maps links with every parameter URL-encoded and dates as
YYYY-MM-DD; postprocess gives every stop a `map_url` ("name, address" or "name, city") and every
lodging its hotel links (the SerpApi link when present, else a Google Hotels search, plus
Booking.com); flight items get `est_cost: null` ("check link"), and a round-trip Google Flights
link is kept for the bookings (step 42).

All offline: pure functions, the fake draft, mock tool mode for compose.
"""

import asyncio
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from app.agent import pipeline
from app.agent.planner import Finding
from app.agent.postprocess import (
    HotelPrice,
    StopPlace,
    build_itinerary,
    flight_link,
    hotel_source,
    stop_cities,
)
from app.core.config import Settings
from app.llm.fake_provider import FakeProvider, load_fake_data
from app.schemas.itinerary import Itinerary, ItineraryDraft, Money, itinerary_errors
from app.schemas.profile import TripProfile
from app.tools import hotels, links, places

TODAY = date(2027, 2, 1)
START, END = date(2027, 3, 5), date(2027, 3, 7)
SERPAPI_LINK = "https://www.example.com/pacific-inn-san-jose"

PACIFIC = {
    "id": "serpapi:mock_pacific_inn",
    "name": "Pacific Inn San Jose",
    "address": None,
    "lat": 37.3398,
    "lng": -121.881,
    "rating": 3.6,
    "price_per_night": {"amount": 79, "currency": "USD"},
    "total_price": {"amount": 158, "currency": "USD"},
    "price_source": "serpapi_google_hotels",
    "price_as_of": "2026-11-09T01:30:00Z",
    "link": SERPAPI_LINK,
}


@pytest.fixture(autouse=True)
def offline_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    # backend/.env may hold real keys: force mock mode in the tools compose may touch.
    settings = Settings(_env_file=None, llm_provider="fake", tool_provider_mode="mock")
    for module in (places, hotels):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
        monkeypatch.setattr(module, "is_mock", lambda: True)


# --- helpers --------------------------------------------------------------------------------


def _profile(**updates: Any) -> TripProfile:
    fields: dict[str, Any] = dict(
        budget_level="budget", cities=["San Jose, CA"], travelers=1,
        start_date=START, end_date=END, interests=["food"], origin="College Station, TX",
    )
    fields.update(updates)
    return TripProfile(**fields)


def _raw() -> dict[str, Any]:
    return load_fake_data("draft_sanjose_v1")


def _stop(raw: dict[str, Any], key: str) -> dict[str, Any]:
    return next(stop for stop in raw["stops"] if stop["key"] == key)


def _build(
    raw: dict[str, Any] | None = None,
    places_by_key: dict[str, StopPlace] | None = None,
    profile: TripProfile | None = None,
) -> Itinerary:
    plan = build_itinerary(
        ItineraryDraft.model_validate(raw or _raw()), [], profile or _profile(), None,
        places_by_key or {},
    )
    assert isinstance(plan, Itinerary), plan
    assert itinerary_errors(plan) == []
    return plan


def _stop_named(plan: Itinerary, name: str) -> Any:
    return next(stop for stop in plan.stops if stop.name == name)


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)


def _link(lodging: Any, label: str) -> str:
    matches = [link.url for link in lodging.links if link.label == label]
    assert len(matches) == 1, lodging.links
    return matches[0]


# --- links.py: exact formats from contracts §6 ----------------------------------------------


def test_google_flights_url_matches_the_contract_format() -> None:
    url = links.google_flights_url("IAH", "San Jose Airport", START, END)

    assert url == (
        "https://www.google.com/travel/flights?q=Flights%20from%20IAH%20to%20San%20Jose%20Airport"
        "%20on%202027-03-05%20returning%202027-03-07"
    )


def test_google_flights_url_dates_are_zero_padded_iso() -> None:
    url = links.google_flights_url("AUS", "SFO", date(2027, 1, 2), date(2027, 1, 9))

    assert _query(url)["q"] == ["Flights from AUS to SFO on 2027-01-02 returning 2027-01-09"]


def test_google_hotels_url_is_always_a_search() -> None:
    # Step 42: SerpApi's `link` is the hotel's own site, shown separately as "Hotel site".
    expected = "https://www.google.com/travel/hotels?q=Pacific%20Inn%20San%20Jose"

    assert links.google_hotels_url("Pacific Inn", "San Jose") == expected


def test_booking_com_url_matches_the_contract_format() -> None:
    url = links.booking_com_url("San Jose Marriott", "San Jose", START, END, 2)

    assert url == (
        "https://www.booking.com/searchresults.html?ss=San%20Jose%20Marriott%2C%20San%20Jose"
        "&checkin=2027-03-05&checkout=2027-03-07&group_adults=2"
    )


def test_tickets_url_matches_the_contract_format() -> None:
    url = links.tickets_url("The Tech Interactive", "San Jose")

    assert url == "https://www.google.com/search?q=The%20Tech%20Interactive%20San%20Jose%20tickets"


def test_map_url_matches_the_contract_format() -> None:
    url = links.map_url("San Pedro Square", "87 N San Pedro St, San Jose, CA")

    assert url == (
        "https://www.google.com/maps/search/?api=1"
        "&query=San%20Pedro%20Square%2C%2087%20N%20San%20Pedro%20St%2C%20San%20Jose%2C%20CA"
    )


@pytest.mark.parametrize(
    "url",
    [
        links.google_flights_url("A&B / C?", "D=E #F", START, END),
        links.google_hotels_url("Inn & Suites #1", "Q=City/Town?"),
        links.booking_com_url("Inn & Suites #1", "Q=City/Town?", START, END, 1),
        links.tickets_url("Rock & Roll / Hall?", "A=B #C"),
        links.map_url("Rock & Roll / Hall?", "1 Main St #2, A=B"),
    ],
)
def test_special_characters_are_percent_encoded(url: str) -> None:
    query = urlsplit(url).query
    # No raw space, "+", "#", "/" or "?" in the query; "&" and "=" only separate parameters.
    for raw in (" ", "+", "#", "/", "?"):
        assert raw not in query, (raw, url)
    for pair in query.split("&"):
        assert pair.count("=") == 1, (pair, url)
    assert "%26" in query  # the "&" in a value is encoded


def test_encoded_values_round_trip_exactly() -> None:
    name, city = "Café Ñandú & Co / 2nd Floor", "São Paulo, SP"
    url = links.booking_com_url(name, city, START, END, 3)
    query = _query(url)

    assert query["ss"] == [f"{name}, {city}"]
    assert query["checkin"] == ["2027-03-05"]
    assert query["checkout"] == ["2027-03-07"]
    assert query["group_adults"] == ["3"]
    assert _query(links.map_url(name, city))["query"] == [f"{name}, {city}"]
    assert _query(links.tickets_url(name, city))["q"] == [f"{name} {city} tickets"]
    assert _query(links.google_hotels_url(name, city))["q"] == [f"{name} {city}"]


# --- postprocess: map_url on every stop -----------------------------------------------------


def test_every_stop_gets_a_map_url_with_name_and_address() -> None:
    plan = _build()
    raw_stops = {stop["name"]: stop for stop in _raw()["stops"]}

    for stop in plan.stops:
        expected = links.map_url(stop.name, raw_stops[stop.name]["address"])
        assert stop.map_url == expected, stop.name


def test_map_url_uses_the_tool_address_over_the_draft_address() -> None:
    tool_place = StopPlace(lat=37.33, lng=-121.89, address="201 S Market St, San Jose, CA 95113",
                           place_id="geoapify:tech", source="Geoapify")
    plan = _build(places_by_key={"s7": tool_place})

    stop = _stop_named(plan, "The Tech Interactive")
    assert stop.map_url == links.map_url(
        "The Tech Interactive", "201 S Market St, San Jose, CA 95113"
    )


def test_map_url_without_an_address_uses_the_days_city() -> None:
    raw = _raw()
    _stop(raw, "s7")["address"] = None

    plan = _build(raw)

    stop = _stop_named(plan, "The Tech Interactive")
    assert stop.map_url == links.map_url("The Tech Interactive", "San Jose")
    assert _query(stop.map_url)["query"] == ["The Tech Interactive, San Jose"]


def test_home_without_an_address_uses_the_profile_origin() -> None:
    raw = _raw()
    _stop(raw, "s1")["address"] = None

    plan = _build(raw)

    home = next(stop for stop in plan.stops if stop.kind == "home")
    assert _query(home.map_url)["query"] == ["Home, College Station, TX"]


def test_map_url_city_comes_from_the_first_day_with_an_item_there() -> None:
    raw = _raw()
    raw["cities"].append({"name": "Santa Cruz", "region": "CA", "country": "USA"})
    raw["days"][1]["city"] = "Santa Cruz"
    raw["days"][2]["city"] = "Santa Cruz"
    for key in ("s7", "s10"):  # s7 on day 2, s10 on day 3
        _stop(raw, key)["address"] = None

    plan = _build(raw, profile=_profile(cities=["San Jose, CA", "Santa Cruz, CA"]))

    assert _query(_stop_named(plan, "The Tech Interactive").map_url)["query"] == [
        "The Tech Interactive, Santa Cruz"
    ]
    assert _query(_stop_named(plan, "Japantown").map_url)["query"] == ["Japantown, Santa Cruz"]


def test_stop_cities_maps_each_stop_to_its_first_days_city() -> None:
    raw = _raw()
    raw["cities"].append({"name": "Santa Cruz", "region": "CA", "country": "USA"})
    raw["days"][1]["city"] = "Santa Cruz"
    raw["days"][2]["city"] = "Santa Cruz"

    cities = stop_cities(ItineraryDraft.model_validate(raw))

    assert set(cities) == {stop["key"] for stop in raw["stops"]}
    assert cities["s2"] == "San Jose"  # day 1
    assert cities["s3"] == "San Jose"  # day 1 first, though day 3 flies out of it too
    assert cities["s7"] == "Santa Cruz"  # day 2
    assert cities["s11"] == "Santa Cruz"  # day 3


def test_lodging_stop_named_only_by_the_lodging_list_on_day_1_gets_san_jose() -> None:
    raw = _raw()
    _stop(raw, "s4")["address"] = None
    # Drop the hotel's check-in item: only the lodging list names s4 now.
    raw["days"][0]["items"] = [i for i in raw["days"][0]["items"] if i["stop_key"] != "s4"]

    assert stop_cities(ItineraryDraft.model_validate(raw))["s4"] == "San Jose"
    plan = _build(raw)
    hotel = _stop_named(plan, "Pacific Inn San Jose")
    assert _query(hotel.map_url)["query"] == ["Pacific Inn San Jose, San Jose"]
    lodging = plan.lodging[0]
    assert lodging.stop_tag == hotel.tag
    assert _query(_link(lodging, "Google Hotels"))["q"] == ["Pacific Inn San Jose San Jose"]
    assert _query(_link(lodging, "Booking.com"))["ss"] == ["Pacific Inn San Jose, San Jose"]


def _two_city_hostel_draft(check_in: str) -> dict[str, Any]:
    """Days 2–3 in San Francisco; the hotel (renamed, no address) is named only by the lodging
    list, with one night from `check_in`."""
    raw = _raw()
    raw["cities"].append({"name": "San Francisco", "region": "CA", "country": "USA"})
    raw["days"][1]["city"] = "San Francisco"
    raw["days"][2]["city"] = "San Francisco"
    hotel = _stop(raw, "s4")
    hotel["name"], hotel["address"] = "Golden Gate Hostel", None
    raw["days"][0]["items"] = [i for i in raw["days"][0]["items"] if i["stop_key"] != "s4"]
    raw["lodging"][0]["check_in"] = check_in
    raw["lodging"][0]["nights"] = 1
    return raw


def test_lodging_stop_named_only_by_the_lodging_list_gets_its_check_in_days_city() -> None:
    raw = _two_city_hostel_draft("2027-03-06")  # day 2 is in San Francisco

    assert stop_cities(ItineraryDraft.model_validate(raw))["s4"] == "San Francisco"
    plan = _build(raw, profile=_profile(cities=["San Jose, CA", "San Francisco, CA"]))
    hotel = _stop_named(plan, "Golden Gate Hostel")
    assert _query(hotel.map_url)["query"] == ["Golden Gate Hostel, San Francisco"]
    lodging = plan.lodging[0]
    assert lodging.stop_tag == hotel.tag
    booking = _query(_link(lodging, "Booking.com"))
    assert booking["ss"] == ["Golden Gate Hostel, San Francisco"]
    assert (booking["checkin"], booking["checkout"]) == (["2027-03-06"], ["2027-03-07"])
    assert _query(_link(lodging, "Google Hotels"))["q"] == ["Golden Gate Hostel San Francisco"]


def test_lodging_stop_with_a_check_in_on_no_plan_day_falls_back_to_the_first_city() -> None:
    raw = _two_city_hostel_draft("2027-03-04")  # the day before the trip: no matching day

    assert stop_cities(ItineraryDraft.model_validate(raw))["s4"] == "San Jose"


# --- postprocess: lodging links -------------------------------------------------------------


def test_lodging_without_a_tool_hotel_gets_search_links() -> None:
    plan = _build()
    lodging = plan.lodging[0]

    assert [link.label for link in lodging.links] == ["Google Hotels", "Booking.com"]
    assert _link(lodging, "Google Hotels") == links.google_hotels_url(
        "Pacific Inn San Jose", "San Jose"
    )
    assert _link(lodging, "Booking.com") == links.booking_com_url(
        "Pacific Inn San Jose", "San Jose", START, END, 1
    )


def test_lodging_links_use_the_stays_dates_and_the_plans_travelers() -> None:
    raw = _raw()
    raw["travelers"] = 3
    raw["lodging"][0]["check_in"] = "2027-03-06"
    raw["lodging"][0]["nights"] = 1

    plan = _build(raw, profile=_profile(travelers=3))
    query = _query(_link(plan.lodging[0], "Booking.com"))

    assert query["checkin"] == ["2027-03-06"]
    assert query["checkout"] == ["2027-03-07"]
    assert query["group_adults"] == ["3"]


def test_lodging_at_a_found_hotel_adds_the_serpapi_link_as_hotel_site() -> None:
    as_of = datetime(2026, 11, 9, 1, 30, tzinfo=timezone.utc)
    hotel = HotelPrice(Money(amount=79, currency="USD"), "serpapi_google_hotels", as_of,
                       link=SERPAPI_LINK)
    stop_places = {"s4": StopPlace(lat=37.3398, lng=-121.881, place_id="serpapi:x",
                                   source=hotel_source(hotel), hotel=hotel)}

    plan = _build(places_by_key=stop_places)
    lodging = plan.lodging[0]

    assert [link.label for link in lodging.links] == ["Google Hotels", "Booking.com", "Hotel site"]
    assert _link(lodging, "Hotel site") == SERPAPI_LINK
    assert _link(lodging, "Google Hotels") == links.google_hotels_url(
        "Pacific Inn San Jose", "San Jose"
    )
    assert _query(_link(lodging, "Booking.com"))["ss"] == ["Pacific Inn San Jose, San Jose"]


def test_found_hotel_without_a_link_falls_back_to_the_search_url() -> None:
    hotel = HotelPrice(None, "none", link=None)
    stop_places = {"s4": StopPlace(lat=37.33, lng=-121.89, source="Geoapify", hotel=hotel)}

    plan = _build(places_by_key=stop_places)

    assert [link.label for link in plan.lodging[0].links] == ["Google Hotels", "Booking.com"]
    assert _link(plan.lodging[0], "Google Hotels") == links.google_hotels_url(
        "Pacific Inn San Jose", "San Jose"
    )


def _compose(raw: dict[str, Any], findings: list[Finding],
             previous: list[Itinerary] | None = None) -> Itinerary:
    plan = asyncio.run(
        pipeline.compose(
            FakeProvider(drafts=[raw]), _profile(), [], previous or [], TODAY, findings=findings
        )
    )
    assert itinerary_errors(plan) == []
    return plan


def test_hotel_ref_in_compose_gives_the_lodging_the_serpapi_link() -> None:
    raw = _raw()
    _stop(raw, "s4")["place_ref"] = "h1"

    plan = _compose(raw, [Finding(ref="h1", tool="search_hotels", data=dict(PACIFIC))])

    assert _link(plan.lodging[0], "Hotel site") == SERPAPI_LINK


def test_edit_that_keeps_the_hotel_keeps_its_serpapi_link() -> None:
    raw = _raw()
    _stop(raw, "s4")["place_ref"] = "h1"
    v1 = _compose(raw, [Finding(ref="h1", tool="search_hotels", data=dict(PACIFIC))])

    v2 = _compose(pipeline.as_draft(v1).model_dump(mode="json"), [], previous=[v1])

    assert v2.lodging[0].stop_tag == v1.lodging[0].stop_tag
    assert _link(v2.lodging[0], "Hotel site") == SERPAPI_LINK


# --- flights: no price, a Google Flights link -----------------------------------------------


def test_flight_items_have_no_price_whatever_the_draft_said() -> None:
    plan = _build()  # the draft prices the outbound flight at $300
    flights = [item for day in plan.days for item in day.items if item.kind == "flight"]

    assert len(flights) == 2
    for item in flights:
        assert item.est_cost is None
        assert item.cost_source is None


def test_non_flight_items_keep_their_estimate() -> None:
    plan = _build()
    transit = plan.days[0].items[0]

    assert transit.kind == "transit"
    assert transit.est_cost == Money(amount=100, currency="USD")
    assert transit.cost_source == "ai_estimate"


def test_flight_link_for_the_fake_plan_is_a_round_trip_from_the_departure_airport() -> None:
    plan = _build()

    link = flight_link(plan)

    assert link is not None
    assert link.label == "Google Flights"
    assert link.url == links.google_flights_url("IAH", "San Jose Airport", START, END)
    assert _query(link.url)["q"] == [
        "Flights from IAH to San Jose Airport on 2027-03-05 returning 2027-03-07"
    ]


def test_flight_link_without_an_arrival_airport_uses_the_days_city() -> None:
    raw = _raw()
    # No arrival airport stop: the item after the flight goes straight to the hotel.
    raw["days"][0]["items"] = [i for i in raw["days"][0]["items"] if i["stop_key"] != "s3"]
    raw["days"][2]["items"] = [i for i in raw["days"][2]["items"] if i["stop_key"] != "s3"]
    raw["stops"] = [stop for stop in raw["stops"] if stop["key"] != "s3"]

    link = flight_link(_build(raw))

    assert link is not None
    assert _query(link.url)["q"] == [
        "Flights from IAH to San Jose on 2027-03-05 returning 2027-03-07"
    ]


def test_flight_link_is_none_without_a_flight() -> None:
    raw = _raw()
    for day in raw["days"]:
        day["items"] = [i for i in day["items"] if i["kind"] != "flight"]

    assert flight_link(_build(raw)) is None
