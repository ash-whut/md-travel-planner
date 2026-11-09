"""Step 38: the hotels tool (SerpApi Google Hotels) and its `search_hotels` registry entry.

Normalization and the rating filter, mock mode, the 6 h cache, the no-price places fallback
(no key, 429, quota message), errors → ok=False, and the registry entry with its per-plan
limit. Live mode always runs over an httpx MockTransport with a patched `get_settings`, so the
developer's real SERPAPI_KEY is never read and nothing touches the network. The places tool
stays in mock mode, so the lodging fallback reads recorded JSON.
"""

import re
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.db.tables import utcnow
from app.tools import hotels, registry
from app.tools.common import HOTELS_TTL_SECONDS, cache_get, tool_error

Handler = Callable[[httpx.Request], httpx.Response]
HOTEL_KEYS = {
    "id", "name", "address", "lat", "lng", "rating", "price_per_night", "total_price",
    "price_source", "price_as_of", "link",
}
KEY = "test-serpapi-key"
CHECK_IN, CHECK_OUT = "2027-03-05", "2027-03-07"
ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def prop(name: str = "Hotel A", rating: Any = 4.0, nightly: Any = 100, total: Any = 200,
         token: str | None = "tok_a", **extra: Any) -> dict[str, Any]:
    """One SerpApi `properties` entry."""
    entry: dict[str, Any] = {
        "name": name,
        "overall_rating": rating,
        "rate_per_night": {"lowest": f"${nightly}", "extracted_lowest": nightly},
        "total_rate": {"lowest": f"${total}", "extracted_lowest": total},
        "gps_coordinates": {"latitude": 37.33, "longitude": -121.89},
        "link": "https://example.com/hotel-a",
        **extra,
    }
    if token is not None:
        entry["property_token"] = token
    return entry


