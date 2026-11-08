"""Generation pipeline (architecture §4.1): gather → compose → postprocess → save.

Gather so far: the weather for each profile city over the trip dates (when both are known).
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import date, timedelta
from typing import Any

from pydantic import ValidationError
from sqlmodel import Session

from app.agent import context, sse
from app.agent.postprocess import CityWeather, build_itinerary, short_city_name
from app.agent.sse import SseEvent
from app.db import repo
from app.llm.base import LLMProvider, Message
from app.schemas.itinerary import (
    DayWeather,
    DraftCity,
    DraftDay,
    DraftItem,
    DraftLodging,
    DraftStop,
    Itinerary,
    ItineraryDraft,
)
from app.schemas.profile import TripProfile
from app.tools import weather as weather_tool
from app.tools.common import ToolResult, tool_error, tool_ok

COMPOSE_REQUEST = "Make the full trip plan now."
# For an edit; the fake provider spots edits by "change only what was asked".
EDIT_REQUEST = (
    "Update the current plan: {change_request}\n"
    "Change only what was asked. Copy every other day, item and stop exactly as it is in the "
    "current plan (same names, keys, times and descriptions), and reply with the whole updated "
    "plan."
)
DRAFTING_LABEL = "Drafting your plan…"
UPDATING_LABEL = "Updating your plan…"


async def run_generation(
    db: Session,
    session_id: str,
    llm: LLMProvider,
    profile: TripProfile,
    messages: list[Message],
    on_saved: Callable[[Itinerary], None],
    today: date | None = None,
    change_request: str | None = None,
) -> AsyncIterator[SseEvent]:
    """Make the session's next plan version and save it. Events: the gather status lines (one
    start → end/error pair per weather city), then the draft's status start → end → itinerary.

    A failed weather call only leaves the weather out (postprocess adds an assumption).
    `change_request` (an edit) makes compose update the latest plan instead of making a new one.
    `on_saved` is called right after the save, so the caller knows the new version even if a
    later step fails or the stream is stopped. If compose or the save fails, it emits status
    "error" and re-raises; nothing is saved, so the previous plan stays. The caller turns the
    exception into an `error` event.
    """
    weather: list[CityWeather] = []
    async for item in gather_weather(profile, today):
        if isinstance(item, CityWeather):
            weather.append(item)
        else:
            yield item

    label = UPDATING_LABEL if change_request else DRAFTING_LABEL
    yield sse.status(label, "start")
    try:
        previous_versions = repo.list_itineraries(db, session_id)
        plan = await compose(
            llm, profile, messages, previous_versions, today, change_request, weather
        )
        saved = repo.save_itinerary(db, session_id, plan)  # also sets the status to "planned"
    except Exception:
        yield sse.status(label, "error")
        raise
    on_saved(saved)
    yield sse.status(label, "end")
    yield sse.itinerary(saved.model_dump(mode="json"))


async def status(
    label: str, tool: Callable[..., ToolResult], *args: Any
) -> AsyncIterator[SseEvent | ToolResult]:
    """Run one tool call between `status` lines: start, then end (ok) or error (failed).

    Yields the two status events, then the ToolResult as the last item. The tool runs in a
    worker thread (tools are synchronous). A tool that raises counts as failed, so the pipeline
    can always carry on without that data. Use it like this:

        async for item in status("Checking weather…", weather.get_weather, lat, lng, start, end):
            if isinstance(item, ToolResult):
                result = item
            else:
                yield item
    """
    yield sse.status(label, "start")
    try:
        result = await asyncio.to_thread(tool, *args)
    except Exception as error:  # tools shouldn't raise, but one bad tool mustn't stop the plan
        result = tool_error(str(error) or type(error).__name__)
    yield sse.status(label, "end" if result.ok else "error")
    yield result


async def gather_weather(
    profile: TripProfile, today: date | None = None
) -> AsyncIterator[SseEvent | CityWeather]:
    """Weather for each profile city over the trip dates, one status line pair per city.

    Yields the status events and one CityWeather per city (with `error` set if the tool
    failed). Yields nothing when the profile has no city or no exact dates yet, or when
    the trip already ended before `today` (there is no forecast for past dates).
    """
    dates = trip_dates(profile)
    if dates is None:
        return
    start, end = dates
    if end < (today or date.today()):
        return
    for city in profile.cities:
        label = weather_label(city, start, end)
        async for item in status(label, city_weather, city, start, end, today):
            yield to_city_weather(city, item) if isinstance(item, ToolResult) else item


def trip_dates(profile: TripProfile) -> tuple[date, date] | None:
    """The trip's first and last day from the profile, or None if they aren't known exactly."""
    start = profile.start_date
    if start is None:
        return None
    if profile.end_date is not None:
        end = profile.end_date
    elif profile.duration_days is not None:
        end = start + timedelta(days=profile.duration_days - 1)
    else:
        return None
    return (start, end) if end >= start else None


def weather_label(city: str, start: date, end: date) -> str:
    """e.g. "Checking weather for San Jose · Mar 5–7"."""
    return f"Checking weather for {short_city_name(city)} · {date_range_label(start, end)}"


def date_range_label(start: date, end: date) -> str:
    """A short date range: "Mar 5–7", "Mar 30 – Apr 2", or "Mar 5" for a single day."""
    if start == end:
        return f"{start:%b} {start.day}"
    if (start.year, start.month) == (end.year, end.month):
        return f"{start:%b} {start.day}–{end.day}"
    return f"{start:%b} {start.day} – {end:%b} {end.day}"


def city_weather(city: str, start: date, end: date, today: date | None = None) -> ToolResult:
    """The weather "tool" for one city: geocode it, then get its weather for the dates.

    Data: {"place": geocode data, "days": weather days}. When only the weather fails, the
    result is not ok but still carries the place, so the city keeps its coordinates.
    """
    place = weather_tool.geocode_city(city)
    if not place.ok:
        return place
    days = weather_tool.get_weather(place.data["lat"], place.data["lng"], start, end, today)
    if not days.ok:
        return ToolResult(ok=False, data={"place": place.data}, error=days.error)
    return tool_ok({"place": place.data, "days": days.data})


def to_city_weather(city: str, result: ToolResult) -> CityWeather:
    """A `city_weather` result as a CityWeather for postprocess and the context."""
    data = result.data or {}
    place = data.get("place") or {}
    return CityWeather(
        name=city,
        lat=place.get("lat"),
        lng=place.get("lng"),
        days={
            date.fromisoformat(day["date"]): DayWeather.model_validate(day)
            for day in data.get("days") or []
        },
        error=None if result.ok else (result.error or "Weather is unavailable."),
    )


class ComposeError(Exception):
    """Compose failed twice (the first try and the one repair try). `errors` says why."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("The plan could not be made: " + "; ".join(errors))
        self.errors = errors


