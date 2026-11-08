"""Step 30: weather in the plan and in chat.

Specified by plan step 30: the gather step geocodes the cities (fills `cities[].lat/lng`) and
fetches weather; postprocess fills `days[].weather` and a code-built `weather_summary` from tool
data, never from the draft; status lines read "Checking weather for San Jose · Mar 5–7"
(contracts §5); a tool failure → weather null, the plan is still saved and an assumption is
added; with a city + dates the chat context includes the forecast. `compact_itinerary` keeps its
one-line-per-day format (step 30 notes).

No network: FakeProvider, TOOL_PROVIDER_MODE=mock (recorded JSON in tools/mocks/), a temp DB.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session

from app.agent import context, pipeline, planner
from app.agent.postprocess import CityWeather, build_itinerary
from app.agent.turn import TurnLlms
from app.api.chat import get_llm
from app.db import repo
from app.llm.base import Message
from app.llm.fake_provider import FakeProvider, load_fake_data
from app.schemas.itinerary import DayWeather, Itinerary, ItineraryDraft, itinerary_errors
from app.schemas.profile import TripProfile
from app.tools.common import ToolResult, tool_error

TODAY = date(2027, 2, 1)  # the San Jose trip (Mar 5–7, 2027) is past the forecast window
NEAR_TODAY = date(2027, 3, 1)  # the same trip is inside the forecast window
START, END = date(2027, 3, 5), date(2027, 3, 7)
LABEL = "Checking weather for San Jose · Mar 5–7"
DAY_LINES = [
    "Day 1 (Fri Mar 5): 06:00 [A] Home · 09:15 [B] IAH · 13:30 [C] San Jose Airport · "
    "14:15 [D] San Jose Marriott · 18:30 [E] San Pedro Square",
    "Day 2 (Sat Mar 6): 11:00 [F] Baconhouse · 13:00 [G] The Tech Interactive · "
    "16:00 [H] Winchester Mystery House · 18:30 [I] Santana Row",
    "Day 3 (Sun Mar 7): 09:30 [J] Japantown · 11:15 [K] Guadalupe River Park · "
    "14:40 [C] San Jose Airport",
]
TRIP_MESSAGE = "San Jose, first weekend of March, just me."  # fake sets city + Mar 5–7 dates

Event = tuple[str, dict[str, Any]]


# --- helpers --------------------------------------------------------------------------------


def _profile(**updates: Any) -> TripProfile:
    fields: dict[str, Any] = dict(
        budget_level="budget", cities=["San Jose, CA"], travelers=1,
        start_date=START, end_date=END,
    )
    fields.update(updates)
    return TripProfile(**fields)


def _day(high: float, low: float, condition: str, source: str = "forecast") -> DayWeather:
    return DayWeather(high_f=high, low_f=low, condition=condition, icon="?", source=source)


def _san_jose(source: str = "forecast") -> CityWeather:
    return CityWeather(
        name="San Jose, CA",
        lat=37.33939,
        lng=-121.89496,
        days={
            date(2027, 3, 5): _day(66, 48, "sunny", source),
            date(2027, 3, 6): _day(68, 50, "sunny", source),
            date(2027, 3, 7): _day(61, 47, "rain", source),
        },
    )


def _draft(raw: dict[str, Any] | None = None) -> ItineraryDraft:
    return ItineraryDraft.model_validate(raw or load_fake_data("draft_sanjose_v1"))


def _build(weather: list[CityWeather] | None, raw: dict[str, Any] | None = None) -> Itinerary:
    plan = build_itinerary(_draft(raw), [], _profile(), weather)
    assert isinstance(plan, Itinerary), plan
    assert itinerary_errors(plan) == []
    return plan


def _draft_with_fake_weather() -> dict[str, Any]:
    """The v1 draft with weather and coordinates the LLM has no business writing."""
    raw = load_fake_data("draft_sanjose_v1")
    raw["weather_summary"] = "Scorching heat wave, 110–120 °F"
    raw["cities"][0]["lat"] = 1.0
    raw["cities"][0]["lng"] = 2.0
    for day in raw["days"]:
        day["weather"] = {
            "high_f": 115, "low_f": 99, "condition": "heat wave", "icon": "X", "source": "forecast",
        }
    return raw


def _gather(profile: TripProfile, today: date = TODAY) -> tuple[list[dict[str, str]], list[CityWeather]]:
    async def collect() -> tuple[list[dict[str, str]], list[CityWeather]]:
        events: list[dict[str, str]] = []
        cities: list[CityWeather] = []
        async for item in pipeline.gather_weather(profile, today):
            if isinstance(item, CityWeather):
                cities.append(item)
            else:
                events.append(item)
        return events, cities

    return asyncio.run(collect())


def _status_data(events: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [json.loads(e["data"]) for e in events if e["event"] == "status"]


def _fail_forecast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pipeline.weather_tool, "get_weather",
        lambda *args, **kwargs: tool_error("Weather is unavailable: HTTP 500"),
    )


def _fail_geocode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pipeline.weather_tool, "geocode_city",
        lambda *args, **kwargs: tool_error("City lookup failed: HTTP 500"),
    )


def _run_generation(
    db: Session, session_id: str, profile: TripProfile, llm: FakeProvider | None = None
) -> list[dict[str, str]]:
    async def collect() -> list[dict[str, str]]:
        return [
            event
            async for event in pipeline.run_generation(
                db, session_id, llm or FakeProvider(), profile, [], on_saved=lambda _: None,
                today=TODAY,
            )
        ]

    return asyncio.run(collect())


def _parse_sse(text: str) -> list[Event]:
    events: list[Event] = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        name, data = "message", []
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data.append(line[len("data:"):].lstrip(" "))
        if data:
            events.append((name, json.loads("\n".join(data))))
    return events


class RecordingFake(FakeProvider):
    """FakeProvider that records the system text of every streamed reply."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.systems: list[str] = []

    async def stream_text(self, system: str, messages: list[Message]) -> AsyncIterator[str]:
        self.systems.append(system)
        async for chunk in super().stream_text(system, messages):
            yield chunk


