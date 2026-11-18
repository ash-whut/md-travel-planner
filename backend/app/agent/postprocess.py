"""Postprocess: turn the LLM's ItineraryDraft into a full Itinerary (contracts §2.2, §2.3, §3).

Code owns ids, version, tags, sources and `updated_in_version`. City coordinates, day weather
and the weather summary come from the gathered weather (never from the draft). Stop
coordinates, addresses and place ids come from the places tool, found by the pipeline
(`StopPlace`); never from the draft or the weather's city coordinates. A hotel stop that cites a
hotels-tool result gets its lodging price and `price_as_of` from the tool (`HotelPrice`), which
wins over the draft's estimate. Links come from `tools/links.py` (contracts §6): a `map_url` per
stop and the hotel links per lodging; flight items have no price ("check link"). The Book
tab's `bookings` (a round-trip flight, one per hotel, one per booking-required activity) are
built by code too, and keep their status from the previous version. Travel between stops
(`transit_from_previous`) is a code estimate from the stops' coordinates. The finished
itinerary is validated; any broken rules come back as a list of error strings instead of an
exception, so the compose call can try once more with them (step 22).
"""

import math
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from pydantic import ValidationError
from pydantic_core import ErrorDetails

from app.agent.tags import assign_tags, index_for_tag
from app.schemas.itinerary import (
    Booking,
    City,
    CostEstimate,
    CostSource,
    Day,
    DayWeather,
    DraftItem,
    DraftLodging,
    Itinerary,
    ItineraryDraft,
    ItineraryItem,
    Link,
    Lodging,
    Money,
    PriceSource,
    Stop,
    TransitLeg,
    TransitMode,
)
from app.schemas.profile import Transport, TripProfile
from app.tools import links

DEFAULT_ITEM_SOURCE = "AI suggestion"
BUDGET_ASSUMPTION = "Budget level assumed (none given)"
WEATHER_ASSUMPTION = "Weather for {city} couldn't be loaded; check a forecast before you go"
PLACES_SOURCE = "Geoapify"  # item source when its stop is a place the places search found
HOTELS_SOURCE = "SerpApi Google Hotels"  # + " · as of …" for items at a priced hotel
GOOGLE_HOTELS_LABEL = "Google Hotels"
BOOKING_COM_LABEL = "Booking.com"
HOTEL_SITE_LABEL = "Hotel site"  # SerpApi's `link`: the hotel's own website
GOOGLE_FLIGHTS_LABEL = "Google Flights"
TICKETS_LABEL = "Find tickets"
FLIGHT_BOOKING_ID = "bk-flight"
FLIGHT_BOOKING_TITLE = "Flight Booking"
HOTEL_BOOKING_TITLE = "Hotel Booking"

EARTH_RADIUS_MI = 3958.8
WALK_MAX_MI = 1.0  # legs up to this distance are walked
SPEED_MPH: dict[TransitMode, float] = {"walk": 3, "transit": 12, "drive": 25, "rideshare": 25}
# The profile's transport choice → the mode for legs too long to walk.
MODE_FOR_TRANSPORT: dict[Transport, TransitMode] = {
    "car": "drive",
    "transit": "transit",
    "rideshare": "rideshare",
    "mixed": "rideshare",
}
DEFAULT_MODE: TransitMode = "rideshare"  # no transport stated


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
class HotelPrice:
    """A hotel's price from the hotels tool, for the stop that cites the hotel.

    `source` "serpapi_google_hotels" has a per-night price and `as_of` (when SerpApi was
    asked); "none" has no price, so the plan shows "check link". `from_serpapi` marks a hotel
    SerpApi found even without a price (else it is a places-search fallback). `link` is the
    hotel's link from SerpApi, if any: its own website (the lodging's "Hotel site" link).
    """

    per_night: Money | None
    source: PriceSource
    as_of: datetime | None = None
    link: str | None = None
    from_serpapi: bool = False


