"""Deep links (contracts §6): built by code from stop names, cities and dates, never by the LLM.

Every parameter is URL-encoded (spaces become %20). None of these links needs an API key.
"""

from datetime import date
from urllib.parse import quote, urlencode

GOOGLE_FLIGHTS_URL = "https://www.google.com/travel/flights"
GOOGLE_HOTELS_URL = "https://www.google.com/travel/hotels"
BOOKING_COM_URL = "https://www.booking.com/searchresults.html"
GOOGLE_SEARCH_URL = "https://www.google.com/search"
GOOGLE_MAPS_SEARCH_URL = "https://www.google.com/maps/search/"


def _query(params: dict[str, str | int]) -> str:
    """A query string with every value percent-encoded (%20 for spaces, not "+")."""
    return urlencode(params, quote_via=quote)


def google_flights_url(origin: str, destination: str, depart: date, return_date: date) -> str:
    """A round-trip Google Flights search, e.g. "Flights from IAH to San Jose Airport on
    2027-03-05 returning 2027-03-07"."""
    text = (
        f"Flights from {origin} to {destination} "
        f"on {depart.isoformat()} returning {return_date.isoformat()}"
    )
    return f"{GOOGLE_FLIGHTS_URL}?{_query({'q': text})}"


def google_hotels_url(hotel_name: str, city: str) -> str:
    """A Google Hotels search for the hotel. (SerpApi's own `link` is the hotel's website, so
    postprocess shows it separately as "Hotel site".)"""
    return f"{GOOGLE_HOTELS_URL}?{_query({'q': f'{hotel_name} {city}'})}"


def booking_com_url(
    hotel_name: str, city: str, check_in: date, check_out: date, adults: int
) -> str:
    """A Booking.com search for the hotel on the stay's dates."""
    params: dict[str, str | int] = {
        "ss": f"{hotel_name}, {city}",
        "checkin": check_in.isoformat(),
        "checkout": check_out.isoformat(),
        "group_adults": adults,
    }
    return f"{BOOKING_COM_URL}?{_query(params)}"


def tickets_url(stop_name: str, city: str) -> str:
    """A Google search for an activity's tickets."""
    return f"{GOOGLE_SEARCH_URL}?{_query({'q': f'{stop_name} {city} tickets'})}"


def map_url(name: str, address_or_city: str) -> str:
    """A plain Google Maps search link for a stop (no API key needed)."""
    return f"{GOOGLE_MAPS_SEARCH_URL}?{_query({'api': 1, 'query': f'{name}, {address_or_city}'})}"