def _use(client: TestClient, provider: FakeProvider) -> None:
    client.app.dependency_overrides[get_llm] = lambda: TurnLlms(provider, provider)  # type: ignore[attr-defined]


def _session(client: TestClient) -> str:
    return client.post("/api/sessions").json()["id"]


def _send(client: TestClient, session_id: str, content: str) -> list[Event]:
    response = client.post(f"/api/sessions/{session_id}/messages", json={"content": content})
    assert response.status_code == 200
    return _parse_sse(response.text)


def _generate(client: TestClient, session_id: str) -> list[Event]:
    response = client.post(f"/api/sessions/{session_id}/generate", json={})
    assert response.status_code == 200
    return _parse_sse(response.text)


def _statuses(events: list[Event]) -> list[dict[str, Any]]:
    return [data for name, data in events if name == "status"]


# --- postprocess: weather comes from tool data, not the draft -------------------------------


def test_days_get_the_tool_weather_for_their_date() -> None:
    weather = _san_jose()

    plan = _build([weather])

    for day in plan.days:
        assert day.weather == weather.days[day.date]


def test_cities_get_the_geocoded_coordinates() -> None:
    plan = _build([_san_jose()])

    assert (plan.cities[0].lat, plan.cities[0].lng) == (37.33939, -121.89496)


def test_draft_weather_and_coordinates_are_ignored() -> None:
    weather = _san_jose()

    plan = _build([weather], _draft_with_fake_weather())

    assert [day.weather for day in plan.days] == [weather.days[day.date] for day in plan.days]
    assert (plan.cities[0].lat, plan.cities[0].lng) == (37.33939, -121.89496)
    assert plan.weather_summary is not None
    assert "heat" not in plan.weather_summary.lower()
    assert "110" not in plan.weather_summary


def test_draft_weather_is_ignored_when_nothing_was_gathered() -> None:
    plan = _build([], _draft_with_fake_weather())

    assert all(day.weather is None for day in plan.days)
    assert plan.weather_summary is None
    assert (plan.cities[0].lat, plan.cities[0].lng) == (None, None)


def test_weather_summary_is_built_from_the_tool_data() -> None:
    plan = _build([_san_jose()])

    assert plan.weather_summary is not None
    assert "47–68 °F" in plan.weather_summary  # lowest low – highest high
    assert "sunny" in plan.weather_summary  # the most common condition
    assert "average" not in plan.weather_summary


def test_climate_weather_summary_says_it_is_an_average() -> None:
    plan = _build([_san_jose(source="climate")])

    assert plan.weather_summary is not None
    assert "seasonal average" in plan.weather_summary


