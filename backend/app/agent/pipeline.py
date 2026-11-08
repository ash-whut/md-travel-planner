"""Generation pipeline (architecture §4.1): weather → planner → compose → postprocess → save.

Weather: each profile city over the trip dates (when both are known), all cities in parallel.
Planner: the planner agent's tool rounds (agent/planner.py).
Compose cites the planner's places by ref (`place_ref: "p3"`); `locate_stops` turns the draft's
stops into tool locations for postprocess.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import date, timedelta

from pydantic import ValidationError
from sqlmodel import Session

from app.agent import context, sse
from app.agent.planner import PLANNER_REQUEST, Finding, run_parallel, run_planner
from app.agent.postprocess import (
    PLACES_SOURCE,
    CityWeather,
    StopPlace,
    build_itinerary,
    short_city_name,
)
from app.agent.sse import SseEvent
from app.agent.tags import normalize_name
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
from app.tools import places as places_tool
from app.tools import weather as weather_tool
from app.tools.common import ToolResult, tool_ok

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
# Planner tools whose findings are places a stop can cite with `place_ref`.
PLACE_TOOLS = {"search_places"}
# Stops that may have no found place but are still put on the map with the geocoder: the trip's
# fixed points. Other stops without a valid ref stay off the map (D27).
GEOCODE_KINDS = {"home", "airport", "lodging"}


async def run_generation(
    db: Session,
    session_id: str,
    planner_llm: LLMProvider,
    profile: TripProfile,
    messages: list[Message],
    on_saved: Callable[[Itinerary], None],
    today: date | None = None,
    change_request: str | None = None,
) -> AsyncIterator[SseEvent]:
    """Make the session's next plan version and save it. Events: the weather status lines (one
    start → end/error pair per city), the planner's status lines, then the draft's status
    start → end → itinerary.

    A failed weather call only leaves the weather out (postprocess adds an assumption), and a
    failed planner tool only leaves its data out.
    `change_request` (an edit) makes compose update the latest plan instead of making a new one.
    `planner_llm` is the planner-role provider (D26); it runs the planner and compose.
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
    try:
        # Read before the planner, which needs the latest plan for an edit.
        previous_versions = repo.list_itineraries(db, session_id)
    except Exception:
        # A failed generation ends with a status error before the `error` event (contracts §5).
        yield sse.status(label, "start")
        yield sse.status(label, "error")
        raise
    latest = max(previous_versions, key=lambda itinerary: itinerary.version, default=None)
    # Every numbered result item (p1, h1…) the planner's tools found; compose cites them.
    findings: list[Finding] = []
    async for event in run_planner(
        planner_llm, profile, with_request(messages, PLANNER_REQUEST), weather, today,
        current_plan=latest if change_request else None, change_request=change_request,
    ):
        if isinstance(event, list):
            findings = event
        else:
            yield event

    yield sse.status(label, "start")
    try:
        plan = await compose(
            planner_llm, profile, messages, previous_versions, today, change_request, weather,
            findings,
        )
        saved = repo.save_itinerary(db, session_id, plan)  # also sets the status to "planned"
    except Exception:
        yield sse.status(label, "error")
        raise
    on_saved(saved)
    yield sse.status(label, "end")
    yield sse.itinerary(saved.model_dump(mode="json"))