async def compose(
    llm: LLMProvider,
    profile: TripProfile,
    messages: list[Message],
    previous_versions: list[Itinerary] | None = None,
    today: date | None = None,
    change_request: str | None = None,
    weather: list[CityWeather] | None = None,
) -> Itinerary:
    """Ask the LLM for an ItineraryDraft and postprocess it into a valid Itinerary.

    With a `change_request` and an earlier version, it is an edit: compose gets the latest plan
    and is told to change only what was asked. If the draft breaks a rule, compose once more
    with the errors included. Raises ComposeError when the repair try fails too.
    `weather` (from the gather step) goes into the prompt and, by postprocess, into the plan.
    """
    previous_versions = previous_versions or []
    weather = weather or []
    latest = max(previous_versions, key=lambda itinerary: itinerary.version, default=None)
    if change_request and latest is not None:
        request = EDIT_REQUEST.format(change_request=change_request)
        system = build_system(profile, today, current_plan=latest, weather=weather)
    else:
        request = COMPOSE_REQUEST
        system = build_system(profile, today, weather=weather)

    result = await _compose_once(
        llm, system, messages, request, previous_versions, profile, weather
    )
    if isinstance(result, Itinerary):
        return result

    result = await _compose_once(
        llm, system, messages, repair_request(result, request), previous_versions, profile,
        weather,
    )
    if isinstance(result, Itinerary):
        return result
    raise ComposeError(result)