def test_no_weather_gathered_means_null_weather_and_no_weather_assumption() -> None:
    plan = _build(None)

    assert all(day.weather is None for day in plan.days)
    assert plan.weather_summary is None
    assert not any("weather" in note.lower() for note in plan.assumptions)


# --- postprocess: matching gathered cities to draft cities (review fix) ---------------------


def _two_city_draft() -> dict[str, Any]:
    """The v1 draft with a second city: day 3 is in San Francisco."""
    raw = load_fake_data("draft_sanjose_v1")
    raw["cities"].append({"name": "San Francisco", "region": "CA", "country": "USA"})
    raw["days"][2]["city"] = "San Francisco"
    return raw


def _san_francisco() -> CityWeather:
    return CityWeather(
        name="San Francisco, CA",
        lat=37.77493,
        lng=-122.41942,
        days={date(2027, 3, 7): _day(58, 45, "foggy")},
    )


def _build_two_city(weather: list[CityWeather]) -> Itinerary:
    profile = _profile(cities=["San Jose, CA", "San Francisco, CA"])
    plan = build_itinerary(_draft(_two_city_draft()), [], profile, weather)
    assert isinstance(plan, Itinerary), plan
    assert itinerary_errors(plan) == []
    return plan


def test_two_city_draft_does_not_borrow_the_only_gathered_city() -> None:
    weather = _san_jose()

    plan = _build_two_city([weather])

    by_name = {city.name: city for city in plan.cities}
    assert (by_name["San Jose"].lat, by_name["San Jose"].lng) == (37.33939, -121.89496)
    assert (by_name["San Francisco"].lat, by_name["San Francisco"].lng) == (None, None)
    assert plan.days[0].weather == weather.days[date(2027, 3, 5)]
    assert plan.days[1].weather == weather.days[date(2027, 3, 6)]
    assert plan.days[2].weather is None  # the San Francisco day gets no San Jose weather


def test_two_city_draft_gets_each_city_its_own_data() -> None:
    plan = _build_two_city([_san_jose(), _san_francisco()])

    by_name = {city.name: city for city in plan.cities}
    assert (by_name["San Jose"].lat, by_name["San Jose"].lng) == (37.33939, -121.89496)
    assert (by_name["San Francisco"].lat, by_name["San Francisco"].lng) == (37.77493, -122.41942)
    assert plan.days[0].weather is not None and plan.days[0].weather.condition == "sunny"
    assert plan.days[2].weather is not None and plan.days[2].weather.condition == "foggy"


def test_one_city_draft_still_uses_a_differently_spelled_gathered_city() -> None:
    weather = _san_jose()
    weather.name = "San José"  # the draft says "San Jose"

    plan = _build([weather])

    assert (plan.cities[0].lat, plan.cities[0].lng) == (37.33939, -121.89496)
    assert all(day.weather == weather.days[day.date] for day in plan.days)


# --- postprocess: a tool failure ------------------------------------------------------------


def test_failed_weather_leaves_weather_null_and_adds_one_assumption() -> None:
    failed = CityWeather(name="San Jose, CA", error="Weather is unavailable: HTTP 500")

    plan = _build([failed])

    assert all(day.weather is None for day in plan.days)
    assert plan.weather_summary is None
    assert (plan.cities[0].lat, plan.cities[0].lng) == (None, None)
    weather_notes = [note for note in plan.assumptions if "Weather for San Jose" in note]
    assert len(weather_notes) == 1
    assert "HTTP 500" not in weather_notes[0]  # a user-facing note, not the raw error


def test_forecast_only_failure_keeps_the_coordinates() -> None:
    failed = CityWeather(
        name="San Jose, CA", lat=37.33939, lng=-121.89496, error="Weather is unavailable"
    )

    plan = _build([failed])

    assert (plan.cities[0].lat, plan.cities[0].lng) == (37.33939, -121.89496)
    assert all(day.weather is None for day in plan.days)
    assert any("Weather for San Jose" in note for note in plan.assumptions)


def test_weather_assumption_is_not_duplicated_on_repeat() -> None:
    failed = CityWeather(name="San Jose, CA", error="x")
    raw = load_fake_data("draft_sanjose_v1")
    raw["assumptions"].append(
        "Weather for San Jose couldn't be loaded; check a forecast before you go"
    )

    plan = _build([failed], raw)

    assert sum("Weather for San Jose" in note for note in plan.assumptions) == 1


# --- pipeline gather step -------------------------------------------------------------------


def test_weather_label_matches_the_contract() -> None:
    assert pipeline.weather_label("San Jose, CA", START, END) == LABEL


