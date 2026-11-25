"""Flights tool: flight fares from SerpApi Google Flights.

SerpApi's free plan is about 250 searches a month, so live results are cached for
6 h by (origin, destination, departure, return) only, and the registry allows one flight
search per origin-destination pair per plan. Without a key, or when the quota is used up,
the tool returns an error (no fallback for flights). `search` returns a `ToolResult` and
never raises.
"""

from datetime import date, datetime, timezone
from typing import Any

import httpx

from urllib.parse import quote_plus

from app.core.config import get_settings
from app.tools.common import (
    FLIGHTS_TTL_SECONDS,
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
CURRENCY = "USD"
MAX_RESULTS = 5
PRICE_SOURCE_TOOL = "serpapi_google_flights"
GOOGLE_FLIGHTS_URL = "https://www.google.com/travel/flights"


def search(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str,
    adults: int = 1,
    client: httpx.Client | None = None,
) -> ToolResult:
    """Flights between two cities for the given ISO dates, e.g.
    search("College Station, TX", "San Jose, CA", "2027-03-05", "2027-03-07").

    Data: a list of {"id", "airline", "flight_number", "departure_time", "arrival_time",
    "duration_min", "stops", "price", "price_as_of", "booking_url"}. `price` is a Money
    dict ({"amount", "currency"}) or null; `price_as_of` is the UTC time SerpApi was asked
    (ISO, "Z"). Results are sorted by a balance of price, stops and duration, cut to
    MAX_RESULTS. Without SERPAPI_KEY, or when the quota is used up, the result is not ok.
    Mock mode returns the recorded IAH→SJC search for any route.
    """
    origin = origin.strip()
    destination = destination.strip()
    if not origin or not destination:
        return tool_error("Origin and destination are required.")
    try:
        dep = date.fromisoformat(departure_date)
        ret = date.fromisoformat(return_date)
        if ret <= dep:
            return tool_error("return_date must be after departure_date.")
    except (TypeError, ValueError):
        return tool_error("Dates must be YYYY-MM-DD.")

    if is_mock():
        try:
            payload = load_mock("flights_search")
            flights = normalize_flights(payload, now_iso())
        except (OSError, ValueError, KeyError, TypeError) as error:
            return tool_error(f"Flight search failed: {describe_error(error)}")
        return tool_ok(_sort(flights)[:MAX_RESULTS])

    key = get_settings().serpapi_key
    if not key:
        return tool_error("No SerpApi key configured for flight search.")

    cache_args = {
        "origin": origin.lower(),
        "destination": destination.lower(),
        "departure_date": departure_date,
        "return_date": return_date,
    }
    cached = cache_get("flights", cache_args)
    if cached is not None:
        return tool_ok(cached)
    
    dep_code = _resolve_iata(origin, key, client)
    arr_code = _resolve_iata(destination, key, client)
    if not dep_code or not arr_code:
        return tool_error(f"Could not find airport codes for '{origin}' -> '{destination}'.")
    params = {
        "engine": "google_flights",
        "departure_id": dep_code,
        "arrival_id": arr_code,
        "outbound_date": departure_date,
        "return_date": return_date,
        "adults": adults,
        "currency": CURRENCY,
        "gl": "us",
        "hl": "en",
        "type": "1",  # round trip
        "api_key": key,
    }
    try:
        payload = get_json(client, SERPAPI_URL, params)
        if payload.get("error"):
            if _quota_used_up(str(payload["error"])):
                return tool_error("Flight search quota used up.")
            return tool_error(f"Flight search failed: {payload['error']}")
        flights = normalize_flights(payload, now_iso())
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 429:
            return tool_error("Flight search quota used up.")
        return tool_error(f"Flight search failed: {describe_error(error)}")
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as error:
        return tool_error(f"Flight search failed: {describe_error(error)}")

    sorted_flights = _sort(flights)[:MAX_RESULTS]
    if sorted_flights and sorted_flights[0].get("departure_token"):
       ret_params = {
           **params,
           "departure_token": sorted_flights[0]["departure_token"],
       }
       try:
           ret_payload = get_json(client, SERPAPI_URL, ret_params)
           ret_options = normalize_flights(ret_payload, now_iso())
           ret_sorted = _sort(ret_options)
           if ret_sorted:
               best_ret = ret_sorted[0]
               sorted_flights[0]["return_flight_number"] = best_ret.get("flight_number")
               sorted_flights[0]["return_departure_time"] = best_ret.get("departure_time")
               sorted_flights[0]["return_arrival_time"] = best_ret.get("arrival_time")
               sorted_flights[0]["return_duration_min"] = best_ret.get("duration_min")
               # Update total round-trip price if the return leg has a higher/updated price
               if best_ret.get("price"):
                   sorted_flights[0]["price"] = best_ret["price"]
               # Keep top 3 return time choices so the user can swap flight times in chat
               sorted_flights[0]["return_options"] = [
                   {
                       "flight_number": r.get("flight_number"),
                       "departure_time": r.get("departure_time"),
                       "arrival_time": r.get("arrival_time"),
                       "stops": r.get("stops"),
                       "price": r.get("price"),
                   }
                   for r in ret_sorted[:3]
               ]
       except Exception:
           pass  # keep outbound flight data if return lookup fails
    cache_set("flights", cache_args, sorted_flights, FLIGHTS_TTL_SECONDS)
    return tool_ok(sorted_flights)


def normalize_flight(itinerary: dict[str, Any], price_as_of: str) -> dict[str, Any]:
    """One SerpApi flight itinerary (from best_flights or other_flights) in our shape."""
    legs = itinerary.get("flights") or []
    first_leg = legs[0] if legs else {}
    last_leg = legs[-1] if legs else {}
    dep_airport = first_leg.get("departure_airport") or {}
    arr_airport = last_leg.get("arrival_airport") or {}
    airline = first_leg.get("airline") or ""
    flight_number = first_leg.get("flight_number") or ""
    total_duration = itinerary.get("total_duration")
    layovers = itinerary.get("layovers") or []
    price_raw = itinerary.get("price")
    token = itinerary.get("booking_token") or ""    
    dep_code = dep_airport.get("id") or ""
    arr_code = arr_airport.get("id") or ""
    dep_date = str(dep_airport.get("time") or "").split(" ")[0]
    if dep_code and arr_code and dep_date:
        q = quote_plus(f"Flights to {arr_code} from {dep_code} on {dep_date}")
        booking_url = f"{GOOGLE_FLIGHTS_URL}?q={q}"
    else:
        booking_url = GOOGLE_FLIGHTS_URL
    return {
        "id": f"serpapi:{token}" if token else None,
        "airline": airline,
        "flight_number": flight_number,
        "departure_time": dep_airport.get("time"),
        "arrival_time": arr_airport.get("time"),
        "duration_min": total_duration,
        "stops": len(layovers),
        "price": _money(price_raw),
        "price_as_of": price_as_of,
        "booking_url": booking_url,
        "departure_token": itinerary.get("departure_token"),
    }


def normalize_flights(payload: dict[str, Any], price_as_of: str) -> list[dict[str, Any]]:
    """Normalize SerpApi best_flights + other_flights into our shape."""
    raw: list[dict[str, Any]] = []
    for itinerary in payload.get("best_flights") or []:
        raw.append(normalize_flight(itinerary, price_as_of))
    for itinerary in payload.get("other_flights") or []:
        raw.append(normalize_flight(itinerary, price_as_of))
    return raw


def _sort(flights: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort by a composite score: balance of price, stops and duration. Flights without a
    price sort last."""
    def score(f: dict[str, Any]) -> tuple[int, float]:
        price = f.get("price")
        if price is None or price.get("amount") is None:
            return (1, float("inf"))
        # Composite: price + penalty for stops and long durations.
        amount = price["amount"]
        stops = f.get("stops") or 0
        duration = f.get("duration_min") or 0
        return (0, amount + stops * 50 + duration * 0.1)

    return sorted(flights, key=score)


def now_iso() -> str:
    """The current UTC time as an ISO string with a "Z", e.g. "2026-11-01T18:04:05Z"."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def _resolve_iata(query: str, api_key: str, client: httpx.Client | None = None) -> str | None:
    """Return a 3-letter uppercase IATA code directly, or resolve a city/airport name via
    SerpApi Google Flights Autocomplete (cached 6h)."""
    cleaned = query.strip()
    if len(cleaned) == 3 and cleaned.isalpha():
        return cleaned.upper()
    # Take the city name before any comma (e.g. "San Jose, CA" -> "San Jose")
    city_query = cleaned.split(",")[0].strip()
    if not city_query:
        return None
    cache_args = {"iata_query": city_query.lower()}
    cached = cache_get("flights_iata", cache_args)
    if isinstance(cached, str) and len(cached) == 3:
        return cached
    try:
        data = get_json(
            client,
            SERPAPI_URL,
            {"engine": "google_flights_autocomplete", "q": city_query, "api_key": api_key},
        )
        for suggestion in data.get("suggestions") or []:
            # Pick the first airport suggestion or top-level 3-letter code
            code = suggestion.get("id") or ""
            if isinstance(code, str) and len(code) == 3 and code.isalpha():
                cache_set("flights_iata", cache_args, code.upper(), FLIGHTS_TTL_SECONDS)
                return code.upper()
            for airport in suggestion.get("airports") or []:
                acode = airport.get("id") or ""
                if isinstance(acode, str) and len(acode) == 3 and acode.isalpha():
                    cache_set("flights_iata", cache_args, acode.upper(), FLIGHTS_TTL_SECONDS)
                    return acode.upper()
    except Exception:
        return None
    return None

def _money(amount: Any) -> dict[str, Any] | None:
    if isinstance(amount, (int, float)) and amount > 0:
        return {"amount": amount, "currency": CURRENCY}
    return None


def _quota_used_up(message: str) -> bool:
    return "run out of searches" in message.lower()
