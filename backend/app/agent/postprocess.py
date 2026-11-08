"""Postprocess: turn the LLM's ItineraryDraft into a full Itinerary (contracts §2.2, §2.3, §3).

Code owns ids, version, tags, sources and `updated_in_version`. Things that later steps fill
from tools (coordinates, weather, prices, links, transit, bookings) stay null or empty here.
The finished itinerary is validated; any broken rules come back as a list of error strings
instead of an exception, so the compose call can try once more with them (step 22).
"""

import uuid
from datetime import datetime, timezone

from pydantic import ValidationError
from pydantic_core import ErrorDetails

from app.agent.tags import assign_tags, index_for_tag
from app.schemas.itinerary import (
    City,
    CostEstimate,
    Day,
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


def build_itinerary(
    draft: ItineraryDraft,
    previous_versions: list[Itinerary],
    profile: TripProfile,
) -> Itinerary | list[str]:
    """The finished Itinerary, or a list of validation errors if it breaks the §2.2 rules.

    `previous_versions` are all earlier itineraries of the session (empty for the first plan).
    The new plan reuses the id of the latest one, so all versions share one plan id.
    """
    latest = max(previous_versions, key=lambda itinerary: itinerary.version, default=None)
    try:
        itinerary = _assemble(draft, latest, previous_versions, profile)
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
) -> Itinerary:
    """Copy the draft into an Itinerary. Raises ValidationError when a §2.2 rule breaks."""
    tags = assign_tags(draft, previous_versions)
    return Itinerary(
        id=latest.id if latest else str(uuid.uuid4()),
        version=latest.version + 1 if latest else 1,
        title=draft.title,
        summary=draft.summary,
        start_date=draft.start_date,
        end_date=draft.end_date,
        travelers=draft.travelers,
        cities=[
            City(name=city.name, region=city.region, country=city.country)  # lat/lng null until geocoded
            for city in draft.cities
        ],
        cost_estimate=_cost_estimate(draft.cost_estimate),
        weather_summary=None,
        assumptions=_assumptions(draft, profile),
        stops=_stops(draft, tags),
        lodging=[_lodging(lodging, tags) for lodging in draft.lodging],
        days=[
            Day(
                day_number=day.day_number,
                date=day.date,
                title=day.title,
                city=day.city,
                weather=None,
                items=[
                    _item(item, f"d{day.day_number}-i{index}", tags)
                    for index, item in enumerate(day.items, start=1)
                ],
            )
            for day in draft.days
        ],
        bookings=[],
        created_at=datetime.now(timezone.utc),
    )


def _cost_estimate(estimate: CostEstimate | None) -> CostEstimate | None:
    # The draft's totals are always an AI estimate, whatever source the LLM wrote.
    if estimate is None:
        return None
    return estimate.model_copy(update={"source": "ai_estimate"})


def _assumptions(draft: ItineraryDraft, profile: TripProfile) -> list[str]:
    assumptions = list(draft.assumptions)
    # Decisions D17: plans assume budget when the user never stated a budget level.
    if profile.budget_level is None and BUDGET_ASSUMPTION not in assumptions:
        assumptions.insert(0, BUDGET_ASSUMPTION)
    return assumptions


def _stops(draft: ItineraryDraft, tags: dict[str, str]) -> list[Stop]:
    """One stop per tag (two draft keys can be the same place), sorted by letter."""
    stops_by_tag: dict[str, Stop] = {}
    for draft_stop in draft.stops:
        tag = tags[draft_stop.key]
        if tag in stops_by_tag:
            continue
        stops_by_tag[tag] = Stop(
            tag=tag,
            name=draft_stop.name,
            kind=draft_stop.kind,
            address=draft_stop.address,
            # Coordinates, place_id, rating and map_url come from tools/links (steps 34, 41).
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


def _item(item: DraftItem, item_id: str, tags: dict[str, str]) -> ItineraryItem:
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
        source=DEFAULT_ITEM_SOURCE,
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