def test_date_range_label_across_months_names_both_months() -> None:
    label = pipeline.date_range_label(date(2027, 3, 30), date(2027, 4, 2))

    assert "Mar 30" in label and "Apr 2" in label


def test_gather_emits_start_then_end_with_the_label() -> None:
    events, cities = _gather(_profile())

    assert _status_data(events) == [
        {"label": LABEL, "state": "start"},
        {"label": LABEL, "state": "end"},
    ]
    assert len(cities) == 1


def test_gather_fills_coordinates_and_one_day_per_trip_date() -> None:
    _, (city,) = _gather(_profile())

    assert city.error is None
    assert (city.lat, city.lng) == (37.33939, -121.89496)  # tools/mocks/weather_geocode.json
    assert sorted(city.days) == [date(2027, 3, 5), date(2027, 3, 6), date(2027, 3, 7)]


def test_gather_uses_climate_far_out_and_forecast_near() -> None:
    _, (far,) = _gather(_profile(), today=TODAY)
    _, (near,) = _gather(_profile(), today=NEAR_TODAY)

    assert {day.source for day in far.days.values()} == {"climate"}
    assert {day.source for day in near.days.values()} == {"forecast"}


def test_gather_works_with_start_date_and_length() -> None:
    events, (city,) = _gather(_profile(end_date=None, duration_days=3))

    assert _status_data(events)[0]["label"] == LABEL
    assert len(city.days) == 3


@pytest.mark.parametrize(
    "updates",
    [
        {"start_date": None, "end_date": None},  # no dates
        {"end_date": None, "duration_days": None},  # start only
        {"cities": []},  # no city
    ],
)
def test_gather_does_nothing_without_city_and_exact_dates(updates: dict[str, Any]) -> None:
    events, cities = _gather(_profile(**updates))

    assert events == [] and cities == []