async def gather_weather(
    profile: TripProfile, today: date | None = None
) -> AsyncIterator[SseEvent | CityWeather]:
    """Weather for each profile city over the trip dates, one status line pair per city. The
    cities run in parallel (D25).

    Yields the status events as they happen, then one CityWeather per city in profile order
    (with `error` set if the tool failed). Yields nothing when the profile has no city or no
    exact dates yet, or when the trip already ended before `today` (there is no forecast for
    past dates).
    """
    dates = trip_dates(profile)
    if dates is None:
        return
    start, end = dates
    if end < (today or date.today()):
        return
    calls = [
        (weather_label(city, start, end), city_weather, (city, start, end, today))
        for city in profile.cities
    ]
    async for item in run_parallel(calls):
        if isinstance(item, list):
            for city, result in zip(profile.cities, item):
                yield to_city_weather(city, result)
        else:
            yield item


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
    findings: list[Finding] | None = None,
) -> Itinerary:
    """Ask the LLM for an ItineraryDraft and postprocess it into a valid Itinerary.

    With a `change_request` and an earlier version, it is an edit: compose gets the latest plan
    and is told to change only what was asked. If the draft breaks a rule, compose once more
    with the errors included. Raises ComposeError when the repair try fails too.
    `weather` (from the gather step) goes into the prompt and, by postprocess, into the plan.
    `findings` (from the planner) are listed in the prompt by ref; the stops that cite one get
    its coordinates (see `locate_stops`).
    """
    previous_versions = previous_versions or []
    weather = weather or []
    findings = findings or []
    latest = max(previous_versions, key=lambda itinerary: itinerary.version, default=None)
    if change_request and latest is not None:
        request = EDIT_REQUEST.format(change_request=change_request)
        system = build_system(
            profile, today, current_plan=latest, weather=weather, findings=findings
        )
    else:
        request = COMPOSE_REQUEST
        system = build_system(profile, today, weather=weather, findings=findings)

    result = await _compose_once(
        llm, system, messages, request, previous_versions, profile, weather, findings
    )
    if isinstance(result, Itinerary):
        return result

    result = await _compose_once(
        llm, system, messages, repair_request(result, request), previous_versions, profile,
        weather, findings,
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
    findings: list[Finding],
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
    places = await locate_stops(draft, findings, previous_versions, profile)
    return build_itinerary(draft, previous_versions, profile, weather, places)


async def locate_stops(
    draft: ItineraryDraft,
    findings: list[Finding],
    previous_versions: list[Itinerary],
    profile: TripProfile,
) -> dict[str, StopPlace]:
    """Where each draft stop is, by stop key, from tools only: never from numbers in the draft
    and never from the city coordinates gathered for the weather.

    For each stop, the first that applies:
    1. its `place_ref` names a place the planner found → that place (id, address, coordinates,
       rating; source "Geoapify"). An unknown ref is ignored;
    2. a stop with the same name in an earlier version had coordinates → copy them (an edit
       copies stops with their letter tags as keys and no ref, so they keep their place);
    3. home, airports and the hotel → the geocoder (see `geocode_query`); for airports and the
       hotel a city-level match counts as not found.
    Any other stop is left out and stays off the map.
    """
    found = {finding.ref: finding.data for finding in findings if finding.tool in PLACE_TOOLS}
    newest_first = sorted(previous_versions, key=lambda itinerary: itinerary.version, reverse=True)
    earlier_stops = [
        stop
        for version in newest_first
        for stop in version.stops
        if stop.lat is not None and stop.lng is not None
    ]
    places: dict[str, StopPlace] = {}
    for stop in draft.stops:
        data = found.get(stop.place_ref or "")
        if data is not None and data.get("lat") is not None and data.get("lng") is not None:
            places[stop.key] = StopPlace(
                lat=data["lat"],
                lng=data["lng"],
                address=data.get("address"),
                place_id=data.get("id"),
                rating=data.get("rating"),
                source=PLACES_SOURCE,
            )
            continue

        earlier = next(
            (s for s in earlier_stops if normalize_name(s.name) == normalize_name(stop.name)),
            None,
        )
        if earlier is not None and earlier.lat is not None and earlier.lng is not None:
            places[stop.key] = StopPlace(
                lat=earlier.lat,
                lng=earlier.lng,
                address=earlier.address,
                place_id=earlier.place_id,
                rating=earlier.rating,
                # Only places from the places search have a place_id.
                source=PLACES_SOURCE if earlier.place_id else None,
            )
            continue

        query = geocode_query(stop, draft, profile)
        if query is None:
            continue
        # Home is the origin city, so a city-level match is right for it; for an airport or the
        # hotel it would pin the city centre, so it counts as not found (D27).
        precise = stop.kind != "home"
        result = await asyncio.to_thread(places_tool.geocode, query, precise=precise)
        if result.ok:
            places[stop.key] = StopPlace(
                lat=result.data["lat"],
                lng=result.data["lng"],
                address=stop.address or result.data.get("address"),
            )
    return places


def geocode_query(stop: DraftStop, draft: ItineraryDraft, profile: TripProfile) -> str | None:
    """What to geocode for a stop with no found place, or None if it isn't geocoded.

    Only GEOCODE_KINDS are. Home is the profile's origin (or its address). Others use their
    address when the draft has one, since geocoders handle addresses best, else "name, city"
    with the city of the first day that visits the stop.
    """
    if stop.kind not in GEOCODE_KINDS:
        return None
    if stop.kind == "home":
        return profile.origin or stop.address
    if stop.address:
        return stop.address
    return f"{stop.name}, {stop_city(stop.key, draft)}"


def stop_city(key: str, draft: ItineraryDraft) -> str:
    """The city of the first day with an item at this stop, else the trip's first city."""
    for day in draft.days:
        if any(item.stop_key == key for item in day.items):
            return day.city
    return draft.cities[0].name


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
    findings: list[Finding] | None = None,
) -> str:
    """System text for the compose call: its prompt plus today's date, the profile, the
    gathered weather and the places the planner found (by ref).

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
    places_text = render_places(findings or [])
    if places_text:
        parts.append(places_text)
    if current_plan is not None:
        parts.append(
            f"## Current plan (version {current_plan.version})\n"
            "The plan to update, as an ItineraryDraft. Its stop keys are the stops' letter tags.\n"
            + as_draft(current_plan).model_dump_json(exclude_none=True)
        )
    return "\n\n".join(parts)


def render_places(findings: list[Finding]) -> str:
    """The found places for the compose prompt, one line each, e.g.
    `- p1 · The Tech Interactive · entertainment.museum · 201 S Market St, San Jose · rating 4.6`.
    A place found under two refs is listed once (its first ref). Empty text when none.
    The fake provider reads these lines (fake_provider.PLACE_LINE), so keep the format.
    """
    lines: list[str] = []
    seen_ids: set[str] = set()
    for finding in findings:
        data = finding.data
        place_id = str(data.get("id"))
        if finding.tool not in PLACE_TOOLS or place_id in seen_ids:
            continue
        seen_ids.add(place_id)
        parts = [finding.ref, str(data.get("name")), str(data.get("category") or "place")]
        if data.get("address"):
            parts.append(str(data["address"]))
        if data.get("rating") is not None:
            parts.append(f"rating {data['rating']}")
        lines.append("- " + " · ".join(parts))
    if not lines:
        return ""
    return (
        "## Places found (from the places service, Geoapify)\n"
        "Cite a place with its ref in the stop's `place_ref`.\n" + "\n".join(lines)
    )


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
