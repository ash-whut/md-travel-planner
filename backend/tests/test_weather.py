"""Step 29: the Open-Meteo weather tool. Forecast vs climate chosen by date, WMO mapping,
mock mode, HTTP errors (httpx MockTransport) → ok=False, and one live test (skipped)."""

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import httpx
import pytest

from app.tools import weather
from app.tools.common import ToolResult
from app.tools.weather import geocode_city, get_weather, uses_forecast, wmo_condition

TODAY = date(2026, 3, 1)
LAT, LNG = 37.33, -121.89
DAY_KEYS = {"date", "high_f", "low_f", "condition", "icon", "source"}

Handler = Callable[[httpx.Request], httpx.Response]


def live_http(monkeypatch: pytest.MonkeyPatch, handler: Handler) -> tuple[httpx.Client, list[httpx.Request]]:
    """Switch the tool to live mode with a fake transport; returns the client and a request log."""
    monkeypatch.setattr(weather, "is_mock", lambda: False)
    requests: list[httpx.Request] = []

    def logged(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    return httpx.Client(transport=httpx.MockTransport(logged)), requests


def daily_payload(start: str, highs: list[float], lows: list[float], codes: list[int]) -> dict[str, Any]:
    first = date.fromisoformat(start)
    return {
        "daily": {
            "time": [(first + timedelta(days=i)).isoformat() for i in range(len(highs))],
            "temperature_2m_max": highs,
            "temperature_2m_min": lows,
            "weather_code": codes,
        }
    }


def assert_day_shape(days: Any, source: str) -> None:
    assert isinstance(days, list) and days
    for day in days:
        assert set(day) == DAY_KEYS
        assert day["source"] == source
        assert isinstance(day["high_f"], int) and isinstance(day["low_f"], int)
        assert day["high_f"] >= day["low_f"]
        assert day["condition"] and day["icon"]


# ---- forecast vs climate chosen by date ----

def test_uses_forecast_inside_16_day_window() -> None:
    assert uses_forecast(TODAY, TODAY) is True
    assert uses_forecast(TODAY + timedelta(days=15), TODAY) is True  # last forecast day


def test_uses_climate_beyond_16_day_window() -> None:
    assert uses_forecast(TODAY + timedelta(days=16), TODAY) is False
    assert uses_forecast(TODAY + timedelta(days=200), TODAY) is False


def test_trip_straddling_window_end_uses_climate() -> None:
    # Starts inside the window but ends after it → whole trip falls back to climate.
    start, end = TODAY + timedelta(days=14), TODAY + timedelta(days=17)
    result = get_weather(LAT, LNG, start, end, today=TODAY)
    assert result.ok
    assert {d["source"] for d in result.data} == {"climate"}


# ---- WMO mapping ----

@pytest.mark.parametrize(
    ("code", "condition", "icon"),
    [
        (0, "sunny", "☀️"),
        (1, "mostly sunny", "🌤️"),
        (2, "partly cloudy", "⛅"),
        (3, "cloudy", "☁️"),
        (45, "foggy", "🌫️"),
        (53, "drizzle", "🌦️"),
        (61, "rain", "🌧️"),
        (81, "rain", "🌧️"),
        (73, "snow", "❄️"),
        (95, "thunderstorm", "⛈️"),
    ],
)
def test_wmo_codes_map_to_condition_and_icon(code: int, condition: str, icon: str) -> None:
    assert wmo_condition(code) == (condition, icon)


@pytest.mark.parametrize("code", [None, 4, 42, 100, -1])
def test_unknown_wmo_code_is_unknown(code: int | None) -> None:
    condition, icon = wmo_condition(code)
    assert condition == "unknown"
    assert icon


# ---- mock mode ----

def test_mock_forecast_for_near_trip() -> None:
    start = TODAY + timedelta(days=4)
    result = get_weather(LAT, LNG, start, start + timedelta(days=2), today=TODAY)
    assert isinstance(result, ToolResult) and result.ok
    assert_day_shape(result.data, "forecast")
    assert [d["date"] for d in result.data] == [
        (start + timedelta(days=i)).isoformat() for i in range(3)
    ]
    # Recorded weather_forecast.json: 66.2/48.1 code 0, 68.4/50.3 code 2, 61.0/47.5 code 61.
    assert [(d["high_f"], d["low_f"], d["condition"]) for d in result.data] == [
        (66, 48, "sunny"),
        (68, 50, "partly cloudy"),
        (61, 48, "rain"),
    ]


def test_mock_climate_for_far_trip() -> None:
    start = date(2026, 6, 10)
    result = get_weather(LAT, LNG, start, start + timedelta(days=2), today=TODAY)
    assert result.ok
    assert_day_shape(result.data, "climate")
    # Recorded weather_climate.json: 64.0/46.2 code 1, 65.1/47.0 code 3, 63.3/45.8 code 3.
    assert [(d["high_f"], d["low_f"], d["condition"]) for d in result.data] == [
        (64, 46, "mostly sunny"),
        (65, 47, "cloudy"),
        (63, 46, "cloudy"),
    ]


def test_mock_covers_every_requested_day() -> None:
    start = TODAY + timedelta(days=1)
    result = get_weather(LAT, LNG, start, start + timedelta(days=4), today=TODAY)  # 5 days
    assert result.ok
    assert len(result.data) == 5
    assert result.data[-1]["date"] == (start + timedelta(days=4)).isoformat()


def test_single_day_trip() -> None:
    result = get_weather(LAT, LNG, TODAY, TODAY, today=TODAY)
    assert result.ok
    assert len(result.data) == 1
    assert result.data[0]["date"] == TODAY.isoformat()


def test_end_before_start_is_error() -> None:
    result = get_weather(LAT, LNG, TODAY, TODAY - timedelta(days=1), today=TODAY)
    assert result.ok is False
    assert result.error


def test_mock_mode_never_uses_http(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise AssertionError("mock mode must not make HTTP calls")

    client = httpx.Client(transport=httpx.MockTransport(boom))
    assert get_weather(LAT, LNG, TODAY, TODAY, today=TODAY, client=client).ok
    assert geocode_city("San Jose", client=client).ok


def test_mock_geocode_known_city_strips_region() -> None:
    result = geocode_city("San Jose, CA")
    assert result.ok
    assert result.data["name"] == "San Jose"
    assert result.data["lat"] == pytest.approx(37.339, abs=0.01)
    assert result.data["lng"] == pytest.approx(-121.895, abs=0.01)
    assert result.data["country"] == "United States"
    assert result.data["admin1"] == "California"


def test_mock_geocode_is_case_insensitive() -> None:
    result = geocode_city("san francisco")
    assert result.ok
    assert result.data["name"] == "San Francisco"
    assert result.data["lat"] == pytest.approx(37.77, abs=0.01)


def test_mock_geocode_unknown_city_still_returns_coordinates() -> None:
    result = geocode_city("Austin")
    assert result.ok
    assert isinstance(result.data["lat"], float) and isinstance(result.data["lng"], float)


def test_geocode_empty_name_is_error() -> None:
    assert geocode_city("").ok is False
    assert geocode_city("  , CA").ok is False


# ---- live mode over a fake transport ----

def test_forecast_request_uses_forecast_api_in_fahrenheit(monkeypatch: pytest.MonkeyPatch) -> None:
    start = TODAY + timedelta(days=2)
    end = start + timedelta(days=1)
    payload = daily_payload(start.isoformat(), [70.4, 72.6], [50.0, 51.5], [0, 95])
    client, requests = live_http(monkeypatch, lambda r: httpx.Response(200, json=payload))

    result = get_weather(LAT, LNG, start, end, today=TODAY, client=client)

    assert result.ok
    assert len(requests) == 1
    req = requests[0]
    assert req.url.host == "api.open-meteo.com"
    assert req.url.params["start_date"] == start.isoformat()
    assert req.url.params["end_date"] == end.isoformat()
    assert req.url.params["temperature_unit"] == "fahrenheit"
    assert_day_shape(result.data, "forecast")
    assert [(d["high_f"], d["low_f"], d["condition"]) for d in result.data] == [
        (70, 50, "sunny"),
        (73, 52, "thunderstorm"),
    ]


def test_climate_averages_same_dates_over_last_3_years(monkeypatch: pytest.MonkeyPatch) -> None:
    start, end = date(2026, 6, 10), date(2026, 6, 12)
    by_year = {
        2025: ([60, 70, 80], [40, 50, 60], [0, 61, 3]),
        2024: ([62, 72, 82], [42, 52, 62], [0, 61, 95]),
        2023: ([64, 74, 84], [44, 54, 64], [2, 3, 95]),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        first = request.url.params["start_date"]
        highs, lows, codes = by_year[int(first[:4])]
        return httpx.Response(200, json=daily_payload(first, highs, lows, codes))

    client, requests = live_http(monkeypatch, handler)
    result = get_weather(LAT, LNG, start, end, today=TODAY, client=client)

    assert result.ok, result.error
    assert {r.url.host for r in requests} == {"archive-api.open-meteo.com"}
    assert sorted((r.url.params["start_date"], r.url.params["end_date"]) for r in requests) == [
        ("2023-06-10", "2023-06-12"),
        ("2024-06-10", "2024-06-12"),
        ("2025-06-10", "2025-06-12"),
    ]
    assert all(r.url.params["temperature_unit"] == "fahrenheit" for r in requests)
    assert_day_shape(result.data, "climate")
    assert [d["date"] for d in result.data] == ["2026-06-10", "2026-06-11", "2026-06-12"]
    # Mean highs/lows; most common code per day.
    assert [(d["high_f"], d["low_f"], d["condition"]) for d in result.data] == [
        (62, 42, "sunny"),
        (72, 52, "rain"),
        (82, 62, "thunderstorm"),
    ]


def test_climate_only_asks_archive_for_past_dates(monkeypatch: pytest.MonkeyPatch) -> None:
    # A trip almost a year out: "one year earlier" is still in the future/too recent.
    today = date(2026, 11, 7)
    start = date(2027, 11, 5)
    payload = daily_payload("2000-01-01", [60], [40], [0])
    client, requests = live_http(monkeypatch, lambda r: httpx.Response(200, json=payload))

    result = get_weather(LAT, LNG, start, start, today=today, client=client)

    assert result.ok, result.error
    assert len(requests) == 3
    for r in requests:
        assert date.fromisoformat(r.url.params["end_date"]) < today


def test_climate_handles_feb_29(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = daily_payload("2000-01-01", [55], [38], [3])
    client, requests = live_http(monkeypatch, lambda r: httpx.Response(200, json=payload))

    result = get_weather(LAT, LNG, date(2028, 2, 29), date(2028, 2, 29), today=date(2027, 11, 1), client=client)

    assert result.ok, result.error
    assert len(requests) == 3
    assert result.data[0]["date"] == "2028-02-29"


def test_geocode_live_parses_first_result(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {"results": [{"name": "Austin", "latitude": 30.27, "longitude": -97.74,
                         "country": "United States", "admin1": "Texas"}]}
    client, requests = live_http(monkeypatch, lambda r: httpx.Response(200, json=body))

    result = geocode_city("Austin, TX", client=client)

    assert result.ok
    assert result.data == {"name": "Austin", "lat": 30.27, "lng": -97.74,
                           "country": "United States", "admin1": "Texas"}
    assert requests[0].url.host == "geocoding-api.open-meteo.com"
    assert requests[0].url.params["name"] == "Austin"


def test_geocode_live_no_results_is_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = live_http(monkeypatch, lambda r: httpx.Response(200, json={"generationtime_ms": 0.3}))
    result = geocode_city("Nowhereville", client=client)
    assert result.ok is False
    assert "Nowhereville" in (result.error or "")


# ---- HTTP errors → ok: false ----

@pytest.mark.parametrize("status", [500, 429, 404])
def test_weather_http_error_is_not_ok(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    client, _ = live_http(monkeypatch, lambda r: httpx.Response(status, json={"error": True}))
    result = get_weather(LAT, LNG, TODAY, TODAY + timedelta(days=1), today=TODAY, client=client)
    assert result.ok is False
    assert result.data is None
    assert f"HTTP {status}" in (result.error or "")


def test_climate_http_error_is_not_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = live_http(monkeypatch, lambda r: httpx.Response(503))
    result = get_weather(LAT, LNG, date(2026, 6, 10), date(2026, 6, 12), today=TODAY, client=client)
    assert result.ok is False
    assert result.error


def test_weather_network_error_is_not_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    client, _ = live_http(monkeypatch, fail)
    result = get_weather(LAT, LNG, TODAY, TODAY, today=TODAY, client=client)
    assert result.ok is False
    assert result.error


@pytest.mark.parametrize(
    "body",
    [
        {"unexpected": 1},
        {"daily": {"temperature_2m_max": [70], "temperature_2m_min": [], "weather_code": [0]}},
        ["not", "an", "object"],
    ],
)
def test_weather_malformed_response_is_not_ok(monkeypatch: pytest.MonkeyPatch, body: Any) -> None:
    client, _ = live_http(monkeypatch, lambda r: httpx.Response(200, json=body))
    result = get_weather(LAT, LNG, TODAY, TODAY, today=TODAY, client=client)
    assert result.ok is False
    assert result.error


def test_weather_non_json_response_is_not_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = live_http(monkeypatch, lambda r: httpx.Response(200, text="<html>oops</html>"))
    result = get_weather(LAT, LNG, TODAY, TODAY, today=TODAY, client=client)
    assert result.ok is False


def test_geocode_http_error_is_not_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = live_http(monkeypatch, lambda r: httpx.Response(500))
    result = geocode_city("San Jose", client=client)
    assert result.ok is False
    assert "HTTP 500" in (result.error or "")


# ---- api_cache (weather 3 h) ----

def test_live_success_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = daily_payload(TODAY.isoformat(), [70], [50], [0])
    client, requests = live_http(monkeypatch, lambda r: httpx.Response(200, json=payload))

    first = get_weather(LAT, LNG, TODAY, TODAY, today=TODAY, client=client)
    second = get_weather(LAT, LNG, TODAY, TODAY, today=TODAY, client=client)

    assert first.ok and second.ok
    assert second.data == first.data
    assert len(requests) == 1


def test_errors_are_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [httpx.Response(500), httpx.Response(200, json=daily_payload(TODAY.isoformat(), [70], [50], [0]))]
    client, requests = live_http(monkeypatch, lambda r: responses.pop(0))

    assert get_weather(LAT, LNG, TODAY, TODAY, today=TODAY, client=client).ok is False
    assert get_weather(LAT, LNG, TODAY, TODAY, today=TODAY, client=client).ok is True
    assert len(requests) == 2


# ---- api_cache (geocode 30 d) ----

AUSTIN = {"results": [{"name": "Austin", "latitude": 30.27, "longitude": -97.74,
                       "country": "United States", "admin1": "Texas"}]}


def test_geocode_ttl_is_30_days() -> None:
    from app.tools.common import GEOCODE_TTL_SECONDS

    assert GEOCODE_TTL_SECONDS == 30 * 24 * 60 * 60


def test_geocode_live_success_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    client, requests = live_http(monkeypatch, lambda r: httpx.Response(200, json=AUSTIN))

    first = geocode_city("Austin, TX", client=client)
    second = geocode_city("austin", client=client)  # same city: region and case don't matter

    assert first.ok and second.ok
    assert second.data == first.data
    assert len(requests) == 1


def test_geocode_cache_is_per_city(monkeypatch: pytest.MonkeyPatch) -> None:
    client, requests = live_http(monkeypatch, lambda r: httpx.Response(200, json=AUSTIN))

    geocode_city("Austin", client=client)
    geocode_city("Dallas", client=client)

    assert len(requests) == 2


def test_geocode_errors_are_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [httpx.Response(500), httpx.Response(200, json=AUSTIN)]
    client, requests = live_http(monkeypatch, lambda r: responses.pop(0))

    assert geocode_city("Austin", client=client).ok is False
    assert geocode_city("Austin", client=client).ok is True
    assert len(requests) == 2


def test_geocode_not_found_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [httpx.Response(200, json={}), httpx.Response(200, json=AUSTIN)]
    client, requests = live_http(monkeypatch, lambda r: responses.pop(0))

    assert geocode_city("Austin", client=client).ok is False
    assert geocode_city("Austin", client=client).ok is True
    assert len(requests) == 2


def test_geocode_mock_results_are_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    # A mock lookup (San Jose fallback for "Austin") must not leak into live mode later.
    assert geocode_city("Austin").ok

    client, requests = live_http(monkeypatch, lambda r: httpx.Response(200, json=AUSTIN))
    result = geocode_city("Austin", client=client)

    assert len(requests) == 1
    assert result.data["lat"] == 30.27


# ---- live (skipped by default; run with `pytest -m live`) ----

@pytest.mark.live
def test_live_open_meteo_geocode_and_forecast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(weather, "is_mock", lambda: False)
    city = geocode_city("San Jose, CA")
    assert city.ok, city.error
    start = date.today() + timedelta(days=2)
    result = get_weather(city.data["lat"], city.data["lng"], start, start + timedelta(days=2))
    assert result.ok, result.error
    assert len(result.data) == 3
    assert_day_shape(result.data, "forecast")