def _record_weather_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace both weather tools with ones that record a call and fail."""
    calls: list[str] = []

    def geocode(*args: Any, **kwargs: Any) -> ToolResult:
        calls.append("geocode_city")
        return tool_error("should not be called")

    def forecast(*args: Any, **kwargs: Any) -> ToolResult:
        calls.append("get_weather")
        return tool_error("should not be called")

    monkeypatch.setattr(pipeline.weather_tool, "geocode_city", geocode)
    monkeypatch.setattr(pipeline.weather_tool, "get_weather", forecast)
    return calls


@pytest.mark.parametrize(
    "updates",
    [
        {},  # start + end dates
        {"end_date": None, "duration_days": 3},  # start + length
    ],
)
def test_gather_does_nothing_for_a_trip_that_already_ended(
    monkeypatch: pytest.MonkeyPatch, updates: dict[str, Any]
) -> None:
    calls = _record_weather_calls(monkeypatch)

    events, cities = _gather(_profile(**updates), today=date(2027, 3, 8))  # day after END

    assert events == [] and cities == []
    assert calls == []


def test_gather_does_nothing_for_a_trip_long_past(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _record_weather_calls(monkeypatch)

    events, cities = _gather(_profile(), today=date(2028, 1, 1))

    assert events == [] and cities == []
    assert calls == []


def test_gather_still_runs_for_a_trip_ending_today() -> None:
    events, cities = _gather(_profile(), today=END)

    assert _status_data(events) == [
        {"label": LABEL, "state": "start"},
        {"label": LABEL, "state": "end"},
    ]
    (city,) = cities
    assert city.error is None
    assert sorted(city.days) == [date(2027, 3, 5), date(2027, 3, 6), date(2027, 3, 7)]


def test_gather_still_runs_for_a_trip_already_underway() -> None:
    events, cities = _gather(_profile(), today=date(2027, 3, 6))

    assert [s["state"] for s in _status_data(events)] == ["start", "end"]
    assert len(cities) == 1 and cities[0].error is None


def test_gather_one_status_pair_per_city() -> None:
    events, cities = _gather(_profile(cities=["San Jose, CA", "San Francisco, CA"]))

    # The cities run in parallel (step 33a, D25), so the lines may interleave: both starts
    # come first, then each city's end.
    statuses = _status_data(events)
    sf_label = "Checking weather for San Francisco · Mar 5–7"
    assert [s["state"] for s in statuses] == ["start", "start", "end", "end"]
    assert sorted(s["label"] for s in statuses if s["state"] == "start") == sorted([LABEL, sf_label])
    assert sorted(s["label"] for s in statuses if s["state"] == "end") == sorted([LABEL, sf_label])
    assert [c.name for c in cities] == ["San Jose, CA", "San Francisco, CA"]


def test_gather_geocode_failure_emits_error_and_no_data(monkeypatch: pytest.MonkeyPatch) -> None:
    _fail_geocode(monkeypatch)

    events, (city,) = _gather(_profile())

    assert _status_data(events) == [
        {"label": LABEL, "state": "start"},
        {"label": LABEL, "state": "error"},
    ]
    assert city.error is not None
    assert city.days == {} and city.lat is None


def test_gather_forecast_failure_keeps_coordinates(monkeypatch: pytest.MonkeyPatch) -> None:
    _fail_forecast(monkeypatch)

    events, (city,) = _gather(_profile())

    assert _status_data(events)[-1] == {"label": LABEL, "state": "error"}
    assert city.error is not None and city.days == {}
    assert (city.lat, city.lng) == (37.33939, -121.89496)


def test_gather_survives_a_tool_that_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: Any, **kwargs: Any) -> ToolResult:
        raise RuntimeError("boom")

    monkeypatch.setattr(pipeline.weather_tool, "get_weather", boom)

    events, (city,) = _gather(_profile())

    assert _status_data(events)[-1]["state"] == "error"
    assert city.error is not None


# --- pipeline run_generation ----------------------------------------------------------------


def test_generation_weather_status_comes_before_drafting(db: Session) -> None:
    session_id = repo.create_session(db).id

    statuses = _status_data(_run_generation(db, session_id, _profile()))

    assert statuses[:2] == [
        {"label": LABEL, "state": "start"},
        {"label": LABEL, "state": "end"},
    ]
    # Then the planner's line (step 33a), then the draft.
    assert statuses[2] == {"label": planner.CHOOSING_LABEL, "state": "start"}
    assert statuses[4] == {"label": pipeline.DRAFTING_LABEL, "state": "start"}


def test_generation_saves_the_tool_weather(db: Session) -> None:
    session_id = repo.create_session(db).id
    llm = FakeProvider(drafts=[_draft_with_fake_weather()])

    _run_generation(db, session_id, _profile(), llm)

    saved = repo.get_latest_itinerary(db, session_id)
    assert saved is not None
    assert all(day.weather is not None for day in saved.days)
    assert all(day.weather.condition != "heat wave" for day in saved.days)  # type: ignore[union-attr]
    assert {day.weather.source for day in saved.days} == {"climate"}  # type: ignore[union-attr]
    assert saved.cities[0].lat == 37.33939
    assert saved.weather_summary is not None and "seasonal average" in saved.weather_summary


def test_generation_with_failed_weather_still_saves_the_plan(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fail_geocode(monkeypatch)
    session_id = repo.create_session(db).id

    events = _run_generation(db, session_id, _profile())

    statuses = _status_data(events)
    assert {"label": LABEL, "state": "error"} in statuses
    assert statuses[-1] == {"label": pipeline.DRAFTING_LABEL, "state": "end"}
    assert events[-1]["event"] == "itinerary"
    saved = repo.get_latest_itinerary(db, session_id)
    assert saved is not None and saved.version == 1
    assert all(day.weather is None for day in saved.days)
    assert saved.weather_summary is None
    assert any("Weather for San Jose" in note for note in saved.assumptions)


def test_compose_prompt_gets_the_gathered_weather() -> None:
    system = pipeline.build_system(_profile(), TODAY, weather=[_san_jose()])

    weather_part = system.split("## Weather", 1)[1]
    assert "66" in weather_part and "48" in weather_part and "sunny" in weather_part


def test_compose_prompt_tells_the_llm_to_plan_around_the_weather() -> None:
    rules = pipeline.build_system(_profile(), TODAY).split("# Context", 1)[0]

    assert "Plan around the weather" in rules
    assert "indoor" in rules


def test_chat_prompt_tells_the_llm_to_fit_suggestions_to_the_weather() -> None:
    rules = context.build_system(_profile(), TODAY).split("# Context", 1)[0]

    assert "indoor option on a rainy day" in rules


# --- chat context ---------------------------------------------------------------------------


def test_chat_context_contains_the_forecast() -> None:
    system = context.build_system(_profile(), TODAY, weather=[_san_jose()])

    assert "## Weather" in system
    assert "San Jose" in system.split("## Weather", 1)[1]
    for high, low in ((66, 48), (68, 50), (61, 47)):
        assert str(high) in system and str(low) in system
    assert "rain" in system


def test_chat_context_says_when_weather_is_unavailable() -> None:
    failed = CityWeather(name="San Jose, CA", error="x")

    system = context.build_system(_profile(), TODAY, weather=[failed])

    weather_part = system.split("## Weather", 1)[1]
    assert "unavailable" in weather_part.lower()


def test_chat_context_without_weather_has_no_weather_section() -> None:
    assert "## Weather" not in context.build_system(_profile(), TODAY)


# --- compact_itinerary ----------------------------------------------------------------------


def test_compact_itinerary_with_weather_keeps_the_day_lines() -> None:
    lines = context.compact_itinerary(_build([_san_jose()])).splitlines()

    for day_line in DAY_LINES:
        assert day_line in lines
    assert sum(line.startswith("Day ") for line in lines) == 3


def test_compact_itinerary_has_one_weather_line_before_the_days() -> None:
    lines = context.compact_itinerary(_build([_san_jose()])).splitlines()

    weather_lines = [i for i, line in enumerate(lines) if line.startswith("Weather:")]
    first_day = next(i for i, line in enumerate(lines) if line.startswith("Day "))
    assert len(weather_lines) == 1 and weather_lines[0] < first_day
    assert "66" in lines[weather_lines[0]] and "sunny" in lines[weather_lines[0]]


def test_compact_itinerary_without_weather_has_no_weather_line() -> None:
    lines = context.compact_itinerary(_build([])).splitlines()

    assert not any(line.startswith("Weather:") for line in lines)
    for day_line in DAY_LINES:
        assert day_line in lines


# --- API: chat and generate turns -----------------------------------------------------------


def test_chat_turn_without_plan_gets_the_forecast_and_no_status(client: TestClient) -> None:
    provider = RecordingFake()
    _use(client, provider)
    session_id = _session(client)

    events = _send(client, session_id, TRIP_MESSAGE)

    assert "status" not in [name for name, _ in events]
    assert "## Weather" in provider.systems[-1]
    assert "San Jose" in provider.systems[-1].split("## Weather", 1)[1]


def test_chat_turn_without_dates_has_no_weather(client: TestClient) -> None:
    provider = RecordingFake()
    _use(client, provider)
    session_id = _session(client)

    _send(client, session_id, "Hi there")

    assert "## Weather" not in provider.systems[-1]


def test_generate_shows_the_weather_status_and_saves_weather(
    client: TestClient, db_engine: Engine
) -> None:
    session_id = _session(client)
    _send(client, session_id, TRIP_MESSAGE)

    events = _generate(client, session_id)

    statuses = _statuses(events)
    assert statuses[:2] == [
        {"label": LABEL, "state": "start"},
        {"label": LABEL, "state": "end"},
    ]
    plan = next(data for name, data in events if name == "itinerary")
    assert all(day["weather"] is not None for day in plan["days"])
    assert plan["weather_summary"]
    assert plan["cities"][0]["lat"] is not None
    with Session(db_engine) as db:
        saved = repo.get_latest_itinerary(db, session_id)
    assert saved is not None and saved.days[0].weather is not None


def test_generate_with_failed_weather_still_saves_plan_with_assumption(
    client: TestClient, db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = _session(client)
    _send(client, session_id, TRIP_MESSAGE)
    _fail_forecast(monkeypatch)

    events = _generate(client, session_id)

    names = [name for name, _ in events]
    assert "error" not in names and names[-1] == "done"
    assert {"label": LABEL, "state": "error"} in _statuses(events)
    plan = next(data for name, data in events if name == "itinerary")
    assert all(day["weather"] is None for day in plan["days"])
    assert plan["weather_summary"] is None
    assert any("Weather for San Jose" in note for note in plan["assumptions"])
    with Session(db_engine) as db:
        assert len(repo.list_itineraries(db, session_id)) == 1


def test_chat_after_plan_sees_weather_in_the_compact_plan(client: TestClient) -> None:
    provider = RecordingFake()
    _use(client, provider)
    session_id = _session(client)
    _send(client, session_id, TRIP_MESSAGE)
    _generate(client, session_id)

    _send(client, session_id, "What's the weather like?")

    system = provider.systems[-1]
    plan_part = system.split("## Current plan", 1)[1]
    assert "Weather:" in plan_part
    assert DAY_LINES[0] in system
