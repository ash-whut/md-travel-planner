"""Weather tool (Open-Meteo, free, no key): city geocoding and a per-day forecast in °F.

Trips that end within the 16-day forecast window use the forecast API. Later trips get a
climate average instead: the same dates over the last 3 years from the archive API.
Both functions return a `ToolResult` and never raise.
"""

from collections import Counter
from datetime import date, timedelta
from typing import Any

import httpx

from app.tools.common import (
    GEOCODE_TTL_SECONDS,
    WEATHER_TTL_SECONDS,
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

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

FORECAST_DAYS = 16  # today plus 15 days
CLIMATE_YEARS = 3
ARCHIVE_LAG_DAYS = 7  # the archive trails today by about 5 days
DAILY_FIELDS = "temperature_2m_max,temperature_2m_min,weather_code"

# WMO weather code → (condition, icon). https://open-meteo.com/en/docs ("WMO Weather
# interpretation codes").
WMO_CODES: dict[int, tuple[str, str]] = {
    0: ("sunny", "☀️"),
    1: ("mostly sunny", "🌤️"),
    2: ("partly cloudy", "⛅"),
    3: ("cloudy", "☁️"),
    45: ("foggy", "🌫️"),
    48: ("foggy", "🌫️"),
    51: ("drizzle", "🌦️"),
    53: ("drizzle", "🌦️"),
    55: ("drizzle", "🌦️"),
    56: ("drizzle", "🌦️"),
    57: ("drizzle", "🌦️"),
    61: ("rain", "🌧️"),
    63: ("rain", "🌧️"),
    65: ("rain", "🌧️"),
    66: ("rain", "🌧️"),
    67: ("rain", "🌧️"),
    80: ("rain", "🌧️"),
    81: ("rain", "🌧️"),
    82: ("rain", "🌧️"),
    71: ("snow", "❄️"),
    73: ("snow", "❄️"),
    75: ("snow", "❄️"),
    77: ("snow", "❄️"),
    85: ("snow", "❄️"),
    86: ("snow", "❄️"),
    95: ("thunderstorm", "⛈️"),
    96: ("thunderstorm", "⛈️"),
    99: ("thunderstorm", "⛈️"),
}
UNKNOWN_WEATHER = ("unknown", "🌡️")

# One day from the API: (high °F, low °F, WMO code); any of them may be missing.
DailyRow = tuple[float | None, float | None, int | None]


def wmo_condition(code: int | None) -> tuple[str, str]:
    """The (condition, icon) for a WMO weather code, e.g. 0 → ("sunny", "☀️")."""
    if code is None:
        return UNKNOWN_WEATHER
    return WMO_CODES.get(code, UNKNOWN_WEATHER)


def uses_forecast(end: date, today: date) -> bool:
    """True when the whole trip is inside the forecast window; otherwise use the climate."""
    return end <= today + timedelta(days=FORECAST_DAYS - 1)


def geocode_city(name: str, client: httpx.Client | None = None) -> ToolResult:
    """Coordinates for a city name. Data: {"name", "lat", "lng", "country", "admin1"}.

    Open-Meteo matches plain names only, so "San Jose, CA" is searched as "San Jose" and the
    first (most populous) match wins. Live results are cached for 30 days; errors are not.

    Mock mode: an unknown city falls back to the first mock city (San Jose). Its coordinates
    are fine for mock weather but must not be trusted for map pins.
    """
    query = name.split(",")[0].strip()
    if not query:
        return tool_error("No city name given.")

    mock = is_mock()
    cache_args = {"name": query.lower()}
    if not mock:
        cached = cache_get("geocode", cache_args)
        if cached is not None:
            return tool_ok(cached)

    try:
        if mock:
            results = load_mock("weather_geocode").get("results", [])
            matches = [r for r in results if r["name"].lower() == query.lower()]
            # Any other city falls back to the first mock city, so mock trips still get weather.
            chosen = matches or results[:1]
        else:
            params = {"name": query, "count": 1, "language": "en", "format": "json"}
            chosen = _get_json(client, GEOCODING_URL, params).get("results") or []
        if not chosen:
            return tool_error(f"City not found: {query}")
        city = chosen[0]
        data = {
            "name": city["name"],
            "lat": city["latitude"],
            "lng": city["longitude"],
            "country": city.get("country"),
            "admin1": city.get("admin1"),
        }
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        return tool_error(f"City lookup failed: {describe_error(error)}")

    if not mock:
        cache_set("geocode", cache_args, data, GEOCODE_TTL_SECONDS)
    return tool_ok(data)


def get_weather(
    lat: float,
    lng: float,
    start: date,
    end: date,
    today: date | None = None,
    client: httpx.Client | None = None,
) -> ToolResult:
    """Weather for each trip day, start to end inclusive.

    Data: a list of {"date", "high_f", "low_f", "condition", "icon", "source"}, where source
    is "forecast" or "climate". `today` and `client` exist for tests.
    """
    if end < start:
        return tool_error("The trip ends before it starts.")
    today = today or date.today()
    source = "forecast" if uses_forecast(end, today) else "climate"
    dates = [start + timedelta(days=i) for i in range((end - start).days + 1)]

    if is_mock():
        try:
            return tool_ok(_mock_days(dates, source))
        except (OSError, ValueError, KeyError, TypeError) as error:
            return tool_error(f"Weather is unavailable: {describe_error(error)}")

    cache_args = {"lat": lat, "lng": lng, "start": start, "end": end, "source": source}
    cached = cache_get("weather", cache_args)
    if cached is not None:
        return tool_ok(cached)

    try:
        if source == "forecast":
            series = [_fetch_daily(client, FORECAST_URL, lat, lng, start, end)]
        else:
            series = [
                _fetch_daily(client, ARCHIVE_URL, lat, lng, year_start, year_start + (end - start))
                for year_start in _climate_starts(start, end, today)
            ]
        days = _build_days(dates, series, source)
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        return tool_error(f"Weather is unavailable: {describe_error(error)}")

    cache_set("weather", cache_args, days, WEATHER_TTL_SECONDS)
    return tool_ok(days)


def _climate_starts(start: date, end: date, today: date) -> list[date]:
    """The trip's start date in each of the last 3 years the archive already covers."""
    starts: list[date] = []
    trip_length = end - start
    years_back = 1
    while len(starts) < CLIMATE_YEARS:
        year_start = _years_earlier(start, years_back)
        if year_start + trip_length < today - timedelta(days=ARCHIVE_LAG_DAYS):
            starts.append(year_start)
        years_back += 1
    return starts


def _years_earlier(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:  # Feb 29 in a year without one
        return day.replace(year=day.year - years, day=28)


def _fetch_daily(
    client: httpx.Client | None, url: str, lat: float, lng: float, start: date, end: date
) -> list[DailyRow]:
    params = {
        "latitude": lat,
        "longitude": lng,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "daily": DAILY_FIELDS,
        "temperature_unit": "fahrenheit",
        "timezone": "auto",
    }
    return _parse_daily(_get_json(client, url, params))


def _get_json(client: httpx.Client | None, url: str, params: dict[str, Any]) -> dict[str, Any]:
    """GET a JSON object. Raises httpx.HTTPError on network or HTTP errors."""
    payload = get_json(client, url, params)
    if not isinstance(payload, dict):
        raise ValueError("unexpected response")
    return payload


def _parse_daily(payload: dict[str, Any]) -> list[DailyRow]:
    """The rows of an Open-Meteo `daily` block, in date order."""
    daily = payload["daily"]
    highs = daily["temperature_2m_max"]
    lows = daily["temperature_2m_min"]
    codes = daily["weather_code"]
    if not (len(highs) == len(lows) == len(codes)) or not highs:
        raise ValueError("incomplete daily data")
    return list(zip(highs, lows, codes))


def _build_days(dates: list[date], series: list[list[DailyRow]], source: str) -> list[dict[str, Any]]:
    """One weather dict per trip date. Several series (climate years) are averaged: the mean
    high and low, and the most common weather code."""
    days = []
    for i, day in enumerate(dates):
        rows = [rows[i] for rows in series if i < len(rows)]
        highs = [row[0] for row in rows if row[0] is not None]
        lows = [row[1] for row in rows if row[1] is not None]
        codes = [row[2] for row in rows if row[2] is not None]
        if not highs or not lows:
            raise ValueError(f"no temperatures for {day.isoformat()}")
        code = Counter(codes).most_common(1)[0][0] if codes else None
        condition, icon = wmo_condition(code)
        days.append(
            {
                "date": day.isoformat(),
                "high_f": round(sum(highs) / len(highs)),
                "low_f": round(sum(lows) / len(lows)),
                "condition": condition,
                "icon": icon,
                "source": source,
            }
        )
    return days


def _mock_days(dates: list[date], source: str) -> list[dict[str, Any]]:
    """Recorded rows from `weather_{source}.json`, reused in turn for the requested dates."""
    rows = _parse_daily(load_mock(f"weather_{source}"))
    cycled = [rows[i % len(rows)] for i in range(len(dates))]
    return _build_days(dates, [cycled], source)