@dataclass
class StopPlace:
    """Where one draft stop is, from a tool (the pipeline finds it; see pipeline.locate_stops).

    `source` is the item source for items at this stop (e.g. "Geoapify" for a place the
    places search found); None keeps the default "AI suggestion" (e.g. a geocoded home).
    `hotel` is set when the stop is a hotel the hotels tool found; its price replaces the
    draft's lodging estimate.
    """

    lat: float
    lng: float
    address: str | None = None
    place_id: str | None = None
    rating: float | None = None
    source: str | None = None
    hotel: HotelPrice | None = None


def short_city_name(name: str) -> str:
    """The name without its region: "San Jose, CA" → "San Jose"."""
    return name.split(",")[0].strip()


def hotel_source(hotel: HotelPrice) -> str:
    """The item source for a hotel stop: "SerpApi Google Hotels · as of Nov 1, 6:04 PM UTC"
    for a priced hotel, plain "SerpApi Google Hotels" for a SerpApi hotel with no price; a
    fallback hotel came from the places search ("Geoapify")."""
    if hotel.source != "serpapi_google_hotels" or hotel.as_of is None:
        return HOTELS_SOURCE if hotel.from_serpapi else PLACES_SOURCE
    as_of = hotel.as_of.astimezone(timezone.utc)
    time = as_of.strftime("%I:%M %p").lstrip("0")
    return f"{HOTELS_SOURCE} · as of {as_of:%b} {as_of.day}, {time} UTC"


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

    build_bookings(itinerary, latest)
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
    cities = stop_cities(draft)
    stops = _stops(draft, tags, places, cities, profile.origin)
    nights = {lodging.stop_key: lodging.nights for lodging in draft.lodging}
    days = [
        Day(
            day_number=day.day_number,
            date=day.date,
            title=day.title,
            city=day.city,
            weather=_day_weather(day.city, day.date, weather, len(draft.cities)),
            items=[
                _item(item, f"d{day.day_number}-i{index}", tags, places, nights)
                for index, item in enumerate(day.items, start=1)
            ],
        )
        for day in draft.days
    ]
    set_travel_estimates(days, stops, profile.transport)
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
        stops=stops,
        lodging=[
            _lodging(lodging, draft, tags, places, cities) for lodging in draft.lodging
        ],
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


def stop_cities(draft: ItineraryDraft) -> dict[str, str]:
    """Each draft stop key → the city of the first day with an item at it. A lodging stop that
    only the lodging list names gets the city of its check-in day. Any other stop falls back to
    the trip's first city."""
    cities: dict[str, str] = {}
    for day in draft.days:
        for item in day.items:
            if item.stop_key is not None:
                cities.setdefault(item.stop_key, day.city)
    city_by_date = {day.date: day.city for day in draft.days}
    first_city = draft.cities[0].name
    for stay in draft.lodging:
        cities.setdefault(stay.stop_key, city_by_date.get(stay.check_in, first_city))
    return {stop.key: cities.get(stop.key, first_city) for stop in draft.stops}


def _stops(
    draft: ItineraryDraft,
    tags: dict[str, str],
    places: dict[str, StopPlace],
    cities: dict[str, str],
    origin: str | None,
) -> list[Stop]:
    """One stop per tag (two draft keys can be the same place), sorted by letter. Coordinates,
    place_id, rating and (when the tool has one) the address come from `places`. Every stop gets
    a Google Maps `map_url` for "name, address", or "name, city" when it has no address (home:
    the profile's origin)."""
    stops_by_tag: dict[str, Stop] = {}
    for draft_stop in draft.stops:
        tag = tags[draft_stop.key]
        if tag in stops_by_tag:
            continue
        place = places.get(draft_stop.key)
        address = place.address if place and place.address else draft_stop.address
        city = cities[draft_stop.key]
        if draft_stop.kind == "home" and origin:
            city = origin
        stops_by_tag[tag] = Stop(
            tag=tag,
            name=draft_stop.name,
            kind=draft_stop.kind,
            address=address,
            lat=place.lat if place else None,
            lng=place.lng if place else None,
            place_id=place.place_id if place else None,
            rating=place.rating if place else None,
            map_url=links.map_url(draft_stop.name, address or city),
        )
    return sorted(stops_by_tag.values(), key=lambda stop: index_for_tag(stop.tag))


