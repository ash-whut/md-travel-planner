"""Step 33: the places tool (Geoapify + Nominatim) and the tool registry.

Interest → category mapping and its default, result normalization, geocoding without a key
(Nominatim path), errors → ok=False, mock mode, and the `search_places` registry entry.
Live mode always runs over an httpx MockTransport with a patched `get_settings`, so the
developer's real GEOAPIFY_KEY in backend/.env is never read and nothing touches the network.
"""

import json
import threading
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.tools import places, registry
from app.tools.common import ToolResult, tool_ok
from app.tools.places import DEFAULT_CATEGORIES, categories_for, normalize_place

Handler = Callable[[httpx.Request], httpx.Response]
PLACE_KEYS = {"id", "name", "address", "lat", "lng", "category", "rating"}
GEOCODE_KEYS = {"name", "address", "lat", "lng", "source"}
LAT, LNG = 37.3361663, -121.8905833


@pytest.fixture(autouse=True)
def no_nominatim_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(places, "NOMINATIM_INTERVAL_SECONDS", 0.0)


def live(
    monkeypatch: pytest.MonkeyPatch, handler: Handler, key: str = ""
) -> tuple[httpx.Client, list[httpx.Request]]:
    """Live mode with the given Geoapify key (empty = none) over a fake transport."""
    settings = Settings(_env_file=None, tool_provider_mode="live", geoapify_key=key)
    monkeypatch.setattr(places, "get_settings", lambda: settings)
    monkeypatch.setattr(places, "is_mock", lambda: False)
    requests: list[httpx.Request] = []

    def logged(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    return httpx.Client(transport=httpx.MockTransport(logged)), requests


def nominatim_payload(name: str = "San Jose") -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "display_name": f"{name}, Santa Clara County, California, United States",
            "lat": "37.3361663",
            "lon": "-121.8905833",
        }
    ]


def geoapify_geocode_payload() -> dict[str, Any]:
    return {
        "results": [
            {
                "name": "San Jose",
                "formatted": "San Jose, CA, United States of America",
                "lat": 37.3361663,
                "lon": -121.8905833,
            }
        ]
    }


def feature(**properties: Any) -> dict[str, Any]:
    base = {
        "place_id": "abc123",
        "name": "Good Karma Kitchen",
        "address_line2": "37 S 1st St, San Jose, CA 95113",
        "formatted": "Good Karma Kitchen, 37 S 1st St, San Jose, CA 95113",
        "lat": 37.335,
        "lon": -121.889,
        "categories": ["catering", "catering.restaurant", "catering.restaurant.vegetarian"],
    }
    base.update(properties)
    return {"type": "Feature", "properties": base}


def assert_place_shape(place: dict[str, Any]) -> None:
    assert set(place) == PLACE_KEYS
    assert place["id"].startswith("geoapify:")
    assert place["name"]
    assert isinstance(place["lat"], float) and isinstance(place["lng"], float)
    assert place["rating"] is None or isinstance(place["rating"], (int, float))


# ---- interest → category mapping ----

@pytest.mark.parametrize(
    ("interest", "expected"),
    [
        ("food", "catering.restaurant"),
        ("coffee", "catering.cafe"),
        ("museums", "entertainment.museum"),
        ("tech", "entertainment.museum"),
        ("gardens", "leisure.park.garden"),  # plural matches by word prefix
        ("Hiking", "natural"),  # case-insensitive
        ("nightlife", "catering.bar"),
        ("shopping", "commercial.shopping_mall"),
    ],
)
def test_categories_for_known_interests(interest: str, expected: str) -> None:
    assert expected in categories_for(interest).split(",")


def test_categories_for_phrase_uses_a_matching_word() -> None:
    assert "leisure.park.garden" in categories_for("japanese gardens").split(",")


@pytest.mark.parametrize("interest", ["", "xyzzy", "vibes", "something else"])
def test_categories_for_unknown_interest_uses_default(interest: str) -> None:
    assert categories_for(interest) == DEFAULT_CATEGORIES


def test_categories_for_does_not_match_inside_a_word() -> None:
    # "start" contains "art" but does not start with it → default, not galleries.
    assert categories_for("start") == DEFAULT_CATEGORIES


