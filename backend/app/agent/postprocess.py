"""Postprocess: turn the LLM's ItineraryDraft into a full Itinerary (contracts §2.2, §2.3, §3).

Code owns ids, version, tags, sources and `updated_in_version`. City coordinates, day weather
and the weather summary come from the gathered weather (never from the draft). Stop
coordinates, addresses and place ids come from the places tool, found by the pipeline
(`StopPlace`); never from the draft or the weather's city coordinates. Things that later steps
fill from tools (prices, links, transit, bookings) stay null or empty here. The finished itinerary is validated; any broken rules come back as a list of error
strings instead of an exception, so the compose call can try once more with them (step 22).
"""

import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from pydantic import ValidationError
from pydantic_core import ErrorDetails

from app.agent.tags import assign_tags, index_for_tag
from app.schemas.itinerary import (
    City,
    CostEstimate,
    Day,
    DayWeather,
    DraftItem,
    DraftLodging,
    Itinerary,
    ItineraryDraft,
    ItineraryItem,
    Lodging,
    Money,
    Stop,
)
from app.schemas.profile import TripProfile

DEFAULT_ITEM_SOURCE = "AI suggestion"
BUDGET_ASSUMPTION = "Budget level assumed (none given)"
WEATHER_ASSUMPTION = "Weather for {city} couldn't be loaded; check a forecast before you go"
PLACES_SOURCE = "Geoapify"  # item source when its stop is a place the places search found


@dataclass
class CityWeather:
    """What the gather step found for one city: its coordinates and weather per date.

    `error` is set when the weather tool failed; `days` is then empty (the coordinates may
    still be known if only the forecast failed).
    """

    name: str  # the city as the profile names it, e.g. "San Jose, CA"
    lat: float | None = None
    lng: float | None = None
    days: dict[date, DayWeather] = field(default_factory=dict)
    error: str | None = None


@dataclass
class StopPlace:
    """Where one draft stop is, from a tool (the pipeline finds it; see pipeline.locate_stops).

    `source` is the item source for items at this stop (e.g. "Geoapify" for a place the
    places search found); None keeps the default "AI suggestion" (e.g. a geocoded home).
    """

    lat: float
    lng: float
    address: str | None = None
    place_id: str | None = None
    rating: float | None = None
    source: str | None = None


def short_city_name(name: str) -> str:
    """The name without its region: "San Jose, CA" → "San Jose"."""
    return name.split(",")[0].strip()


def build_itinerary(
    draft: ItineraryDraft,
    previous_versions: list[Itinerary],
    profile: TripProfile,
    weather: list[CityWeather] | None = None,
    places: dict[str, StopPlace] | None = None,
) -> Itinerary | list[str]:
    """The finished Itinerary, or a list of validation errors if it breaks the §2.2 rules.

    `previous_versions` are all earlier itineraries of the session (empty for the first plan).
    The new plan reuses the id of the latest one, so all versions share one plan id.
    `weather` is the gather step's result (empty when nothing was gathered).
    `places` maps a draft stop key to its tool location; stops without one stay off the map.
    """
    latest = max(previous_versions, key=lambda itinerary: itinerary.version, default=None)
    try:
        itinerary = _assemble(
            draft, latest, previous_versions, profile, weather or [], places or {}
        )
    except ValidationError as error:
        return [line for detail in error.errors() for line in _error_lines(detail)]

    if latest is not None:
        _mark_updated_items(itinerary, latest)
    return itinerary


