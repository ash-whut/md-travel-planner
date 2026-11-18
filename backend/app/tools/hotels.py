"""Hotels tool: hotel prices from SerpApi Google Hotels, with a no-price places fallback.

SerpApi's free plan is about 250 searches a month (step 37), so live results are cached for
6 h by (city, check_in, check_out) only, and the registry allows one hotel search per city per
plan (`registry.PlanLimits`). Without a key, or when the quota is used up, the tool falls back
to lodging places from the places tool, with no prices (`price_source: "none"`).
`search` returns a `ToolResult` and never raises.
"""

from datetime import date, datetime, timezone
from typing import Any

import httpx

from app.core.config import get_settings
from app.tools import places
from app.tools.common import (
    HOTELS_TTL_SECONDS,
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

SERPAPI_URL = "https://serpapi.com/search.json"
SORT_LOWEST_PRICE = 3  # SerpApi google_hotels `sort_by`
CURRENCY = "USD"
# The cheapest results are often poorly rated (the step 37 check's cheapest had 1.8), so keep
# only well-rated ones, cheapest first, and let compose pick among a few.
MIN_RATING = 3.5
MAX_RESULTS = 5
PRICE_SOURCE_TOOL = "serpapi_google_hotels"
PRICE_SOURCE_NONE = "none"
LODGING_INTEREST = "lodging"  # places.categories_for maps it to accommodation categories


def search(
    city: str,
    check_in: str,
    check_out: str,
    adults: int = 1,
    budget_level: str | None = None,
    client: httpx.Client | None = None,
) -> ToolResult:
    """Hotels in a city for the given ISO dates, e.g. search("San Jose, CA", "2027-03-05",
    "2027-03-07").

    Data: a list of {"id", "name", "address", "lat", "lng", "rating", "price_per_night",
    "total_price", "price_source", "price_as_of", "link"}. Prices are Money dicts
    ({"amount", "currency"}) or null; `price_as_of` is the UTC time SerpApi was asked (ISO, "Z").
    SerpApi results are sorted by lowest price, keep only ratings ≥ MIN_RATING (all of them if
    none qualify) and are cut to MAX_RESULTS; `budget_level="splurge"` orders them by rating
    instead. Without SERPAPI_KEY, or when the quota is used up, the items are lodging places
    with null prices and `price_source: "none"`. Mock mode returns the recorded San Jose
    search for any city.
    """
    city = city.strip()
    if not city:
        return tool_error("No city given.")
    try:
        if date.fromisoformat(check_out) <= date.fromisoformat(check_in):
            return tool_error("check_out must be after check_in.")
    except (TypeError, ValueError):
        return tool_error("Dates must be YYYY-MM-DD.")

    if is_mock():
        try:
            hotels = normalize_hotels(load_mock("hotels_search")["properties"], now_iso())
        except (OSError, ValueError, KeyError, TypeError) as error:
            return tool_error(f"Hotel search failed: {describe_error(error)}")
        return tool_ok(_order(hotels, budget_level))

    key = get_settings().serpapi_key
    if not key:
        return lodging_fallback(city, client)

    cache_args = {"city": city.lower(), "check_in": check_in, "check_out": check_out}
    cached = cache_get("hotels", cache_args)
    if cached is not None:
        return tool_ok(_order(cached, budget_level))

    params = {
        "engine": "google_hotels",
        "q": city,
        "check_in_date": check_in,
        "check_out_date": check_out,
        "adults": adults,
        "currency": CURRENCY,
        "gl": "us",
        "hl": "en",
        "sort_by": SORT_LOWEST_PRICE,
        "api_key": key,
    }
    try:
        payload = get_json(client, SERPAPI_URL, params)
        if payload.get("error"):
            if _quota_used_up(str(payload["error"])):
                return lodging_fallback(city, client)
            return tool_error(f"Hotel search failed: {payload['error']}")
        hotels = normalize_hotels(payload.get("properties") or [], now_iso())
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 429:  # SerpApi: out of searches (or hourly limit)
            return lodging_fallback(city, client)
        return tool_error(f"Hotel search failed: {describe_error(error)}")
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as error:
        return tool_error(f"Hotel search failed: {describe_error(error)}")

    cache_set("hotels", cache_args, hotels, HOTELS_TTL_SECONDS)
    return tool_ok(_order(hotels, budget_level))


def normalize_hotel(prop: dict[str, Any], price_as_of: str) -> dict[str, Any]:
    """One SerpApi `properties` entry in our shape (see `search`)."""
    gps = prop.get("gps_coordinates") or {}
    rating = prop.get("overall_rating")
    token = prop.get("property_token")
    return {
        "id": f"serpapi:{token}" if token else None,
        "name": prop["name"],
        "address": None,  # Google Hotels results carry no street address
        "lat": gps.get("latitude"),
        "lng": gps.get("longitude"),
        "rating": rating if isinstance(rating, (int, float)) else None,
        "price_per_night": _money((prop.get("rate_per_night") or {}).get("extracted_lowest")),
        "total_price": _money((prop.get("total_rate") or {}).get("extracted_lowest")),
        "price_source": PRICE_SOURCE_TOOL,
        "price_as_of": price_as_of,
        "link": prop.get("link"),
    }


def normalize_hotels(properties: list[dict[str, Any]], price_as_of: str) -> list[dict[str, Any]]:
    """Normalize SerpApi properties (already cheapest first) and keep the well-rated ones: at
    most MAX_RESULTS with rating ≥ MIN_RATING, or the first MAX_RESULTS if none qualify."""
    hotels = [normalize_hotel(prop, price_as_of) for prop in properties if prop.get("name")]
    rated = [h for h in hotels if h["rating"] is not None and h["rating"] >= MIN_RATING]
    return (rated or hotels)[:MAX_RESULTS]


def lodging_fallback(city: str, client: httpx.Client | None = None) -> ToolResult:
    """Lodging places near the city from the places tool, in the hotel shape with no prices
    (`price_source: "none"`). Used when SerpApi has no key or no quota left."""
    located = places.geocode(city, client=client)
    if not located.ok:
        return located
    found = places.search(
        located.data["lat"], located.data["lng"], LODGING_INTEREST, limit=MAX_RESULTS, client=client
    )
    if not found.ok:
        return found
    return tool_ok([_unpriced(place) for place in found.data])


def now_iso() -> str:
    """The current UTC time as an ISO string with a "Z", e.g. "2026-11-01T18:04:05Z"."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _unpriced(place: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": place["id"],
        "name": place["name"],
        "address": place["address"],
        "lat": place["lat"],
        "lng": place["lng"],
        "rating": place["rating"],
        "price_per_night": None,
        "total_price": None,
        "price_source": PRICE_SOURCE_NONE,
        "price_as_of": None,
        "link": None,
    }


def _money(amount: Any) -> dict[str, Any] | None:
    if isinstance(amount, (int, float)) and amount > 0:
        return {"amount": amount, "currency": CURRENCY}
    return None


def _order(hotels: list[dict[str, Any]], budget_level: str | None) -> list[dict[str, Any]]:
    """Cheapest first (as cached), or best rated first for a splurge trip."""
    if budget_level == "splurge":
        return sorted(hotels, key=lambda h: h["rating"] or 0, reverse=True)
    return hotels


def _quota_used_up(message: str) -> bool:
    # SerpApi's wording, e.g. "Your account has run out of searches."
    return "run out of searches" in message.lower()