def test_every_category_string_is_comma_separated_and_non_empty() -> None:
    for _, categories in places.INTEREST_CATEGORIES + [("", DEFAULT_CATEGORIES)]:
        parts = categories.split(",")
        assert parts and all(part and " " not in part for part in parts)


# ---- normalization ----

def test_normalize_place_shape_and_values() -> None:
    place = normalize_place({**feature(rating=4.5)["properties"]}, "catering.restaurant")
    assert_place_shape(place)
    assert place == {
        "id": "geoapify:abc123",
        "name": "Good Karma Kitchen",
        "address": "37 S 1st St, San Jose, CA 95113",
        "lat": 37.335,
        "lng": -121.889,
        "category": "catering.restaurant.vegetarian",  # most specific under the request
        "rating": 4.5,
    }


def test_normalize_place_without_rating_gives_null() -> None:
    place = normalize_place(feature()["properties"], "catering.restaurant")
    assert place["rating"] is None


def test_normalize_place_non_numeric_rating_gives_null() -> None:
    place = normalize_place(feature(rating="great")["properties"], "catering.restaurant")
    assert place["rating"] is None


def test_normalize_place_falls_back_to_formatted_address() -> None:
    props = feature()["properties"]
    del props["address_line2"]
    assert normalize_place(props, "catering.restaurant")["address"] == props["formatted"]


def test_normalize_place_category_outside_request_uses_first() -> None:
    props = feature(categories=["tourism", "tourism.sights"])["properties"]
    assert normalize_place(props, "catering.restaurant")["category"] == "tourism"


def test_normalize_place_without_categories_gives_null() -> None:
    props = feature(categories=[])["properties"]
    assert normalize_place(props, "catering.restaurant")["category"] is None


# ---- mock mode ----

def test_mock_geocode_known_city() -> None:
    result = places.geocode("San Francisco, CA")
    assert result.ok
    assert set(result.data) == GEOCODE_KEYS
    assert result.data["name"] == "San Francisco"
    assert result.data["lat"] == pytest.approx(37.78, abs=0.01)


def test_mock_geocode_unknown_city_falls_back_to_first() -> None:
    result = places.geocode("Nowhere, ZZ")
    assert result.ok
    assert result.data["name"] == "San Jose"


def test_geocode_empty_query_is_error() -> None:
    result = places.geocode("   ")
    assert result.ok is False and result.error


def test_mock_search_filters_by_interest() -> None:
    result = places.search(LAT, LNG, "food")
    assert result.ok
    assert result.data
    for place in result.data:
        assert_place_shape(place)
        assert place["category"].startswith("catering.")
    names = {p["name"] for p in result.data}
    assert "Good Karma Kitchen" in names
    assert "The Tech Interactive" not in names


def test_mock_search_respects_limit() -> None:
    result = places.search(LAT, LNG, "sightseeing", limit=1)
    assert result.ok
    assert len(result.data) == 1


def test_mock_search_ids_are_unique() -> None:
    result = places.search(LAT, LNG, "parks")
    ids = [p["id"] for p in result.data]
    assert ids and len(ids) == len(set(ids))


# ---- geocode, live mode over a fake transport ----

def test_geocode_without_key_uses_nominatim(monkeypatch: pytest.MonkeyPatch) -> None:
    client, requests = live(monkeypatch, lambda r: httpx.Response(200, json=nominatim_payload()))
    result = places.geocode("San Jose, CA", client=client)
    assert result.ok
    assert result.data["source"] == "Nominatim"
    assert result.data["name"] == "San Jose"
    assert result.data["lat"] == pytest.approx(37.3361663)  # strings parsed to floats
    assert isinstance(result.data["lng"], float)
    assert len(requests) == 1
    request = requests[0]
    assert request.url.host == "nominatim.openstreetmap.org"
    assert request.url.params["q"] == "San Jose, CA"  # region passed through
    assert "geoapify" not in str(request.url)
    user_agent = request.headers.get("user-agent", "")
    assert user_agent and not user_agent.startswith("python-httpx")


def test_geocode_region_survives_for_other_cities(monkeypatch: pytest.MonkeyPatch) -> None:
    client, requests = live(monkeypatch, lambda r: httpx.Response(200, json=nominatim_payload("Paris")))
    places.geocode("Paris, TX", client=client)
    assert requests[0].url.params["q"] == "Paris, TX"