def _assemble(
    draft: ItineraryDraft,
    latest: Itinerary | None,
    previous_versions: list[Itinerary],
    profile: TripProfile,
    weather: list[CityWeather],
    places: dict[str, StopPlace],
) -> Itinerary:
    """Copy the draft into an Itinerary. Raises ValidationError when a §2.2 rule breaks."""
    place_ids = {key: place.place_id for key, place in places.items() if place.place_id}
    tags = assign_tags(draft, previous_versions, place_ids)
    days = [
        Day(
            day_number=day.day_number,
            date=day.date,
            title=day.title,
            city=day.city,
            weather=_day_weather(day.city, day.date, weather, len(draft.cities)),
            items=[
                _item(item, f"d{day.day_number}-i{index}", tags, places)
                for index, item in enumerate(day.items, start=1)
            ],
        )
        for day in draft.days
    ]
    return Itinerary(
        id=latest.id if latest else str(uuid.uuid4()),
        version=latest.version + 1 if latest else 1,
        title=draft.title,
        summary=draft.summary,
        start_date=draft.start_date,
        end_date=draft.end_date,
        travelers=draft.travelers,
        cities=[
            _city(city.name, city.region, city.country, weather, len(draft.cities))
            for city in draft.cities
        ],
        cost_estimate=_cost_estimate(draft.cost_estimate),
        weather_summary=weather_summary(days),
        assumptions=_assumptions(draft, profile, weather),
        stops=_stops(draft, tags, places),
        lodging=[_lodging(lodging, tags) for lodging in draft.lodging],
        days=days,
        bookings=[],
        created_at=datetime.now(timezone.utc),
    )


def _cost_estimate(estimate: CostEstimate | None) -> CostEstimate | None:
    # The draft's totals are always an AI estimate, whatever source the LLM wrote.
    if estimate is None:
        return None
    return estimate.model_copy(update={"source": "ai_estimate"})


def _assumptions(
    draft: ItineraryDraft, profile: TripProfile, weather: list[CityWeather]
) -> list[str]:
    assumptions = list(draft.assumptions)
    # Decisions D17: plans assume budget when the user never stated a budget level.
    if profile.budget_level is None and BUDGET_ASSUMPTION not in assumptions:
        assumptions.insert(0, BUDGET_ASSUMPTION)
    for city in weather:
        note = WEATHER_ASSUMPTION.format(city=short_city_name(city.name))
        if city.error is not None and note not in assumptions:
            assumptions.append(note)
    return assumptions


def _gathered_city(
    name: str, weather: list[CityWeather], draft_city_count: int
) -> CityWeather | None:
    """The gathered city with this name ("San Jose" matches "San Jose, CA"). When both the
    draft and the gathered data have a single city, it is used for any name, since the draft
    may spell the city differently. With two draft cities an unmatched name gets None, so it
    never borrows the other city's coordinates or weather."""
    key = short_city_name(name).lower()
    for city in weather:
        if short_city_name(city.name).lower() == key:
            return city
    return weather[0] if len(weather) == 1 and draft_city_count == 1 else None


def _city(
    name: str,
    region: str | None,
    country: str | None,
    weather: list[CityWeather],
    draft_city_count: int,
) -> City:
    gathered = _gathered_city(name, weather, draft_city_count)
    return City(
        name=name,
        region=region,
        country=country,
        lat=gathered.lat if gathered else None,  # null when the city wasn't geocoded
        lng=gathered.lng if gathered else None,
    )


def _day_weather(
    city: str, day: date, weather: list[CityWeather], draft_city_count: int
) -> DayWeather | None:
    gathered = _gathered_city(city, weather, draft_city_count)
    return gathered.days.get(day) if gathered else None


def weather_summary(days: list[Day]) -> str | None:
    """A one-line summary of the days' weather, e.g. "Mild and sunny, 48–68 °F"; None when no
    day has weather. Built by code from the tool data only."""
    known = [day.weather for day in days if day.weather is not None]
    if not known:
        return None
    low = min(weather.low_f for weather in known)
    high = max(weather.high_f for weather in known)
    feel = _feel(sum(weather.high_f for weather in known) / len(known))
    condition = Counter(weather.condition for weather in known).most_common(1)[0][0]
    text = feel if condition == "unknown" else f"{feel} and {condition}"
    summary = f"{text}, {low:.0f}–{high:.0f} °F"
    if any(weather.source == "climate" for weather in known):
        summary += " (seasonal average)"
    return summary


