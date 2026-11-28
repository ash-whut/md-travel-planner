"""Step 51: vacation rentals next to hotels.

Specified by plan step 51, contracts §2.2/§2.3/§6 and D34: `hotels.search` makes a second
SerpApi call with `vacation_rentals=true` (own "rentals" cache, 6 h), keeps well-rated rentals
(≤ 3) and appends them after the hotels. Each result has `type` and `details`; a rental has no
`link`. A failed rentals call (error, quota) leaves the hotels alone and `ok: true`. A stop
citing a rental gets `lodging.type: "vacation_rental"`, a Google Hotels + Airbnb search link (no
Booking.com, no Hotel site), the source "SerpApi Google Hotels (vacation rental) · as of …" and
a "Rental Booking" booking. The offline fake plan can show a rental.

All offline: httpx MockTransport with a patched `get_settings` for live mode, mock tool mode
otherwise, the fake LLM, a temp DB (conftest).
"""

import asyncio
import copy
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
import pytest
from sqlmodel import Session

from app.agent import pipeline
from app.agent.planner import Finding
from app.agent.postprocess import HotelPrice, StopPlace, build_itinerary, hotel_source
from app.core.config import Settings
from app.db import repo
from app.db.tables import utcnow
from app.llm.base import Message
from app.llm.fake_provider import FakeProvider, load_fake_data
from app.schemas.itinerary import Itinerary, ItineraryDraft, Lodging, Money, itinerary_errors
from app.schemas.profile import TripProfile
from app.tools import hotels, links, places, registry
from app.tools.common import HOTELS_TTL_SECONDS, cache_get, load_mock

Handler = Callable[[httpx.Request], httpx.Response]
KEY = "test-serpapi-key"
CHECK_IN, CHECK_OUT = "2027-03-05", "2027-03-07"
TODAY = date(2027, 2, 1)
START, END = date(2027, 3, 5), date(2027, 3, 7)
AS_OF = "2026-11-09T01:30:00Z"
RESULT_KEYS = {
    "id", "type", "name", "details", "address", "lat", "lng", "rating", "price_per_night",
    "total_price", "price_source", "price_as_of", "link",
}
CACHE_ARGS = {"city": "san jose, ca", "check_in": CHECK_IN, "check_out": CHECK_OUT}


# --- helpers --------------------------------------------------------------------------------


def prop(name: str, rating: Any = 4.0, nightly: Any = 100, total: Any = 200,
         token: str | None = "tok", **extra: Any) -> dict[str, Any]:
    """One SerpApi `properties` entry (hotel or rental)."""
    entry: dict[str, Any] = {
        "name": name,
        "overall_rating": rating,
        "rate_per_night": {"lowest": f"${nightly}", "extracted_lowest": nightly},
        "total_rate": {"lowest": f"${total}", "extracted_lowest": total},
        "gps_coordinates": {"latitude": 37.32, "longitude": -121.88},
        "link": "https://example.com/" + name.replace(" ", "-").lower(),
        **extra,
    }
    if token is not None:
        entry["property_token"] = token
    return entry


def rental_prop(name: str = "Cozy Loft", **kwargs: Any) -> dict[str, Any]:
    return prop(name, essential_info=["Entire apartment", "Sleeps 4", "1 bedroom"], **kwargs)


def ok(properties: list[dict[str, Any]]) -> Handler:
    return lambda request: httpx.Response(200, json={"properties": properties})