def test_geocode_with_key_uses_geoapify(monkeypatch: pytest.MonkeyPatch) -> None:
    client, requests = live(
        monkeypatch, lambda r: httpx.Response(200, json=geoapify_geocode_payload()), key="test-key"
    )
    result = places.geocode("San Jose, CA", client=client)
    assert result.ok
    assert set(result.data) == GEOCODE_KEYS
    assert result.data["source"] == "Geoapify"
    assert len(requests) == 1
    assert requests[0].url.host == "api.geoapify.com"
    assert requests[0].url.params["text"] == "San Jose, CA"


def test_geocode_geoapify_error_falls_back_to_nominatim(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.geoapify.com":
            return httpx.Response(500)
        return httpx.Response(200, json=nominatim_payload())

    client, requests = live(monkeypatch, handler, key="test-key")
    result = places.geocode("San Jose, CA", client=client)
    assert result.ok
    assert result.data["source"] == "Nominatim"
    assert [r.url.host for r in requests] == ["api.geoapify.com", "nominatim.openstreetmap.org"]


def test_geocode_geoapify_empty_falls_back_to_nominatim(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.geoapify.com":
            return httpx.Response(200, json={"results": []})
        return httpx.Response(200, json=nominatim_payload())

    client, _ = live(monkeypatch, handler, key="test-key")
    result = places.geocode("San Jose, CA", client=client)
    assert result.ok and result.data["source"] == "Nominatim"


def test_geocode_http_error_is_ok_false(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = live(monkeypatch, lambda r: httpx.Response(503))
    result = places.geocode("San Jose, CA", client=client)
    assert result.ok is False
    assert "503" in (result.error or "")


def test_geocode_network_error_is_ok_false(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    client, _ = live(monkeypatch, handler)
    result = places.geocode("San Jose, CA", client=client)
    assert result.ok is False and result.error


def test_geocode_not_found_is_ok_false(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = live(monkeypatch, lambda r: httpx.Response(200, json=[]))
    result = places.geocode("Qwxzv", client=client)
    assert result.ok is False and result.error


def test_geocode_bad_json_is_ok_false(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = live(monkeypatch, lambda r: httpx.Response(200, content=b"not json"))
    result = places.geocode("San Jose, CA", client=client)
    assert result.ok is False and result.error


def test_geocode_error_does_not_leak_key(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = live(monkeypatch, lambda r: httpx.Response(500), key="secret-key-123")
    result = places.geocode("San Jose, CA", client=client)
    assert result.ok is False
    assert "secret-key-123" not in (result.error or "")


def test_geocode_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    client, requests = live(monkeypatch, lambda r: httpx.Response(200, json=nominatim_payload()))
    first = places.geocode("San Jose, CA", client=client)
    second = places.geocode("san jose, ca", client=client)
    assert first.ok and second.ok
    assert second.data == first.data
    assert len(requests) == 1


def test_precise_geocode_rejects_a_geoapify_city_match(monkeypatch: pytest.MonkeyPatch) -> None:
    # An unknown hotel name: Geoapify answers with the city, then Nominatim does too.
    city = {**geoapify_geocode_payload()["results"][0], "result_type": "city"}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.geoapify.com":
            return httpx.Response(200, json={"results": [city]})
        return httpx.Response(200, json=[{**nominatim_payload()[0], "addresstype": "city"}])

    client, requests = live(monkeypatch, handler, key="test-key")
    result = places.geocode("Hotel Nowhere, San Jose", client=client, precise=True)
    assert result.ok is False
    assert [r.url.host for r in requests] == ["api.geoapify.com", "nominatim.openstreetmap.org"]


@pytest.mark.parametrize("field", ["addresstype", "type"])
@pytest.mark.parametrize("area", ["city", "town", "village", "county", "state", "country"])
def test_precise_geocode_rejects_a_nominatim_area_match(
    monkeypatch: pytest.MonkeyPatch, field: str, area: str
) -> None:
    payload = [{**nominatim_payload()[0], field: area}]
    client, _ = live(monkeypatch, lambda r: httpx.Response(200, json=payload))
    assert places.geocode("Hotel Nowhere, San Jose", client=client, precise=True).ok is False


def test_precise_geocode_keeps_a_specific_match(monkeypatch: pytest.MonkeyPatch) -> None:
    hotel = {**geoapify_geocode_payload()["results"][0], "name": "Hotel Clariana",
             "result_type": "amenity"}
    client, _ = live(
        monkeypatch, lambda r: httpx.Response(200, json={"results": [hotel]}), key="test-key"
    )
    result = places.geocode("Hotel Clariana, San Jose", client=client, precise=True)
    assert result.ok and result.data["name"] == "Hotel Clariana"


def test_city_geocode_keeps_a_city_match(monkeypatch: pytest.MonkeyPatch) -> None:
    city = {**geoapify_geocode_payload()["results"][0], "result_type": "city"}
    client, _ = live(
        monkeypatch, lambda r: httpx.Response(200, json={"results": [city]}), key="test-key"
    )
    result = places.geocode("San Jose, CA", client=client)  # e.g. from search_places
    assert result.ok and result.data["name"] == "San Jose"


def test_precise_geocode_does_not_reuse_a_cached_city_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = [{**nominatim_payload()[0], "addresstype": "city"}]
    client, requests = live(monkeypatch, lambda r: httpx.Response(200, json=payload))
    assert places.geocode("San Jose, CA", client=client).ok is True
    assert places.geocode("San Jose, CA", client=client, precise=True).ok is False
    assert len(requests) == 2


def test_geocode_errors_are_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [httpx.Response(500), httpx.Response(200, json=nominatim_payload())]
    client, requests = live(monkeypatch, lambda r: responses.pop(0))
    assert places.geocode("San Jose, CA", client=client).ok is False
    assert places.geocode("San Jose, CA", client=client).ok is True
    assert len(requests) == 2


def test_nominatim_calls_are_spaced_out(monkeypatch: pytest.MonkeyPatch) -> None:
    # Two parallel lookups with a 1 s interval: the second must wait (we record the sleep
    # instead of actually sleeping).
    monkeypatch.setattr(places, "NOMINATIM_INTERVAL_SECONDS", 1.0)
    monkeypatch.setattr(places, "_nominatim_last_call", 0.0)
    clock = [1000.0]
    sleeps: list[float] = []
    monkeypatch.setattr(places.time, "monotonic", lambda: clock[0])

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(places.time, "sleep", fake_sleep)
    client, requests = live(monkeypatch, lambda r: httpx.Response(200, json=nominatim_payload()))

    threads = [
        threading.Thread(target=places.geocode, args=(city,), kwargs={"client": client})
        for city in ["San Jose, CA", "Santa Clara, CA"]
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(requests) == 2
    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(1.0)


def test_module_has_a_nominatim_lock() -> None:
    assert isinstance(places._nominatim_lock, type(threading.Lock()))


# ---- search, live mode over a fake transport ----

def test_search_live_normalizes_and_skips_unnamed(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "type": "FeatureCollection",
        "features": [
            feature(rating=4),
            feature(place_id="noname", name=None),
            feature(place_id="def456", name="Original Joe's", categories=["catering.restaurant"]),
        ],
    }
    client, requests = live(monkeypatch, lambda r: httpx.Response(200, json=payload), key="test-key")
    result = places.search(LAT, LNG, "food", client=client)
    assert result.ok
    assert [p["id"] for p in result.data] == ["geoapify:abc123", "geoapify:def456"]
    for place in result.data:
        assert_place_shape(place)
    assert len(requests) == 1
    params = requests[0].url.params
    assert requests[0].url.host == "api.geoapify.com"
    assert params["categories"] == categories_for("food")
    assert params["limit"] == "8"
    assert str(LAT) in params["filter"] and str(LNG) in params["filter"]


def test_search_live_without_key_is_ok_false(monkeypatch: pytest.MonkeyPatch) -> None:
    client, requests = live(monkeypatch, lambda r: httpx.Response(200, json={"features": []}))
    result = places.search(LAT, LNG, "food", client=client)
    assert result.ok is False and result.error
    assert requests == []


def test_search_http_error_is_ok_false(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = live(monkeypatch, lambda r: httpx.Response(429), key="secret-key-123")
    result = places.search(LAT, LNG, "food", client=client)
    assert result.ok is False
    assert "429" in (result.error or "")
    assert "secret-key-123" not in (result.error or "")


def test_search_malformed_payload_is_ok_false(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = live(monkeypatch, lambda r: httpx.Response(200, json={"oops": 1}), key="test-key")
    result = places.search(LAT, LNG, "food", client=client)
    assert result.ok is False and result.error


def test_search_live_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"features": [feature()]}
    client, requests = live(monkeypatch, lambda r: httpx.Response(200, json=payload), key="test-key")
    assert places.search(LAT, LNG, "food", client=client).ok
    assert places.search(LAT, LNG, "food", client=client).ok
    assert len(requests) == 1


# ---- mocks ----

def test_mock_files_are_geoapify_shaped() -> None:
    geocode = places.load_mock("places_geocode")
    assert geocode["results"] and all({"lat", "lon"} <= set(r) for r in geocode["results"])
    search = places.load_mock("places_search")
    assert search["features"]
    for item in search["features"]:
        assert {"place_id", "name", "lat", "lon", "categories"} <= set(item["properties"])


# ---- registry ----

def test_registry_has_search_places_entry() -> None:
    tool = registry.TOOLS["search_places"]
    assert tool.name == "search_places"
    assert tool.description.strip()
    assert tool.function is registry.search_places


def test_search_places_schema() -> None:
    schema = registry.TOOLS["search_places"].parameters
    assert schema["type"] == "object"
    assert set(schema["properties"]) == {"city", "interest"}
    assert schema["properties"]["city"]["type"] == "string"
    assert schema["properties"]["interest"]["type"] == "string"
    assert set(schema["required"]) == {"city", "interest"}
    assert schema["additionalProperties"] is False
    json.dumps(schema)  # serializable for the LLM


def test_tool_entries_are_frozen() -> None:
    tool = registry.TOOLS["search_places"]
    with pytest.raises(Exception):
        tool.name = "other"  # type: ignore[misc]


def test_search_places_geocodes_then_searches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, Any]] = []

    def fake_geocode(query: str, client: Any = None) -> ToolResult:
        calls.append(("geocode", query))
        return tool_ok({"name": "Austin", "address": "Austin, TX", "lat": 30.27, "lng": -97.74, "source": "Nominatim"})

    def fake_search(lat: float, lng: float, interest: str, limit: int = 8, client: Any = None) -> ToolResult:
        calls.append(("search", (lat, lng, interest)))
        return tool_ok([{"id": "geoapify:x", "name": "Place"}])

    monkeypatch.setattr(places, "geocode", fake_geocode)
    monkeypatch.setattr(places, "search", fake_search)

    result = registry.run_tool("search_places", {"city": "Austin, TX", "interest": "food"})
    assert result.ok
    assert result.data == [{"id": "geoapify:x", "name": "Place"}]
    assert calls == [("geocode", "Austin, TX"), ("search", (30.27, -97.74, "food"))]


def test_search_places_stops_when_geocode_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    searched: list[Any] = []
    monkeypatch.setattr(places, "geocode", lambda query, client=None: ToolResult(ok=False, error="Place not found"))
    monkeypatch.setattr(places, "search", lambda *a, **k: searched.append(a) or tool_ok([]))
    result = registry.run_tool("search_places", {"city": "Qwxzv", "interest": "food"})
    assert result.ok is False and result.error
    assert searched == []


def test_run_tool_in_mock_mode_returns_places() -> None:
    result = registry.run_tool("search_places", {"city": "San Jose, CA", "interest": "museums"})
    assert result.ok
    assert result.data
    for place in result.data:
        assert_place_shape(place)


def test_run_tool_unknown_tool_is_ok_false() -> None:
    result = registry.run_tool("book_flight", {"city": "San Jose, CA"})
    assert result.ok is False
    assert "book_flight" in (result.error or "")


@pytest.mark.parametrize(
    "arguments",
    [{}, {"city": "San Jose, CA"}, {"city": "San Jose, CA", "interest": "food", "extra": 1}],
)
def test_run_tool_bad_arguments_is_ok_false(arguments: dict[str, Any]) -> None:
    result = registry.run_tool("search_places", arguments)
    assert result.ok is False and result.error


# ---- live smoke test (skipped by default) ----

@pytest.mark.live
def test_live_search_places_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(places, "is_mock", lambda: False)
    result = registry.run_tool("search_places", {"city": "San Jose, CA", "interest": "museums"})
    assert result.ok, result.error
    assert result.data