def _feel(average_high_f: float) -> str:
    if average_high_f >= 85:
        return "Hot"
    if average_high_f >= 72:
        return "Warm"
    if average_high_f >= 58:
        return "Mild"
    if average_high_f >= 45:
        return "Cool"
    return "Cold"


def _stops(
    draft: ItineraryDraft, tags: dict[str, str], places: dict[str, StopPlace]
) -> list[Stop]:
    """One stop per tag (two draft keys can be the same place), sorted by letter. Coordinates,
    place_id, rating and (when the tool has one) the address come from `places`; map_url comes
    from links (step 41)."""
    stops_by_tag: dict[str, Stop] = {}
    for draft_stop in draft.stops:
        tag = tags[draft_stop.key]
        if tag in stops_by_tag:
            continue
        place = places.get(draft_stop.key)
        stops_by_tag[tag] = Stop(
            tag=tag,
            name=draft_stop.name,
            kind=draft_stop.kind,
            address=(place.address if place and place.address else draft_stop.address),
            lat=place.lat if place else None,
            lng=place.lng if place else None,
            place_id=place.place_id if place else None,
            rating=place.rating if place else None,
        )
    return sorted(stops_by_tag.values(), key=lambda stop: index_for_tag(stop.tag))


def _lodging(lodging: DraftLodging, tags: dict[str, str]) -> Lodging:
    per_night = lodging.price_per_night
    total = (
        Money(amount=per_night.amount * lodging.nights, currency=per_night.currency)
        if per_night is not None
        else None
    )
    return Lodging(
        stop_tag=tags[lodging.stop_key],
        check_in=lodging.check_in,
        check_out=lodging.check_out,
        nights=lodging.nights,
        price_per_night=per_night,
        total_price=total,
        price_source="ai_estimate" if per_night is not None else "none",
    )


def _item(
    item: DraftItem, item_id: str, tags: dict[str, str], places: dict[str, StopPlace]
) -> ItineraryItem:
    place = places.get(item.stop_key) if item.stop_key else None
    return ItineraryItem(
        id=item_id,
        kind=item.kind,
        stop_tag=tags[item.stop_key] if item.stop_key else None,
        description=item.description,
        start_time=item.start_time,
        duration_min=item.duration_min,
        nights=item.nights,
        est_cost=item.est_cost,
        cost_source="ai_estimate" if item.est_cost is not None else None,
        booking_required=item.booking_required,
        why=item.why,
        source=(place.source if place and place.source else DEFAULT_ITEM_SOURCE),
    )


def _mark_updated_items(itinerary: Itinerary, previous: Itinerary) -> None:
    """Contracts §3: an item with no identical item in version N−1 gets `updated_in_version = N`;
    otherwise it keeps that previous item's value."""
    previous_values: dict[tuple[str | None, str, str, str], int | None] = {}
    for day in previous.days:
        for item in day.items:
            previous_values.setdefault(_item_identity(item), item.updated_in_version)

    for day in itinerary.days:
        for item in day.items:
            identity = _item_identity(item)
            if identity in previous_values:
                item.updated_in_version = previous_values[identity]
            else:
                item.updated_in_version = itinerary.version


def _item_identity(item: ItineraryItem) -> tuple[str | None, str, str, str]:
    return (item.stop_tag, item.kind, item.start_time, item.description)


def _error_lines(detail: ErrorDetails) -> list[str]:
    """Readable lines from one Pydantic error, e.g. "days: List should have at most 7 items".

    The §2.2 rule check reports all its errors in one message joined by "; " (see
    `itinerary_errors`), so that message is split back into one line per broken rule.
    """
    location = ".".join(str(part) for part in detail["loc"])
    message = detail["msg"].removeprefix("Value error, ")
    if location:
        return [f"{location}: {message}"]
    return message.split("; ")