def live(
    monkeypatch: pytest.MonkeyPatch, handler: Handler, key: str = KEY
) -> tuple[httpx.Client, list[httpx.Request]]:
    """Hotels in live mode with the given SerpApi key (empty = none) over a fake transport."""
    settings = Settings(_env_file=None, tool_provider_mode="live", serpapi_key=key)
    monkeypatch.setattr(hotels, "get_settings", lambda: settings)
    monkeypatch.setattr(hotels, "is_mock", lambda: False)
    requests: list[httpx.Request] = []

    def logged(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    return httpx.Client(transport=httpx.MockTransport(logged)), requests


def serpapi_ok(properties: list[dict[str, Any]]) -> Handler:
    return lambda request: httpx.Response(200, json={"properties": properties})


def search(client: httpx.Client, city: str = "San Jose, CA", check_in: str = CHECK_IN,
           check_out: str = CHECK_OUT) -> Any:
    return hotels.search(city, check_in, check_out, client=client)


# ---- normalization ----

def test_normalize_hotel_full_entry() -> None:
    hotel = hotels.normalize_hotel(prop(), "2026-11-08T12:00:00Z")
    assert set(hotel) == HOTEL_KEYS
    assert hotel["id"] == "serpapi:tok_a"
    assert hotel["name"] == "Hotel A"
    assert hotel["address"] is None
    assert (hotel["lat"], hotel["lng"]) == (37.33, -121.89)
    assert hotel["rating"] == 4.0
    assert hotel["price_per_night"] == {"amount": 100, "currency": "USD"}
    assert hotel["total_price"] == {"amount": 200, "currency": "USD"}
    assert hotel["price_source"] == "serpapi_google_hotels"
    assert hotel["price_as_of"] == "2026-11-08T12:00:00Z"
    assert hotel["link"] == "https://example.com/hotel-a"


def test_normalize_hotel_missing_fields_become_null() -> None:
    hotel = hotels.normalize_hotel({"name": "Bare Inn"}, "2026-11-08T12:00:00Z")
    assert set(hotel) == HOTEL_KEYS
    assert hotel["id"] is None
    for field in ("lat", "lng", "rating", "price_per_night", "total_price", "link"):
        assert hotel[field] is None, field
    assert hotel["price_source"] == "serpapi_google_hotels"


@pytest.mark.parametrize("bad", [0, -5, None, "85", "$85"])
def test_normalize_hotel_unusable_price_is_null(bad: Any) -> None:
    hotel = hotels.normalize_hotel(prop(nightly=bad, total=bad), "t")
    assert hotel["price_per_night"] is None
    assert hotel["total_price"] is None


def test_normalize_hotel_non_numeric_rating_is_null() -> None:
    assert hotels.normalize_hotel(prop(rating="great"), "t")["rating"] is None


def test_normalize_hotels_keeps_well_rated_in_order() -> None:
    props = [
        prop("Cheap Bad", rating=1.8, nightly=50),
        prop("Edge", rating=3.5, nightly=60),
        prop("Unrated", rating=None, nightly=70),
        prop("Good", rating=4.2, nightly=90),
        prop("Below", rating=3.4, nightly=95),
    ]
    names = [h["name"] for h in hotels.normalize_hotels(props, "t")]
    assert names == ["Edge", "Good"]  # 3.5 is in, cheapest first kept


def test_normalize_hotels_caps_at_five() -> None:
    props = [prop(f"H{i}", rating=4.0, nightly=50 + i) for i in range(8)]
    names = [h["name"] for h in hotels.normalize_hotels(props, "t")]
    assert names == ["H0", "H1", "H2", "H3", "H4"]


def test_normalize_hotels_keeps_all_when_none_qualify() -> None:
    props = [prop(f"H{i}", rating=2.0) for i in range(3)] + [prop("NoRating", rating=None)]
    names = [h["name"] for h in hotels.normalize_hotels(props, "t")]
    assert names == ["H0", "H1", "H2", "NoRating"]


def test_normalize_hotels_skips_unnamed() -> None:
    props = [{"overall_rating": 4.5}, prop("", rating=4.5), prop("Named")]
    assert [h["name"] for h in hotels.normalize_hotels(props, "t")] == ["Named"]


def test_now_iso_is_utc_with_z() -> None:
    assert ISO_Z.match(hotels.now_iso())


# ---- mock mode ----

def test_mock_search_returns_recorded_hotels() -> None:
    result = hotels.search("San Jose, CA", CHECK_IN, CHECK_OUT)
    assert result.ok, result.error
    assert 1 <= len(result.data) <= 5
    for hotel in result.data:
        assert set(hotel) == HOTEL_KEYS
        assert hotel["price_source"] == "serpapi_google_hotels"
        assert ISO_Z.match(hotel["price_as_of"])
        assert hotel["rating"] is not None and hotel["rating"] >= 3.5
        assert hotel["price_per_night"]["currency"] == "USD"
        assert hotel["lat"] is not None and hotel["lng"] is not None
    nightly = [h["price_per_night"]["amount"] for h in result.data]
    assert nightly == sorted(nightly)  # cheapest first


def test_mock_search_filters_out_poorly_rated() -> None:
    names = [h["name"] for h in hotels.search("San Jose, CA", CHECK_IN, CHECK_OUT).data]
    assert "Budget Lodge San Jose" not in names  # rated 1.8 in the recording


def test_mock_search_works_for_any_city() -> None:
    result = hotels.search("Austin, TX", CHECK_IN, CHECK_OUT)
    assert result.ok and result.data


def test_splurge_orders_by_rating() -> None:
    result = hotels.search("San Jose, CA", CHECK_IN, CHECK_OUT, budget_level="splurge")
    ratings = [h["rating"] for h in result.data]
    assert ratings == sorted(ratings, reverse=True)


def test_mock_search_makes_no_http_request(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("mock mode must not call get_json")

    monkeypatch.setattr(hotels, "get_json", boom)
    assert hotels.search("San Jose, CA", CHECK_IN, CHECK_OUT).ok


# ---- input errors ----

@pytest.mark.parametrize(
    ("city", "check_in", "check_out"),
    [
        ("", CHECK_IN, CHECK_OUT),
        ("   ", CHECK_IN, CHECK_OUT),
        ("San Jose, CA", "2027-03-07", "2027-03-05"),  # check_out before check_in
        ("San Jose, CA", CHECK_IN, CHECK_IN),  # zero nights
        ("San Jose, CA", "03/05/2027", CHECK_OUT),
        ("San Jose, CA", CHECK_IN, "next friday"),
        ("San Jose, CA", "2027-02-30", CHECK_OUT),
    ],
)
def test_bad_input_is_ok_false(city: str, check_in: str, check_out: str) -> None:
    result = hotels.search(city, check_in, check_out)
    assert result.ok is False
    assert result.error


def test_bad_dates_never_reach_serpapi(monkeypatch: pytest.MonkeyPatch) -> None:
    client, requests = live(monkeypatch, serpapi_ok([prop()]))
    assert search(client, check_in="2027-03-07", check_out="2027-03-05").ok is False
    assert requests == []


# ---- live mode with a key ----

def test_live_search_sends_lowest_price_google_hotels_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, requests = live(monkeypatch, serpapi_ok([prop()]))
    result = search(client)
    assert result.ok, result.error
    assert len(requests) == 1
    params = requests[0].url.params
    assert requests[0].url.host == "serpapi.com"
    assert params["engine"] == "google_hotels"
    assert params["q"] == "San Jose, CA"
    assert params["check_in_date"] == CHECK_IN
    assert params["check_out_date"] == CHECK_OUT
    assert params["sort_by"] == "3"  # lowest price
    assert params["api_key"] == KEY


def test_live_search_normalizes(monkeypatch: pytest.MonkeyPatch) -> None:
    props = [prop("Cheap Bad", rating=2.0, nightly=40), prop("Good", rating=4.1, nightly=99)]
    client, _ = live(monkeypatch, serpapi_ok(props))
    result = search(client)
    assert [h["name"] for h in result.data] == ["Good"]
    hotel = result.data[0]
    assert set(hotel) == HOTEL_KEYS
    assert hotel["price_per_night"] == {"amount": 99, "currency": "USD"}
    assert hotel["price_source"] == "serpapi_google_hotels"
    assert ISO_Z.match(hotel["price_as_of"])


def test_live_search_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    client, requests = live(monkeypatch, serpapi_ok([prop()]))
    first = search(client)
    second = search(client, city="  san jose, ca ")  # same city, other case and spaces
    assert first.ok and second.ok
    assert len(requests) == 1
    assert second.data == first.data  # price_as_of is the time SerpApi was asked


def test_cache_is_per_dates(monkeypatch: pytest.MonkeyPatch) -> None:
    client, requests = live(monkeypatch, serpapi_ok([prop()]))
    search(client)
    search(client, check_out="2027-03-08")
    assert len(requests) == 2


def test_cache_lasts_six_hours() -> None:
    assert HOTELS_TTL_SECONDS == 6 * 60 * 60


def test_cached_entry_expires_after_six_hours(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = live(monkeypatch, serpapi_ok([prop()]))
    search(client)
    args = {"city": "san jose, ca", "check_in": CHECK_IN, "check_out": CHECK_OUT}
    assert cache_get("hotels", args) is not None
    assert cache_get("hotels", args, now=utcnow() + timedelta(hours=6, minutes=1)) is None


def test_cached_result_still_honours_splurge(monkeypatch: pytest.MonkeyPatch) -> None:
    props = [prop("Cheap", rating=3.6, nightly=60), prop("Best", rating=4.8, nightly=200)]
    client, requests = live(monkeypatch, serpapi_ok(props))
    assert [h["name"] for h in search(client).data] == ["Cheap", "Best"]
    splurge = hotels.search("San Jose, CA", CHECK_IN, CHECK_OUT, budget_level="splurge",
                            client=client)
    assert [h["name"] for h in splurge.data] == ["Best", "Cheap"]
    assert len(requests) == 1


def test_live_empty_result_is_ok_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = live(monkeypatch, lambda request: httpx.Response(200, json={}))
    result = search(client)
    assert result.ok and result.data == []


# ---- errors → ok: false ----

@pytest.mark.parametrize("status", [400, 401, 500, 503])
def test_http_error_is_ok_false(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    client, _ = live(monkeypatch, lambda request: httpx.Response(status, json={"error": "x"}))
    result = search(client)
    assert result.ok is False
    assert KEY not in (result.error or "")


def test_network_error_is_ok_false(monkeypatch: pytest.MonkeyPatch) -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    client, _ = live(monkeypatch, down)
    result = search(client)
    assert result.ok is False
    assert KEY not in (result.error or "")


def test_non_json_body_is_ok_false(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = live(monkeypatch, lambda request: httpx.Response(200, text="<html>oops"))
    assert search(client).ok is False


def test_malformed_properties_is_ok_false(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = live(monkeypatch, lambda request: httpx.Response(200, json={"properties": 5}))
    assert search(client).ok is False


def test_serpapi_error_message_is_ok_false(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = live(
        monkeypatch, lambda request: httpx.Response(200, json={"error": "Invalid API key."})
    )
    result = search(client)
    assert result.ok is False
    assert "Invalid API key" in (result.error or "")


def test_errors_are_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter([httpx.Response(500), httpx.Response(200, json={"properties": [prop()]})])
    client, requests = live(monkeypatch, lambda request: next(responses))
    assert search(client).ok is False
    assert search(client).ok is True
    assert len(requests) == 2


# ---- no-price fallback ----

def assert_unpriced_lodging(result: Any) -> None:
    assert result.ok, result.error
    assert 1 <= len(result.data) <= 5
    for hotel in result.data:
        assert set(hotel) == HOTEL_KEYS
        assert hotel["name"]
        assert hotel["price_per_night"] is None
        assert hotel["total_price"] is None
        assert hotel["price_source"] == "none"
        assert hotel["price_as_of"] is None


def test_no_key_falls_back_to_lodging_places(monkeypatch: pytest.MonkeyPatch) -> None:
    client, requests = live(monkeypatch, serpapi_ok([prop()]), key="")
    result = search(client)
    assert_unpriced_lodging(result)
    assert not any(r.url.host == "serpapi.com" for r in requests)


def test_fallback_uses_places_lodging_search(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    real_search = hotels.places.search

    def spy(lat: float, lng: float, interest: str, **kwargs: Any) -> Any:
        calls.append(interest)
        return real_search(lat, lng, interest, **kwargs)

    monkeypatch.setattr(hotels.places, "search", spy)
    client, _ = live(monkeypatch, serpapi_ok([prop()]), key="")
    assert_unpriced_lodging(search(client))
    assert calls == ["lodging"]


def test_quota_429_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = live(monkeypatch, lambda request: httpx.Response(429, json={"error": "limit"}))
    assert_unpriced_lodging(search(client))


def test_run_out_of_searches_message_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {"error": "Your account has run out of searches."}
    client, _ = live(monkeypatch, lambda request: httpx.Response(200, json=body))
    assert_unpriced_lodging(search(client))


def test_fallback_is_not_cached_as_hotels(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter(
        [httpx.Response(429), httpx.Response(200, json={"properties": [prop()]})]
    )
    client, requests = live(monkeypatch, lambda request: next(responses))
    assert search(client).data[0]["price_source"] == "none"
    assert search(client).data[0]["price_source"] == "serpapi_google_hotels"
    assert len(requests) == 2


def test_fallback_geocode_failure_is_ok_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hotels.places, "geocode", lambda *a, **k: tool_error("Place not found"))
    client, _ = live(monkeypatch, serpapi_ok([prop()]), key="")
    assert search(client).ok is False


def test_fallback_search_failure_is_ok_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hotels.places, "search", lambda *a, **k: tool_error("search failed"))
    client, _ = live(monkeypatch, serpapi_ok([prop()]), key="")
    assert search(client).ok is False


# ---- registry (mock mode only: a live run_tool would make a real request) ----

def test_registry_has_search_hotels_entry() -> None:
    tool = registry.TOOLS["search_hotels"]
    assert tool.name == "search_hotels"
    assert tool.description
    assert tool.function is registry.search_hotels


def test_search_hotels_schema_uses_fake_planner_argument_names() -> None:
    schema = registry.TOOLS["search_hotels"].parameters
    assert schema["type"] == "object"
    assert set(schema["properties"]) == {"city", "check_in", "check_out"}
    assert set(schema["required"]) == {"city", "check_in", "check_out"}
    assert schema["additionalProperties"] is False


def test_run_tool_search_hotels_in_mock_mode() -> None:
    args = {"city": "San Jose, CA", "check_in": CHECK_IN, "check_out": CHECK_OUT}
    result = registry.run_tool("search_hotels", args)
    assert result.ok, result.error
    assert all(set(h) == HOTEL_KEYS for h in result.data)


def test_run_tool_search_hotels_bad_arguments_is_ok_false() -> None:
    assert registry.run_tool("search_hotels", {"city": "San Jose, CA"}).ok is False
    bad_dates = {"city": "San Jose, CA", "check_in": CHECK_OUT, "check_out": CHECK_IN}
    assert registry.run_tool("search_hotels", bad_dates).ok is False


def test_plan_limits_one_hotel_search_per_city() -> None:
    limits = registry.PlanLimits()
    args = {"city": "San Jose, CA", "check_in": CHECK_IN, "check_out": CHECK_OUT}
    assert registry.run_tool("search_hotels", args, limits).ok
    again = registry.run_tool("search_hotels", {**args, "city": " san jose "}, limits)
    assert again.ok is False
    assert again.error == "skipped: limit"
    other_dates = {**args, "check_out": "2027-03-08"}
    assert registry.run_tool("search_hotels", other_dates, limits).error == "skipped: limit"


def test_plan_limits_allow_another_city() -> None:
    limits = registry.PlanLimits()
    base = {"check_in": CHECK_IN, "check_out": CHECK_OUT}
    assert registry.run_tool("search_hotels", {"city": "San Jose, CA", **base}, limits).ok
    assert registry.run_tool("search_hotels", {"city": "San Francisco, CA", **base}, limits).ok


def test_plan_limits_are_per_plan() -> None:
    args = {"city": "San Jose, CA", "check_in": CHECK_IN, "check_out": CHECK_OUT}
    first, second = registry.PlanLimits(), registry.PlanLimits()
    assert registry.run_tool("search_hotels", args, first).ok
    assert registry.run_tool("search_hotels", args, second).ok


def test_no_limits_means_no_skipping() -> None:
    args = {"city": "San Jose, CA", "check_in": CHECK_IN, "check_out": CHECK_OUT}
    assert registry.run_tool("search_hotels", args).ok
    assert registry.run_tool("search_hotels", args).ok


def test_plan_limits_do_not_limit_search_places() -> None:
    limits = registry.PlanLimits()
    args = {"city": "San Jose, CA", "interest": "museums"}
    assert registry.run_tool("search_places", args, limits).ok
    assert registry.run_tool("search_places", args, limits).ok


def test_skipped_call_does_not_run_the_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def counting(city: str, check_in: str, check_out: str) -> Any:
        calls.append(city)
        return hotels.search(city, check_in, check_out)

    monkeypatch.setitem(
        registry.TOOLS, "search_hotels",
        registry.Tool(name="search_hotels", description="d", parameters={}, function=counting),
    )
    limits = registry.PlanLimits()
    args = {"city": "San Jose, CA", "check_in": CHECK_IN, "check_out": CHECK_OUT}
    registry.run_tool("search_hotels", args, limits)
    registry.run_tool("search_hotels", args, limits)
    assert calls == ["San Jose, CA"]


def test_city_key() -> None:
    assert registry.city_key("San Jose, CA") == "san jose"
    assert registry.city_key("  San   Jose ") == "san jose"
