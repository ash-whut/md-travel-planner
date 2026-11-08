"""Places tool: geocoding (Geoapify, falling back to Nominatim) and place search (Geoapify).

Geoapify's free plan allows 3,000 credits/day and 5 requests/second; the planner's 6-call cap
keeps us under the rate (D25). Nominatim allows ≤ 1 request/second, so a module-level lock
spaces its calls out even when tool calls run in parallel threads. Unlike Open-Meteo, both
geocoders take the full query, so a region like "Paris, TX" is passed through.
Both public functions return a `ToolResult` and never raise.
"""

import re
import threading
import time
from typing import Any

import httpx

from app.core.config import get_settings
from app.tools.common import (
    GEOCODE_TTL_SECONDS,
    PLACES_TTL_SECONDS,
    ToolResult,
    cache_get,
    cache_set,
    describe_error,
    get_json,
    is_mock,
    load_mock,
    tool_error,
    tool_ok,
)

GEOAPIFY_GEOCODE_URL = "https://api.geoapify.com/v1/geocode/search"
GEOAPIFY_PLACES_URL = "https://api.geoapify.com/v2/places"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Nominatim's usage policy asks for a User-Agent that names the app.
NOMINATIM_HEADERS = {"User-Agent": "md-travel-planner/0.1 (CSCE 634 course project)"}
NOMINATIM_INTERVAL_SECONDS = 1.0
SEARCH_RADIUS_METERS = 10_000
# Area-level match types (Geoapify `result_type`, Nominatim `addresstype`/`type`). A geocoder
# answers an unknown hotel name with the city it is in; a precise lookup rejects those (D27).
AREA_RESULT_TYPES = {"city", "town", "village", "county", "state", "country", "postcode"}

# Interest keyword → Geoapify categories (https://apidocs.geoapify.com/docs/places/#categories).
# An interest matches when one of its words starts with the keyword ("gardens" → "garden");
# the first match wins, so put more specific keywords first.
INTEREST_CATEGORIES: list[tuple[str, str]] = [
    ("coffee", "catering.cafe"),
    ("cafe", "catering.cafe"),
    ("food", "catering.restaurant,catering.fast_food,catering.food_court"),
    ("restaurant", "catering.restaurant"),
    ("eat", "catering.restaurant,catering.fast_food,catering.food_court"),
    ("nightlife", "catering.bar,catering.pub,adult.nightclub"),
    ("drink", "catering.bar,catering.pub"),
    ("tech", "entertainment.museum,entertainment.planetarium"),
    ("science", "entertainment.museum,entertainment.planetarium"),
    ("museum", "entertainment.museum"),
    ("art", "entertainment.culture.gallery,entertainment.museum"),
    ("history", "tourism.sights,heritage"),
    ("garden", "leisure.park.garden,leisure.park"),
    ("park", "leisure.park"),
    ("nature", "natural,leisure.park"),
    ("hik", "natural,leisure.park"),
    ("beach", "beach"),
    ("shop", "commercial.shopping_mall,commercial.marketplace"),
    ("zoo", "entertainment.zoo,entertainment.aquarium"),
]
DEFAULT_CATEGORIES = "tourism.sights,tourism.attraction"

# The last Nominatim call time (time.monotonic), guarded by the lock.
_nominatim_lock = threading.Lock()
_nominatim_last_call = 0.0


def categories_for(interest: str) -> str:
    """The Geoapify categories for an interest, e.g. "food" → "catering.restaurant,…".
    Unknown interests get the general sights and attractions."""
    words = re.findall(r"[a-z]+", interest.lower())
    for keyword, categories in INTEREST_CATEGORIES:
        if any(word.startswith(keyword) for word in words):
            return categories
    return DEFAULT_CATEGORIES


def geocode(query: str, client: httpx.Client | None = None, precise: bool = False) -> ToolResult:
    """Coordinates for a place or city, e.g. "San Jose, CA" or "SJC airport, San Jose".

    Data: {"name", "address", "lat", "lng", "source"} with source "Geoapify" or "Nominatim".
    Uses Geoapify when GEOAPIFY_KEY is set, and Nominatim when there is no key or Geoapify
    fails or finds nothing. Live results are cached for 30 days (Nominatim's policy asks for
    caching); errors are not. Mock mode: an unknown query falls back to the first mock city.
    `precise=True` (a hotel or airport) treats a city-level match as not found, so the stop isn't
    pinned at the city centre; mock mode ignores it (the mocks are all cities).
    """
    query = query.strip()
    if not query:
        return tool_error("No place name given.")

    if is_mock():
        try:
            return tool_ok(_mock_geocode(query))
        except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
            return tool_error(f"Place lookup failed: {describe_error(error)}")

    cache_args: dict[str, Any] = {"query": query.lower()}
    if precise:
        cache_args["precise"] = True  # a city match cached for a city lookup mustn't be reused
    cached = cache_get("place_geocode", cache_args)
    if cached is not None:
        return tool_ok(cached)

    data = None
    key = get_settings().geoapify_key
    if key:
        try:
            data = _geoapify_geocode(client, query, key, precise)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            data = None  # fall back to Nominatim below
    if data is None:
        try:
            data = _nominatim_geocode(client, query, precise)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
            return tool_error(f"Place lookup failed: {describe_error(error)}")
    if data is None:
        return tool_error(f"Place not found: {query}")

    cache_set("place_geocode", cache_args, data, GEOCODE_TTL_SECONDS)
    return tool_ok(data)