def _lodging(
    lodging: DraftLodging,
    draft: ItineraryDraft,
    tags: dict[str, str],
    places: dict[str, StopPlace],
    cities: dict[str, str],
) -> Lodging:
    """The lodging entry. At a hotel the hotels tool found, the tool's per-night price and
    `price_as_of` win over the draft's estimate (null when the tool had no price). The total is
    per night × nights, since the tool's total is for the dates it was asked about. Links: a
    Google Hotels search, a Booking.com search and, when SerpApi gave one, the hotel's own
    website ("Hotel site")."""
    place = places.get(lodging.stop_key)
    hotel = place.hotel if place else None
    if hotel is not None:
        per_night, price_source, as_of = hotel.per_night, hotel.source, hotel.as_of
    else:
        per_night, as_of = lodging.price_per_night, None
        price_source = "ai_estimate" if per_night is not None else "none"
    total = (
        Money(amount=per_night.amount * lodging.nights, currency=per_night.currency)
        if per_night is not None
        else None
    )
    name = next(stop.name for stop in draft.stops if stop.key == lodging.stop_key)
    city = cities[lodging.stop_key]
    hotel_links = [
        Link(label=GOOGLE_HOTELS_LABEL, url=links.google_hotels_url(name, city)),
        Link(
            label=BOOKING_COM_LABEL,
            url=links.booking_com_url(
                name, city, lodging.check_in, lodging.check_out, draft.travelers
            ),
        ),
    ]
    if hotel is not None and hotel.link:
        hotel_links.append(Link(label=HOTEL_SITE_LABEL, url=hotel.link))
    return Lodging(
        stop_tag=tags[lodging.stop_key],
        check_in=lodging.check_in,
        check_out=lodging.check_out,
        nights=lodging.nights,
        price_per_night=per_night,
        total_price=total,
        price_source=price_source,
        price_as_of=as_of,
        links=hotel_links,
    )


def _item(
    item: DraftItem,
    item_id: str,
    tags: dict[str, str],
    places: dict[str, StopPlace],
    lodging_nights: dict[str, int],
) -> ItineraryItem:
    """One item. A lodging item at a hotel the hotels tool found shows the tool's per-night
    price (null = "check link") and the stay's nights. A flight never shows a price until real
    fares exist (step 49): `est_cost` is null ("check link"), whatever the draft guessed."""
    place = places.get(item.stop_key) if item.stop_key else None
    est_cost = None if item.kind == "flight" else item.est_cost
    cost_source: CostSource | None = "ai_estimate" if est_cost is not None else None
    nights = item.nights
    if item.kind == "lodging" and place is not None and place.hotel is not None:
        est_cost = place.hotel.per_night
        cost_source = "tool" if est_cost is not None else None
        if nights is None and item.stop_key is not None:
            nights = lodging_nights.get(item.stop_key)
    return ItineraryItem(
        id=item_id,
        kind=item.kind,
        stop_tag=tags[item.stop_key] if item.stop_key else None,
        description=item.description,
        start_time=item.start_time,
        duration_min=item.duration_min,
        nights=nights,
        est_cost=est_cost,
        cost_source=cost_source,
        booking_required=item.booking_required,
        why=item.why,
        source=(place.source if place and place.source else DEFAULT_ITEM_SOURCE),
    )


@dataclass
class FlightRoute:
    """The trip's outbound flight: the departure airport, the arrival airport (None when the
    plan has no airport after it) and the destination text for the flight search."""

    departure: Stop
    arrival: Stop | None
    destination: str