class Live:
    """Hotels in live mode over a fake transport: the hotels call goes to `hotels_handler`,
    the `vacation_rentals=true` call to `rentals_handler`; requests are logged per kind."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, hotels_handler: Handler,
                 rentals_handler: Handler, key: str = KEY) -> None:
        settings = Settings(_env_file=None, tool_provider_mode="live", serpapi_key=key)
        monkeypatch.setattr(hotels, "get_settings", lambda: settings)
        monkeypatch.setattr(hotels, "is_mock", lambda: False)
        self.hotel_requests: list[httpx.Request] = []
        self.rental_requests: list[httpx.Request] = []

        def route(request: httpx.Request) -> httpx.Response:
            if request.url.params.get("vacation_rentals") == "true":
                self.rental_requests.append(request)
                return rentals_handler(request)
            self.hotel_requests.append(request)
            return hotels_handler(request)

        self.client = httpx.Client(transport=httpx.MockTransport(route))

    def search(self, city: str = "San Jose, CA", **kwargs: Any) -> Any:
        return hotels.search(city, CHECK_IN, CHECK_OUT, client=self.client, **kwargs)


def names(results: list[dict[str, Any]]) -> list[str]:
    return [r["name"] for r in results]


def types(results: list[dict[str, Any]]) -> list[str]:
    return [r["type"] for r in results]


# --- normalization --------------------------------------------------------------------------


def test_normalize_rental_type_details_prices_and_no_link() -> None:
    rental = hotels.normalize_rental(rental_prop(nightly=74, total=147, token="tok_r"), AS_OF)

    assert set(rental) == RESULT_KEYS
    assert rental["type"] == "vacation_rental"
    assert rental["details"] == "Entire apartment, Sleeps 4, 1 bedroom"
    assert rental["link"] is None  # SerpApi's link is dropped for rentals
    assert rental["id"] == "serpapi:tok_r"
    assert rental["name"] == "Cozy Loft"
    assert rental["price_per_night"] == {"amount": 74, "currency": "USD"}
    assert rental["total_price"] == {"amount": 147, "currency": "USD"}
    assert rental["price_source"] == "serpapi_google_hotels"
    assert rental["price_as_of"] == AS_OF
    assert (rental["lat"], rental["lng"]) == (37.32, -121.88)


def test_normalize_rental_without_essential_info_has_null_details() -> None:
    assert hotels.normalize_rental(prop("Bare Rental"), AS_OF)["details"] is None
    assert hotels.normalize_rental(prop("Empty", essential_info=[]), AS_OF)["details"] is None


def test_normalized_hotel_is_type_hotel_with_null_details() -> None:
    hotel = hotels.normalize_hotel(prop("Hotel A"), AS_OF)

    assert hotel["type"] == "hotel"
    assert hotel["details"] is None
    assert hotel["link"] == "https://example.com/hotel-a"


def test_normalize_rentals_uses_the_rating_filter_and_keeps_at_most_three() -> None:
    props = [
        rental_prop("Bad", rating=2.6, nightly=50),
        rental_prop("R1", rating=4.5, nightly=60),
        rental_prop("Unrated", rating=None, nightly=65),
        rental_prop("R2", rating=3.5, nightly=70),
        rental_prop("R3", rating=4.0, nightly=80),
        rental_prop("R4", rating=4.9, nightly=90),
    ]

    result = hotels.normalize_rentals(props, AS_OF)

    assert names(result) == ["R1", "R2", "R3"]
    assert set(types(result)) == {"vacation_rental"}


# --- live mode: two calls, merged ----------------------------------------------------------


def test_live_search_makes_a_second_vacation_rentals_call(monkeypatch: pytest.MonkeyPatch) -> None:
    live = Live(monkeypatch, ok([prop("Hotel A")]), ok([rental_prop()]))

    assert live.search().ok
    assert len(live.hotel_requests) == 1
    assert len(live.rental_requests) == 1
    hotel_params = live.hotel_requests[0].url.params
    rental_params = live.rental_requests[0].url.params
    assert "vacation_rentals" not in hotel_params
    assert rental_params["engine"] == "google_hotels"
    assert rental_params["q"] == "San Jose, CA"
    assert rental_params["check_in_date"] == CHECK_IN
    assert rental_params["check_out_date"] == CHECK_OUT


def test_merged_order_is_hotels_first_then_at_most_three_rentals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hotel_props = [prop("H1", nightly=80), prop("H2", nightly=90)]
    rental_props = [rental_prop(f"R{i}", nightly=50 + i) for i in range(5)]
    live = Live(monkeypatch, ok(hotel_props), ok(rental_props))

    result = live.search()

    assert result.ok, result.error
    assert names(result.data) == ["H1", "H2", "R0", "R1", "R2"]
    assert types(result.data) == ["hotel", "hotel"] + ["vacation_rental"] * 3
    assert all(set(r) == RESULT_KEYS for r in result.data)
    assert all(r["link"] is None for r in result.data[2:])


def test_rentals_use_the_rating_filter_in_live_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    rental_props = [rental_prop("Poor", rating=2.0, nightly=40), rental_prop("Good", rating=4.2)]
    live = Live(monkeypatch, ok([prop("H1")]), ok(rental_props))

    assert names(live.search().data) == ["H1", "Good"]


def test_no_rentals_found_gives_hotels_only(monkeypatch: pytest.MonkeyPatch) -> None:
    live = Live(monkeypatch, ok([prop("H1")]), ok([]))

    result = live.search()

    assert result.ok and names(result.data) == ["H1"]


# --- the rentals cache ----------------------------------------------------------------------


def test_rentals_cache_prevents_a_second_call(monkeypatch: pytest.MonkeyPatch) -> None:
    live = Live(monkeypatch, ok([prop("H1")]), ok([rental_prop()]))

    first = live.search()
    second = live.search(city="  san jose, ca ")

    assert first.ok and second.ok
    assert len(live.rental_requests) == 1
    assert len(live.hotel_requests) == 1
    assert second.data == first.data


def test_rentals_have_their_own_cache_key(monkeypatch: pytest.MonkeyPatch) -> None:
    live = Live(monkeypatch, ok([prop("H1")]), ok([rental_prop("R1")]))
    live.search()

    cached_rentals = cache_get("rentals", CACHE_ARGS)
    cached_hotels = cache_get("hotels", CACHE_ARGS)
    assert cached_rentals is not None and names(cached_rentals) == ["R1"]
    assert cached_hotels is not None and names(cached_hotels) == ["H1"]


def test_rentals_cache_lasts_six_hours(monkeypatch: pytest.MonkeyPatch) -> None:
    live = Live(monkeypatch, ok([prop("H1")]), ok([rental_prop()]))
    live.search()

    later = utcnow() + timedelta(hours=5, minutes=59)
    expired = utcnow() + timedelta(hours=6, minutes=1)
    assert HOTELS_TTL_SECONDS == 6 * 60 * 60
    assert cache_get("rentals", CACHE_ARGS, now=later) is not None
    assert cache_get("rentals", CACHE_ARGS, now=expired) is None


def test_cached_hotels_with_uncached_rentals_only_calls_rentals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The first rentals call fails (not cached); the next search reuses the cached hotels and
    # asks for the rentals again.
    responses = iter([httpx.Response(500), httpx.Response(200, json={"properties": [rental_prop()]})])
    live = Live(monkeypatch, ok([prop("H1")]), lambda request: next(responses))

    assert names(live.search().data) == ["H1"]
    again = live.search()

    assert len(live.hotel_requests) == 1
    assert len(live.rental_requests) == 2
    assert types(again.data) == ["hotel", "vacation_rental"]


# --- a failed rentals call never breaks the tool --------------------------------------------


def _down(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("no route", request=request)


@pytest.mark.parametrize(
    "rentals_handler",
    [
        lambda request: httpx.Response(500, json={"error": "boom"}),
        lambda request: httpx.Response(429, json={"error": "limit"}),
        lambda request: httpx.Response(200, json={"error": "Your account has run out of searches."}),
        lambda request: httpx.Response(200, json={"error": "Invalid API key."}),
        lambda request: httpx.Response(200, text="<html>oops"),
        lambda request: httpx.Response(200, json={"properties": 5}),
        _down,
    ],
    ids=["http-500", "quota-429", "quota-message", "error-message", "non-json", "malformed",
         "network"],
)
def test_rentals_failure_returns_hotels_only_and_ok(
    monkeypatch: pytest.MonkeyPatch, rentals_handler: Handler
) -> None:
    live = Live(monkeypatch, ok([prop("H1"), prop("H2", nightly=120)]), rentals_handler)

    result = live.search()

    assert result.ok is True, result.error
    assert names(result.data) == ["H1", "H2"]
    assert types(result.data) == ["hotel", "hotel"]
    assert result.data[0]["price_source"] == "serpapi_google_hotels"


def test_rentals_failure_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    live = Live(monkeypatch, ok([prop("H1")]), lambda request: httpx.Response(429))
    live.search()

    assert cache_get("rentals", CACHE_ARGS) is None


# --- the hotel error and fallback paths stay as they are -----------------------------------


def test_hotels_error_is_still_ok_false_even_with_rentals(monkeypatch: pytest.MonkeyPatch) -> None:
    live = Live(monkeypatch, lambda request: httpx.Response(500), ok([rental_prop()]))

    result = live.search()

    assert result.ok is False
    assert KEY not in (result.error or "")


def test_hotels_quota_falls_back_without_rentals(monkeypatch: pytest.MonkeyPatch) -> None:
    live = Live(monkeypatch, lambda request: httpx.Response(429), ok([rental_prop()]))

    result = live.search()

    assert result.ok, result.error
    assert result.data
    assert all(r["price_source"] == "none" for r in result.data)
    assert all(r["type"] == "hotel" for r in result.data)


def test_no_key_fallback_has_no_rentals(monkeypatch: pytest.MonkeyPatch) -> None:
    live = Live(monkeypatch, ok([prop("H1")]), ok([rental_prop()]), key="")

    result = live.search()

    assert result.ok, result.error
    assert result.data
    assert live.rental_requests == [] and live.hotel_requests == []
    for entry in result.data:
        assert set(entry) == RESULT_KEYS
        assert entry["type"] == "hotel" and entry["details"] is None


# --- mock mode ------------------------------------------------------------------------------


def test_mock_mode_returns_hotels_then_rentals() -> None:
    result = hotels.search("San Jose, CA", CHECK_IN, CHECK_OUT)
    assert result.ok, result.error

    kinds = types(result.data)
    assert "hotel" in kinds and "vacation_rental" in kinds
    first_rental = kinds.index("vacation_rental")
    assert all(kind == "hotel" for kind in kinds[:first_rental])
    assert all(kind == "vacation_rental" for kind in kinds[first_rental:])
    rentals = result.data[first_rental:]
    assert 1 <= len(rentals) <= 3
    for rental in rentals:
        assert set(rental) == RESULT_KEYS
        assert rental["link"] is None
        assert rental["details"]
        assert rental["rating"] is not None and rental["rating"] >= 3.5
        assert rental["price_per_night"]["currency"] == "USD"
        assert rental["price_source"] == "serpapi_google_hotels"


def test_mock_rentals_come_from_the_recording() -> None:
    recorded = load_mock("rentals_search")["properties"]
    result = hotels.search("Austin, TX", CHECK_IN, CHECK_OUT)  # any city

    rentals = [r for r in result.data if r["type"] == "vacation_rental"]
    by_name = {p["name"]: p for p in recorded}
    for rental in rentals:
        source = by_name[rental["name"]]
        assert rental["details"] == ", ".join(source["essential_info"])
        assert rental["price_per_night"]["amount"] == source["rate_per_night"]["extracted_lowest"]
    assert "Charming 1-bedroom house in superb San Jose with AC, WiFi" not in names(rentals)  # 2.6


def test_registry_description_mentions_vacation_rentals() -> None:
    assert "vacation rental" in registry.TOOLS["search_hotels"].description.lower()


def test_run_tool_search_hotels_returns_both_kinds_in_mock_mode() -> None:
    args = {"city": "San Jose, CA", "check_in": CHECK_IN, "check_out": CHECK_OUT}
    result = registry.run_tool("search_hotels", args, registry.PlanLimits())

    assert result.ok, result.error
    assert {"hotel", "vacation_rental"} <= set(types(result.data))


# --- Airbnb link ----------------------------------------------------------------------------


def test_airbnb_search_url_for_city_and_dates() -> None:
    url = links.airbnb_search_url("San Jose, CA", date(2027, 3, 5), date(2027, 3, 7), 3)
    parts = urlsplit(url)

    assert url.startswith("https://www.airbnb.com/s/")
    assert parts.path.endswith("/homes")
    assert unquote(parts.path.split("/")[2]) == "San Jose, CA"
    assert " " not in url
    assert parse_qs(parts.query) == {
        "checkin": ["2027-03-05"], "checkout": ["2027-03-07"], "adults": ["3"],
    }


# --- the plan: a cited rental ---------------------------------------------------------------


RENTAL = hotels.normalize_rental(
    {
        "name": "Oversize Loft w/ Kitchenette",
        "property_token": "mock_loft",
        "gps_coordinates": {"latitude": 37.3171, "longitude": -121.8929},
        "overall_rating": 4.5,
        "rate_per_night": {"extracted_lowest": 74},
        "total_rate": {"extracted_lowest": 999},
        "essential_info": ["Entire house", "Sleeps 4"],
        "link": "https://booking.example.com/loft",
    },
    AS_OF,
)
HOTEL = hotels.normalize_hotel(
    {
        "name": "Pacific Inn San Jose",
        "property_token": "mock_pacific_inn",
        "gps_coordinates": {"latitude": 37.3398, "longitude": -121.881},
        "overall_rating": 3.6,
        "rate_per_night": {"extracted_lowest": 79},
        "total_rate": {"extracted_lowest": 158},
        "link": "https://www.example.com/pacific-inn-san-jose",
    },
    AS_OF,
)
RENTAL_SOURCE = "SerpApi Google Hotels (vacation rental) · as of Nov 9, 1:30 AM UTC"


@pytest.fixture
def offline_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    # backend/.env may hold real GEOAPIFY / SERPAPI keys: force mock mode in both tools.
    settings = Settings(_env_file=None, llm_provider="fake", tool_provider_mode="mock")
    for module in (places, hotels):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
        monkeypatch.setattr(module, "is_mock", lambda: True)


def _profile(travelers: int = 1) -> TripProfile:
    return TripProfile(
        budget_level="budget", cities=["San Jose, CA"], travelers=travelers,
        start_date=START, end_date=END, interests=["food"], origin="College Station, TX",
    )


def _raw_v1(hotel_ref: str | None = None) -> dict[str, Any]:
    """The fake v1 draft; its lodging stop is s4."""
    raw = copy.deepcopy(load_fake_data("draft_sanjose_v1"))
    if hotel_ref is not None:
        next(stop for stop in raw["stops"] if stop["key"] == "s4")["place_ref"] = hotel_ref
    return raw


def _compose(raw: dict[str, Any], findings: list[Finding],
             previous: list[Itinerary] | None = None, travelers: int = 1) -> Itinerary:
    plan = asyncio.run(
        pipeline.compose(
            FakeProvider(drafts=[raw]), _profile(travelers), [], previous or [], TODAY,
            findings=findings,
        )
    )
    assert isinstance(plan, Itinerary), plan
    assert itinerary_errors(plan) == []
    return plan


def _found(ref: str, data: dict[str, Any]) -> Finding:
    return Finding(ref=ref, tool="search_hotels", data=dict(data))


def _lodging_stop(plan: Itinerary) -> Any:
    return next(stop for stop in plan.stops if stop.kind == "lodging")


def _lodging_item(plan: Itinerary) -> Any:
    return next(item for day in plan.days for item in day.items if item.kind == "lodging")


def _usd(amount: float) -> Money:
    return Money(amount=amount, currency="USD")


def test_cited_rental_gives_a_vacation_rental_lodging(offline_tools: None) -> None:
    plan = _compose(_raw_v1("h2"), [_found("h1", HOTEL), _found("h2", RENTAL)])
    lodging = plan.lodging[0]
    stop = _lodging_stop(plan)
    item = _lodging_item(plan)

    assert lodging.type == "vacation_rental"
    assert lodging.stop_tag == stop.tag
    assert stop.place_id == "serpapi:mock_loft"
    assert (stop.lat, stop.lng) == (37.3171, -121.8929)
    # Prices still follow D30: per night × nights, not the tool's total.
    assert lodging.price_per_night == _usd(74)
    assert lodging.total_price == _usd(148)
    assert lodging.price_source == "serpapi_google_hotels"
    assert lodging.price_as_of == datetime(2026, 11, 9, 1, 30, tzinfo=timezone.utc)
    assert (item.est_cost, item.cost_source, item.nights) == (_usd(74), "tool", 2)
    assert item.source == RENTAL_SOURCE


def test_cited_rental_links_are_google_hotels_and_airbnb_without_booking_com(
    offline_tools: None,
) -> None:
    raw = _raw_v1("h1")
    raw["travelers"] = 3  # adults come from the plan's travelers, like Booking.com's
    city = raw["cities"][0]["name"]
    plan = _compose(raw, [_found("h1", RENTAL)], travelers=3)
    lodging_links = plan.lodging[0].links

    assert [link.label for link in lodging_links] == ["Google Hotels", "Airbnb"]
    assert all("booking.com" not in link.url for link in lodging_links)
    assert all("booking.example.com" not in link.url for link in lodging_links)  # no Hotel site
    assert lodging_links[0].url.startswith("https://www.google.com/travel/hotels?")
    airbnb = lodging_links[1].url
    assert airbnb == links.airbnb_search_url(city, START, END, 3)
    assert airbnb.startswith("https://www.airbnb.com/s/")
    assert parse_qs(urlsplit(airbnb).query) == {
        "checkin": ["2027-03-05"], "checkout": ["2027-03-07"], "adults": ["3"],
    }


def test_cited_hotel_stays_a_hotel_with_its_links(offline_tools: None) -> None:
    plan = _compose(_raw_v1("h1"), [_found("h1", HOTEL), _found("h2", RENTAL)])
    lodging = plan.lodging[0]

    assert lodging.type == "hotel"
    assert [link.label for link in lodging.links] == ["Google Hotels", "Booking.com", "Hotel site"]
    assert _lodging_item(plan).source.startswith("SerpApi Google Hotels · as of ")


def test_lodging_without_a_ref_is_a_hotel(offline_tools: None) -> None:
    plan = _compose(_raw_v1(None), [_found("h1", RENTAL)])

    assert plan.lodging[0].type == "hotel"
    assert [link.label for link in plan.lodging[0].links] == ["Google Hotels", "Booking.com"]


def test_rental_booking_title_and_id(offline_tools: None) -> None:
    plan = _compose(_raw_v1("h1"), [_found("h1", RENTAL)])
    tag = _lodging_stop(plan).tag
    booking = next(b for b in plan.bookings if b.kind == "lodging")

    assert booking.id == f"bk-hotel-{tag}"
    assert booking.title == "Rental Booking"
    assert booking.estimate == _usd(148)
    assert booking.links == plan.lodging[0].links
    assert _lodging_item(plan).booking_id == booking.id


def test_hotel_booking_title_is_unchanged(offline_tools: None) -> None:
    plan = _compose(_raw_v1("h1"), [_found("h1", HOTEL)])
    booking = next(b for b in plan.bookings if b.kind == "lodging")

    assert booking.title == "Hotel Booking"


def test_build_itinerary_with_a_rental_price_sets_type_and_source() -> None:
    as_of = datetime(2026, 11, 9, 1, 30, tzinfo=timezone.utc)
    rental = HotelPrice(_usd(74), "serpapi_google_hotels", as_of, link=None, from_serpapi=True,
                        lodging_type="vacation_rental")
    stop_places = {"s4": StopPlace(lat=37.3171, lng=-121.8929, place_id="serpapi:x",
                                   source=hotel_source(rental), hotel=rental)}

    plan = build_itinerary(
        ItineraryDraft.model_validate(_raw_v1()), [], _profile(), None, stop_places
    )

    assert isinstance(plan, Itinerary), plan
    assert plan.lodging[0].type == "vacation_rental"
    assert hotel_source(rental) == RENTAL_SOURCE
    assert next(b for b in plan.bookings if b.kind == "lodging").title == "Rental Booking"


def test_rental_without_price_has_the_plain_rental_source() -> None:
    rental = HotelPrice(None, "none", from_serpapi=True, lodging_type="vacation_rental")

    assert hotel_source(rental) == "SerpApi Google Hotels (vacation rental)"


def test_edit_that_keeps_the_rental_keeps_its_type(offline_tools: None) -> None:
    v1 = _compose(_raw_v1("h1"), [_found("h1", RENTAL)])

    # An edit copies stops by letter with no refs and gets no new hotel findings.
    v2 = _compose(pipeline.as_draft(v1).model_dump(mode="json"), [], previous=[v1])

    assert v2.lodging[0].type == "vacation_rental"
    assert v2.lodging[0].price_per_night == _usd(74)
    assert [link.label for link in v2.lodging[0].links] == ["Google Hotels", "Airbnb"]
    assert next(b for b in v2.bookings if b.kind == "lodging").title == "Rental Booking"


def test_old_saved_lodging_without_type_defaults_to_hotel() -> None:
    old = {
        "stop_tag": "D", "check_in": "2027-03-05", "check_out": "2027-03-07", "nights": 2,
        "price_per_night": None, "total_price": None, "price_source": "none",
        "price_as_of": None, "links": [],
    }

    assert Lodging.model_validate(old).type == "hotel"


def test_lodging_type_rejects_unknown_values() -> None:
    old = {
        "stop_tag": "D", "type": "castle", "check_in": "2027-03-05", "check_out": "2027-03-07",
        "nights": 2, "price_per_night": None, "total_price": None, "price_source": "none",
        "price_as_of": None, "links": [],
    }

    with pytest.raises(ValueError):
        Lodging.model_validate(old)


# --- compose sees rentals; the prompt rule ---------------------------------------------------


def test_render_hotels_marks_rentals_after_hotels() -> None:
    text = pipeline.render_hotels([_found("h1", HOTEL), _found("h2", RENTAL)])
    lines = [line for line in text.splitlines() if line.startswith("- h")]

    assert lines[0].startswith("- h1 · Pacific Inn San Jose · $79/night")
    assert "vacation rental" not in lines[0]
    assert lines[1].startswith("- h2 · Oversize Loft w/ Kitchenette · $74/night")
    assert "vacation rental" in lines[1] and "Entire house, Sleeps 4" in lines[1]


def test_compose_prompt_has_the_rental_rule() -> None:
    system = pipeline.build_system(_profile(), TODAY, findings=[_found("h1", RENTAL)]).lower()

    assert "vacation rental" in system
    assert "airbnb" in system
    assert "3 or more travelers" in system


# --- the offline fake plan can show a rental ------------------------------------------------


def _generate(db: Session, messages: list[Message]) -> Itinerary:
    session_id = repo.create_session(db).id

    async def run() -> None:
        async for _ in pipeline.run_generation(
            db, session_id, FakeProvider(), _profile(), messages, on_saved=lambda _: None,
            today=TODAY,
        ):
            pass

    asyncio.run(run())
    plan = repo.get_latest_itinerary(db, session_id)
    assert plan is not None
    assert itinerary_errors(plan) == []
    return plan


def test_fake_plan_shows_a_rental_when_asked(db: Session, offline_tools: None) -> None:
    plan = _generate(db, [{"role": "user", "content": "We'd like an Airbnb near downtown"}])
    stop = _lodging_stop(plan)
    lodging = plan.lodging[0]

    assert lodging.type == "vacation_rental"
    assert stop.name.startswith("Oversize Loft")  # the first well-rated mock rental
    assert lodging.price_source == "serpapi_google_hotels"
    assert lodging.price_per_night is not None
    assert "Airbnb" in [link.label for link in lodging.links]
    assert "Booking.com" not in [link.label for link in lodging.links]
    assert next(b for b in plan.bookings if b.kind == "lodging").title == "Rental Booking"
    assert _lodging_item(plan).source.startswith("SerpApi Google Hotels (vacation rental) · as of ")
    texts = [f"{item.description} {item.why}" for day in plan.days for item in day.items]
    assert not any("Pacific Inn" in text for text in texts)


def test_car_rental_does_not_ask_for_a_vacation_rental(db: Session, offline_tools: None) -> None:
    plan = _generate(db, [{"role": "user", "content": "We'll pick up a car rental at the airport"}])

    assert plan.lodging[0].type == "hotel"


def test_fake_plan_default_is_still_the_hotel(db: Session, offline_tools: None) -> None:
    plan = _generate(db, [{"role": "user", "content": "A weekend in San Jose please"}])

    assert plan.lodging[0].type == "hotel"
    assert _lodging_stop(plan).name == "Pacific Inn San Jose"