def search(
    lat: float, lng: float, interest: str, limit: int = 8, client: httpx.Client | None = None
) -> ToolResult:
    """Places near a point for one interest, nearest first.

    Data: a list of {"id", "name", "address", "lat", "lng", "category", "rating"}, where `id`
    is "geoapify:<place_id>" and `rating` is null when Geoapify has none. Needs GEOAPIFY_KEY in
    live mode. Live results are cached for 7 days.
    """
    categories = categories_for(interest)

    if is_mock():
        try:
            features = _mock_features(categories)
            return tool_ok(_normalize_places(features, categories)[:limit])
        except (OSError, ValueError, KeyError, TypeError) as error:
            return tool_error(f"Place search failed: {describe_error(error)}")

    key = get_settings().geoapify_key
    if not key:
        return tool_error("Place search needs GEOAPIFY_KEY.")

    cache_args = {"lat": lat, "lng": lng, "categories": categories, "limit": limit}
    cached = cache_get("places", cache_args)
    if cached is not None:
        return tool_ok(cached)

    params = {
        "categories": categories,
        "filter": f"circle:{lng},{lat},{SEARCH_RADIUS_METERS}",
        "bias": f"proximity:{lng},{lat}",
        "limit": limit,
        "apiKey": key,
    }
    try:
        payload = get_json(client, GEOAPIFY_PLACES_URL, params)
        places = _normalize_places(payload["features"], categories)
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        return tool_error(f"Place search failed: {describe_error(error)}")

    cache_set("places", cache_args, places, PLACES_TTL_SECONDS)
    return tool_ok(places)


def normalize_place(properties: dict[str, Any], categories: str) -> dict[str, Any]:
    """One Geoapify feature's `properties` in our shape (see `search`)."""
    rating = properties.get("rating")
    return {
        "id": f"geoapify:{properties['place_id']}",
        "name": properties["name"],
        "address": properties.get("address_line2") or properties.get("formatted"),
        "lat": properties["lat"],
        "lng": properties["lon"],
        "category": _pick_category(properties.get("categories", []), categories),
        "rating": rating if isinstance(rating, (int, float)) else None,
    }


def _normalize_places(features: list[dict[str, Any]], categories: str) -> list[dict[str, Any]]:
    # Unnamed results (a bare "restaurant" pin) are no use in a plan, so they are skipped.
    return [
        normalize_place(feature["properties"], categories)
        for feature in features
        if feature["properties"].get("name")
    ]


def _pick_category(place_categories: list[str], categories: str) -> str | None:
    """The most specific of the place's categories that falls under a requested one, e.g.
    "catering.restaurant.pizza" for a "catering.restaurant" search."""
    wanted = categories.split(",")
    matching = [c for c in place_categories if any(_under(c, w) for w in wanted)]
    if matching:
        return max(matching, key=lambda c: c.count("."))
    return place_categories[0] if place_categories else None


def _under(category: str, parent: str) -> bool:
    return category == parent or category.startswith(parent + ".")


def _geoapify_geocode(
    client: httpx.Client | None, query: str, key: str, precise: bool = False
) -> dict[str, Any] | None:
    params = {"text": query, "format": "json", "limit": 1, "apiKey": key}
    results = get_json(client, GEOAPIFY_GEOCODE_URL, params).get("results") or []
    if not results:
        return None
    if precise and results[0].get("result_type") in AREA_RESULT_TYPES:
        return None
    return _geoapify_result(results[0])


def _geoapify_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": result.get("name") or result.get("city") or result["formatted"],
        "address": result.get("formatted"),
        "lat": result["lat"],
        "lng": result["lon"],
        "source": "Geoapify",
    }


def _nominatim_geocode(
    client: httpx.Client | None, query: str, precise: bool = False
) -> dict[str, Any] | None:
    global _nominatim_last_call
    params = {"q": query, "format": "jsonv2", "limit": 1}
    with _nominatim_lock:
        wait = _nominatim_last_call + NOMINATIM_INTERVAL_SECONDS - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            results = get_json(client, NOMINATIM_URL, params, headers=NOMINATIM_HEADERS)
        finally:
            _nominatim_last_call = time.monotonic()
    if not isinstance(results, list):
        raise ValueError("unexpected response")
    if not results:
        return None
    result = results[0]
    if precise and {result.get("addresstype"), result.get("type")} & AREA_RESULT_TYPES:
        return None
    display_name = result["display_name"]
    return {
        "name": result.get("name") or display_name.split(",")[0],
        "address": display_name,
        "lat": float(result["lat"]),  # Nominatim sends coordinates as strings
        "lng": float(result["lon"]),
        "source": "Nominatim",
    }


def _mock_geocode(query: str) -> dict[str, Any]:
    """The first recorded city named by a comma part of the query ("2800 N Terminal Rd,
    Houston, TX" → Houston), else the first city."""
    results = load_mock("places_geocode")["results"]
    for part in query.split(","):
        matches = [r for r in results if r["name"].lower() == part.strip().lower()]
        if matches:
            return _geoapify_result(matches[0])
    return _geoapify_result(results[0])


def _mock_features(categories: str) -> list[dict[str, Any]]:
    """The recorded San Jose places that fall under the requested categories."""
    wanted = categories.split(",")
    features = load_mock("places_search")["features"]
    return [
        feature
        for feature in features
        if any(_under(c, w) for c in feature["properties"]["categories"] for w in wanted)
    ]
