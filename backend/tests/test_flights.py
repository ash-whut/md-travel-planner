"""Step 49: search_flights tool (SerpApi Google Flights + mock mode).

All tests run offline using the recorded mock in tools/mocks/flights_search.json.
Live tests are marked @pytest.mark.live and skipped by default.
"""

import pytest
import httpx

from app.tools.flights import normalize_flight, normalize_flights, search, _sort, now_iso
from app.tools.registry import TOOLS, run_tool, PlanLimits, route_key


# ---- normalize_flight ----------------------------------------------------------------


def test_normalize_flight_extracts_fields_from_first_and_last_leg() -> None:
    itinerary = {
        "flights": [
            {
                "departure_airport": {"name": "IAH", "id": "IAH", "time": "2027-03-05 06:15"},
                "arrival_airport": {"name": "SJC", "id": "SJC", "time": "2027-03-05 08:45"},
                "airline": "United Airlines",
                "flight_number": "UA 1234",
            }
        ],
        "layovers": [],
        "total_duration": 210,
        "price": 189,
        "booking_token": "tok1",
    }
    result = normalize_flight(itinerary, "2027-01-01T00:00:00Z")
    assert result["airline"] == "United Airlines"
    assert result["flight_number"] == "UA 1234"
    assert result["departure_time"] == "2027-03-05 06:15"
    assert result["arrival_time"] == "2027-03-05 08:45"
    assert result["duration_min"] == 210
    assert result["stops"] == 0
    assert result["price"] == {"amount": 189, "currency": "USD"}
    assert result["price_as_of"] == "2027-01-01T00:00:00Z"
    assert "Flights+to+SJC+from+IAH+on+2027-03-05" in result["booking_url"]



def test_normalize_flight_null_price_gives_none() -> None:
    itinerary = {"flights": [], "layovers": [], "total_duration": 180, "price": None, "booking_token": ""}
    result = normalize_flight(itinerary, "2027-01-01T00:00:00Z")
    assert result["price"] is None


def test_normalize_flights_combines_best_and_other() -> None:
    payload = {
        "best_flights": [{"flights": [], "layovers": [], "total_duration": 100, "price": 100, "booking_token": "a"}],
        "other_flights": [{"flights": [], "layovers": [], "total_duration": 200, "price": 200, "booking_token": "b"}],
    }
    results = normalize_flights(payload, "2027-01-01T00:00:00Z")
    assert len(results) == 2


# ---- _sort ---------------------------------------------------------------------------


def test_sort_puts_cheapest_nonstop_first() -> None:
    flights = [
        {"price": {"amount": 300, "currency": "USD"}, "stops": 1, "duration_min": 400},
        {"price": {"amount": 189, "currency": "USD"}, "stops": 0, "duration_min": 210},
        {"price": {"amount": 215, "currency": "USD"}, "stops": 0, "duration_min": 210},
    ]
    sorted_flights = _sort(flights)
    assert sorted_flights[0]["price"]["amount"] == 189


def test_sort_puts_no_price_flights_last() -> None:
    flights = [
        {"price": None, "stops": 0, "duration_min": 100},
        {"price": {"amount": 500, "currency": "USD"}, "stops": 0, "duration_min": 100},
    ]
    sorted_flights = _sort(flights)
    assert sorted_flights[0]["price"]["amount"] == 500
    assert sorted_flights[1]["price"] is None


# ---- search (mock mode) --------------------------------------------------------------


def test_search_mock_returns_ok_with_flights() -> None:
    result = search("College Station, TX", "San Jose, CA", "2027-03-05", "2027-03-07")
    assert result.ok
    assert isinstance(result.data, list)
    assert len(result.data) >= 1
    # Each flight has the expected keys.
    for flight in result.data:
        assert "airline" in flight
        assert "price_as_of" in flight


def test_search_mock_caps_at_max_results() -> None:
    result = search("A", "B", "2027-03-05", "2027-03-07")
    assert result.ok
    assert len(result.data) <= 5  # MAX_RESULTS


def test_search_returns_error_for_missing_origin() -> None:
    result = search("", "San Jose, CA", "2027-03-05", "2027-03-07")
    assert not result.ok
    assert "required" in result.error.lower()


def test_search_returns_error_for_bad_dates() -> None:
    result = search("IAH", "SJC", "not-a-date", "2027-03-07")
    assert not result.ok


def test_search_returns_error_when_return_before_departure() -> None:
    result = search("IAH", "SJC", "2027-03-07", "2027-03-05")
    assert not result.ok


# ---- registry entry ------------------------------------------------------------------


def test_search_flights_is_registered() -> None:
    assert "search_flights" in TOOLS


def test_registry_search_flights_calls_through() -> None:
    result = run_tool("search_flights", {
        "origin": "College Station, TX",
        "destination": "San Jose, CA",
        "departure_date": "2027-03-05",
        "return_date": "2027-03-07",
    })
    assert result.ok


def test_registry_missing_args_gives_error() -> None:
    result = run_tool("search_flights", {"origin": "IAH"})
    assert not result.ok


def test_plan_limits_allows_one_route_per_plan() -> None:
    limits = PlanLimits()
    args = {"origin": "College Station, TX", "destination": "San Jose, CA",
            "departure_date": "2027-03-05", "return_date": "2027-03-07"}
    assert limits.allow("search_flights", args) is True
    assert limits.allow("search_flights", args) is False  # second call blocked


def test_plan_limits_different_routes_are_independent() -> None:
    limits = PlanLimits()
    args1 = {"origin": "Houston, TX", "destination": "San Jose, CA",
              "departure_date": "2027-03-05", "return_date": "2027-03-07"}
    args2 = {"origin": "Austin, TX", "destination": "San Jose, CA",
              "departure_date": "2027-03-05", "return_date": "2027-03-07"}
    assert limits.allow("search_flights", args1) is True
    assert limits.allow("search_flights", args2) is True


def test_route_key_normalises_city_names() -> None:
    args = {"origin": "College Station, TX", "destination": "San Jose, CA"}
    assert route_key(args) == "college station>san jose"


# ---- live (skipped by default) -------------------------------------------------------


@pytest.mark.live
def test_live_serpapi_flight_search() -> None:
    import os
    if not os.getenv("SERPAPI_KEY"):
        pytest.skip("SERPAPI_KEY not set")
    # Use a real near-future date range; the actual result varies.
    result = search("Houston, TX", "San Jose, CA", "2027-06-01", "2027-06-03")
    assert result.ok, result.error
    assert result.data
    assert all(f.get("price_as_of") for f in result.data)