async def _compose_once(
    llm: LLMProvider,
    system: str,
    messages: list[Message],
    request: str,
    previous_versions: list[Itinerary],
    profile: TripProfile,
    weather: list[CityWeather],
) -> Itinerary | list[str]:
    """One compose call + postprocess: the Itinerary, or the errors that broke it."""
    try:
        draft = await llm.complete_json(system, with_request(messages, request), ItineraryDraft)
    except ValidationError as error:
        # The reply didn't fit the draft schema (e.g. an unknown stop_key); worth one repair.
        return [
            f"{'.'.join(str(part) for part in detail['loc'])}: {detail['msg']}"
            for detail in error.errors()
        ]
    return build_itinerary(draft, previous_versions, profile, weather)


def with_request(messages: list[Message], request: str) -> list[Message]:
    """The chat plus the compose request as the last user message.

    If the chat already ends with a user message, the request is added to it, so roles keep
    alternating (some backends reject two user messages in a row).
    """
    if messages and messages[-1]["role"] == "user":
        last = messages[-1]
        return [*messages[:-1], {"role": "user", "content": f"{last['content']}\n\n{request}"}]
    return [*messages, {"role": "user", "content": request}]


def repair_request(errors: list[str], request: str = COMPOSE_REQUEST) -> str:
    """The user message for the repair try: the request again plus what was wrong."""
    error_lines = "\n".join(f"- {error}" for error in errors)
    return (
        f"{request}\n\n"
        f"Your last plan broke these rules. Fix them and reply with the whole corrected plan:\n"
        f"{error_lines}"
    )


def build_system(
    profile: TripProfile,
    today: date | None = None,
    current_plan: Itinerary | None = None,
    weather: list[CityWeather] | None = None,
) -> str:
    """System text for the compose call: its prompt plus today's date, the profile and the
    gathered weather.

    For an edit, `current_plan` is the latest version. It is given in the draft shape compose
    replies with, so unchanged parts can be copied as they are.
    """
    today = today or date.today()
    parts = [
        context.load_prompt("compose").strip(),
        "# Context",
        f"Today is {context.format_date(today)} ({today.isoformat()}).",
        "## Trip profile\n" + context.render_profile(profile),
    ]
    if weather:
        parts.append(context.render_weather(weather))
    if current_plan is not None:
        parts.append(
            f"## Current plan (version {current_plan.version})\n"
            "The plan to update, as an ItineraryDraft. Its stop keys are the stops' letter tags.\n"
            + as_draft(current_plan).model_dump_json(exclude_none=True)
        )
    return "\n\n".join(parts)


def as_draft(plan: Itinerary) -> ItineraryDraft:
    """A saved itinerary in the ItineraryDraft shape, with each stop's tag as its key.

    Code-owned fields (ids, weather, transit, links…) are dropped, as in a reply from the LLM.
    """
    return ItineraryDraft(
        title=plan.title,
        summary=plan.summary,
        start_date=plan.start_date,
        end_date=plan.end_date,
        travelers=plan.travelers,
        cities=[DraftCity.model_validate(city.model_dump()) for city in plan.cities],
        cost_estimate=plan.cost_estimate,
        assumptions=plan.assumptions,
        stops=[
            DraftStop.model_validate({**stop.model_dump(), "key": stop.tag}) for stop in plan.stops
        ],
        lodging=[
            DraftLodging.model_validate({**lodging.model_dump(), "stop_key": lodging.stop_tag})
            for lodging in plan.lodging
        ],
        days=[
            DraftDay(
                day_number=day.day_number,
                date=day.date,
                title=day.title,
                city=day.city,
                items=[
                    DraftItem.model_validate({**item.model_dump(), "stop_key": item.stop_tag})
                    for item in day.items
                ],
            )
            for day in plan.days
        ],
    )