def flight_route(itinerary: Itinerary) -> FlightRoute | None:
    """From the first flight item's stop (the departure airport) to the next airport stop after
    it (the arrival), else that day's city; None when no flight item has a stop."""
    stops = {stop.tag: stop for stop in itinerary.stops}
    items = [(day, item) for day in itinerary.days for item in day.items]
    for index, (day, item) in enumerate(items):
        if item.kind != "flight" or item.stop_tag is None:
            continue
        arrival = next(
            (
                stops[later.stop_tag]
                for _, later in items[index + 1 :]
                if later.stop_tag is not None
                and later.stop_tag != item.stop_tag
                and stops[later.stop_tag].kind == "airport"
            ),
            None,
        )
        destination = arrival.name if arrival else day.city
        return FlightRoute(stops[item.stop_tag], arrival, destination)
    return None


def flight_link(itinerary: Itinerary) -> Link | None:
    """The trip's round-trip Google Flights link (for the flight booking), on the trip's start
    and end dates; None when no flight item has a stop."""
    route = flight_route(itinerary)
    if route is None:
        return None
    return _route_link(route, itinerary)


def _route_link(route: FlightRoute, itinerary: Itinerary) -> Link:
    url = links.google_flights_url(
        route.departure.name, route.destination, itinerary.start_date, itinerary.end_date
    )
    return Link(label=GOOGLE_FLIGHTS_LABEL, url=url)


def build_bookings(itinerary: Itinerary, previous: Itinerary | None) -> None:
    """Fill `itinerary.bookings` (the Book tab) and the items' `booking_id`, in place.

    - one round-trip flight booking ("bk-flight") when the plan has a flight;
    - one lodging booking per hotel ("bk-hotel-D"): its total, `price_as_of` and links;
    - one per stop of a booking-required activity ("bk-activity-G"): a tickets search.
    Ids come from stop tags, which stay the same across versions, so each booking keeps its
    status from `previous` (the version before). A booking-required item gets the id of the
    booking for its stop (a flight item: the flight booking).
    """
    stops = {stop.tag: stop for stop in itinerary.stops}
    bookings: list[Booking] = []
    flight = _flight_booking(itinerary)
    if flight is not None:
        bookings.append(flight)
    lodging_ids: dict[str, str] = {}
    for lodging in itinerary.lodging:
        booking = _lodging_booking(lodging, stops[lodging.stop_tag])
        lodging_ids[lodging.stop_tag] = booking.id
        bookings.append(booking)
    activity_ids: dict[str, str] = {}
    for day in itinerary.days:
        for item in day.items:
            if not item.booking_required or item.kind != "activity" or item.stop_tag is None:
                continue
            if item.stop_tag not in activity_ids:
                booking = _activity_booking(item, day, stops[item.stop_tag])
                activity_ids[item.stop_tag] = booking.id
                bookings.append(booking)

    for day in itinerary.days:
        for item in day.items:
            if not item.booking_required:
                continue
            if item.kind == "flight" and flight is not None:
                item.booking_id = flight.id
            elif item.kind == "lodging" and item.stop_tag in lodging_ids:
                item.booking_id = lodging_ids[item.stop_tag]
            elif item.kind == "activity" and item.stop_tag in activity_ids:
                item.booking_id = activity_ids[item.stop_tag]

    earlier_bookings = previous.bookings if previous else []
    earlier_status = {booking.id: booking.status for booking in earlier_bookings}
    for booking in bookings:
        booking.status = earlier_status.get(booking.id, "todo")
    itinerary.bookings = bookings


def _flight_booking(itinerary: Itinerary) -> Booking | None:
    route = flight_route(itinerary)
    if route is None:
        return None
    tags = [route.departure.tag] + ([route.arrival.tag] if route.arrival else [])
    dates = _date_range(itinerary.start_date, itinerary.end_date)
    return Booking(
        id=FLIGHT_BOOKING_ID,
        kind="flight",
        tags=tags,
        title=FLIGHT_BOOKING_TITLE,
        details=f"{route.departure.name} → {route.destination} round trip · {dates}",
        estimate=None,  # flights are link-only until real fares (step 49)
        links=[_route_link(route, itinerary)],
    )


def _lodging_booking(lodging: Lodging, stop: Stop) -> Booking:
    nights = f"{lodging.nights} night" + ("" if lodging.nights == 1 else "s")
    return Booking(
        id=f"bk-hotel-{stop.tag}",
        kind="lodging",
        tags=[stop.tag],
        title=HOTEL_BOOKING_TITLE,
        details=f"{stop.name} · {nights} · {_date_range(lodging.check_in, lodging.check_out)}",
        estimate=lodging.total_price,
        price_as_of=lodging.price_as_of,
        links=list(lodging.links),
    )


def _activity_booking(item: ItineraryItem, day: Day, stop: Stop) -> Booking:
    return Booking(
        id=f"bk-activity-{stop.tag}",
        kind="activity",
        tags=[stop.tag],
        title=stop.name,
        details=f"{day.date:%a}, {_short_date(day.date)} · {_time_12h(item.start_time)}",
        estimate=item.est_cost,  # per person, an AI estimate
        links=[Link(label=TICKETS_LABEL, url=links.tickets_url(stop.name, day.city))],
    )


def _short_date(value: date) -> str:
    """A date like "Mar 5" (no zero padding)."""
    return f"{value:%b} {value.day}"


def _date_range(start: date, end: date) -> str:
    """Two dates like "Mar 5 – Mar 7"."""
    return f"{_short_date(start)} – {_short_date(end)}"


def _time_12h(time: str) -> str:
    """A local "HH:MM" time in 12h: "13:30" → "1:30 PM"."""
    hours, minutes = (int(part) for part in time.split(":"))
    suffix = "AM" if hours < 12 else "PM"
    return f"{(hours % 12) or 12}:{minutes:02d} {suffix}"


def haversine_mi(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """The great-circle distance between two points, in miles."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_MI * math.asin(math.sqrt(a))


def travel_mode(distance_mi: float, transport: Transport | None) -> TransitMode:
    """Walk short legs; otherwise use the traveler's transport (rideshare when none given)."""
    if distance_mi <= WALK_MAX_MI:
        return "walk"
    return MODE_FOR_TRANSPORT[transport] if transport else DEFAULT_MODE


def estimate_leg(
    origin: Stop, destination: Stop, transport: Transport | None, after_flight: bool = False
) -> TransitLeg | None:
    """An estimated leg between two stops; None when either stop has no coordinates.

    After a flight item the leg is the flight itself: its distance is known, its duration isn't.
    """
    if (
        origin.lat is None
        or origin.lng is None
        or destination.lat is None
        or destination.lng is None
    ):
        return None
    distance = haversine_mi(origin.lat, origin.lng, destination.lat, destination.lng)
    if after_flight:
        return TransitLeg(mode="flight", distance_mi=round(distance, 1), estimated=True)
    mode = travel_mode(distance, transport)
    minutes = max(1, round(distance / SPEED_MPH[mode] * 60))
    return TransitLeg(
        mode=mode, duration_min=minutes, distance_mi=round(distance, 1), estimated=True
    )


def set_travel_estimates(days: list[Day], stops: list[Stop], transport: Transport | None) -> None:
    """Fill each item's `transit_from_previous` from the previous item of the same day.

    It stays None for a day's first item, when either item has no stop or no coordinates, and
    when both items are at the same stop.
    """
    stops_by_tag = {stop.tag: stop for stop in stops}
    for day in days:
        for previous, item in zip(day.items, day.items[1:]):
            if previous.stop_tag is None or item.stop_tag is None:
                continue
            if previous.stop_tag == item.stop_tag:
                continue
            item.transit_from_previous = estimate_leg(
                stops_by_tag[previous.stop_tag],
                stops_by_tag[item.stop_tag],
                transport,
                after_flight=previous.kind == "flight",
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
