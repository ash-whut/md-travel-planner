"""Itinerary (contracts §2.2) and ItineraryDraft (contracts §2.3).

`Itinerary` is what we store and send to the frontend. Its validator runs the §2.2 rules and
reports every broken rule at once, so the compose repair try (step 22) can show them all.
`ItineraryDraft` is what the LLM returns: the same shape minus everything code owns.
"""

from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field, model_validator

MAX_DAYS = 7
MAX_CITIES = 2
TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"  # local "HH:MM", 24h

StopKind = Literal[
    "home", "airport", "lodging", "food", "sight", "museum",
    "nature", "nightlife", "shopping", "activity", "other",
]
ItemKind = Literal["transit", "flight", "lodging", "meal", "activity", "free_time"]
TransitMode = Literal["walk", "transit", "drive", "rideshare", "flight"]
PriceSource = Literal["ai_estimate", "serpapi_google_hotels", "none"]
CostSource = Literal["ai_estimate", "tool"]
BookingKind = Literal["flight", "lodging", "activity"]
BookingStatus = Literal["todo", "booked"]


# ---- Shared ----

class Money(BaseModel):
    amount: float
    currency: str = "USD"


class Link(BaseModel):
    label: str
    url: str


class CostEstimate(BaseModel):
    """Per person. Flights are included only if priced."""

    low: float
    high: float
    currency: str = "USD"
    source: str = "ai_estimate"


# ---- §2.2 Itinerary ----

class City(BaseModel):
    name: str
    region: str | None = None
    country: str | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)  # null until geocoded
    lng: float | None = Field(default=None, ge=-180, le=180)


class Stop(BaseModel):
    tag: str  # A..Z, AA, AB… assigned by code (contracts §3)
    name: str
    kind: StopKind
    address: str | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)  # null = shown as "off map"
    lng: float | None = Field(default=None, ge=-180, le=180)
    place_id: str | None = None
    rating: float | None = None
    map_url: str | None = None


class Lodging(BaseModel):
    stop_tag: str
    check_in: date
    check_out: date
    nights: int = Field(ge=1)
    price_per_night: Money | None = None
    total_price: Money | None = None
    price_source: PriceSource = "none"
    price_as_of: datetime | None = None  # null unless from a tool
    links: list[Link] = Field(default_factory=list)


class DayWeather(BaseModel):
    high_f: float
    low_f: float
    condition: str
    icon: str
    source: Literal["forecast", "climate"]


class TransitLeg(BaseModel):
    mode: TransitMode
    duration_min: int | None = None
    distance_mi: float | None = None
    estimated: bool = True


class ItineraryItem(BaseModel):
    id: str  # "d1-i1", set by code
    kind: ItemKind
    stop_tag: str | None = None  # null for untagged items (e.g. free time)
    description: str
    start_time: str = Field(pattern=TIME_PATTERN)
    duration_min: int | None = Field(default=None, ge=0)
    nights: int | None = None  # lodging items only
    est_cost: Money | None = None  # per person; null = "check link"
    cost_source: CostSource | None = None
    booking_required: bool = False
    booking_id: str | None = None
    why: str | None = None
    source: str | None = None
    transit_from_previous: TransitLeg | None = None  # null for the first item
    updated_in_version: int | None = None


class Day(BaseModel):
    day_number: int
    date: date
    title: str
    city: str
    weather: DayWeather | None = None  # null until the weather step
    items: list[ItineraryItem] = Field(default_factory=list)


class Booking(BaseModel):
    id: str
    kind: BookingKind
    tags: list[str] = Field(default_factory=list)
    title: str
    details: str
    estimate: Money | None = None  # null = "check link"
    price_as_of: datetime | None = None
    links: list[Link] = Field(default_factory=list)
    status: BookingStatus = "todo"


class Itinerary(BaseModel):
    id: str
    version: int = Field(ge=1)
    title: str
    summary: str
    start_date: date
    end_date: date
    travelers: int = Field(ge=1, le=6)
    cities: list[City] = Field(min_length=1, max_length=MAX_CITIES)
    cost_estimate: CostEstimate | None = None
    weather_summary: str | None = None  # always from the weather tool
    assumptions: list[str] = Field(default_factory=list)
    stops: list[Stop] = Field(default_factory=list)
    lodging: list[Lodging] = Field(default_factory=list, max_length=MAX_CITIES)
    days: list[Day] = Field(min_length=1, max_length=MAX_DAYS)
    bookings: list[Booking] = Field(default_factory=list)
    created_at: datetime

    @model_validator(mode="after")
    def check_rules(self) -> "Itinerary":
        errors = itinerary_errors(self)
        if errors:
            raise ValueError("; ".join(errors))
        return self


def itinerary_errors(itinerary: Itinerary) -> list[str]:
    """Every broken §2.2 rule that field limits can't express. Empty list = valid."""
    errors: list[str] = []

    expected_days = (itinerary.end_date - itinerary.start_date).days + 1
    if expected_days != len(itinerary.days):
        errors.append(
            f"trip runs {itinerary.start_date} to {itinerary.end_date} "
            f"({expected_days} days) but has {len(itinerary.days)} days"
        )
    for index, day in enumerate(itinerary.days):
        expected_number = index + 1
        if day.day_number != expected_number:
            errors.append(f"day {expected_number} has day_number {day.day_number}")
        expected_date = itinerary.start_date + timedelta(days=index)
        if day.date != expected_date:
            errors.append(f"day {expected_number} has date {day.date}, expected {expected_date}")
        times = [item.start_time for item in day.items]
        if times != sorted(times):
            errors.append(f"day {expected_number} items are not sorted by start_time")

    tags = [stop.tag for stop in itinerary.stops]
    duplicate_tags = sorted({tag for tag in tags if tags.count(tag) > 1})
    if duplicate_tags:
        errors.append(f"stop tags used twice: {', '.join(duplicate_tags)}")

    known_tags = set(tags)
    known_bookings = {booking.id for booking in itinerary.bookings}
    for day in itinerary.days:
        for item in day.items:
            if item.stop_tag is not None and item.stop_tag not in known_tags:
                errors.append(f"item {item.id} has unknown stop_tag {item.stop_tag}")
            if item.booking_id is not None and item.booking_id not in known_bookings:
                errors.append(f"item {item.id} has unknown booking_id {item.booking_id}")
    for lodging in itinerary.lodging:
        if lodging.stop_tag not in known_tags:
            errors.append(f"lodging has unknown stop_tag {lodging.stop_tag}")

    return errors


# ---- §2.3 ItineraryDraft (what the LLM returns) ----
# Code owns: ids, version, created_at, tags, updated_in_version, weather, transit_from_previous,
# coordinates, tool prices, price_as_of, links and bookings. Stops use a temporary `key`
# ("s1", "s2"…) that items and lodging point to with `stop_key`.

class DraftCity(BaseModel):
    name: str
    region: str | None = None
    country: str | None = None


class DraftStop(BaseModel):
    key: str
    name: str
    kind: StopKind = "other"
    address: str | None = None
    place_ref: str | None = None  # id of a gathered tool result (step 34+)


class DraftLodging(BaseModel):
    stop_key: str
    check_in: date
    check_out: date
    nights: int = Field(ge=1)
    price_per_night: Money | None = None  # an AI estimate; tool prices replace it later


class DraftItem(BaseModel):
    kind: ItemKind
    stop_key: str | None = None
    description: str
    start_time: str = Field(pattern=TIME_PATTERN)
    duration_min: int | None = Field(default=None, ge=0)
    nights: int | None = None
    est_cost: Money | None = None
    booking_required: bool = False
    why: str | None = None
    # No `source`: code sets it (contracts §2.3), so the LLM can't write the "Source:" text.


class DraftDay(BaseModel):
    day_number: int
    date: date
    title: str
    city: str
    items: list[DraftItem] = Field(default_factory=list)


class ItineraryDraft(BaseModel):
    title: str
    summary: str
    start_date: date
    end_date: date
    travelers: int = Field(ge=1, le=6)
    cities: list[DraftCity] = Field(min_length=1, max_length=MAX_CITIES)
    cost_estimate: CostEstimate | None = None
    assumptions: list[str] = Field(default_factory=list)
    stops: list[DraftStop] = Field(default_factory=list)
    lodging: list[DraftLodging] = Field(default_factory=list, max_length=MAX_CITIES)
    days: list[DraftDay] = Field(min_length=1, max_length=MAX_DAYS)

    @model_validator(mode="after")
    def check_stop_keys(self) -> "ItineraryDraft":
        # Only the key checks live here; postprocess maps keys to tags and needs them to resolve.
        # The day/date/sort rules run on the finished Itinerary.
        keys = [stop.key for stop in self.stops]
        errors: list[str] = []
        duplicate_keys = sorted({key for key in keys if keys.count(key) > 1})
        if duplicate_keys:
            errors.append(f"stop keys used twice: {', '.join(duplicate_keys)}")
        used_keys = [item.stop_key for day in self.days for item in day.items if item.stop_key]
        used_keys += [lodging.stop_key for lodging in self.lodging]
        unknown_keys = sorted(set(used_keys) - set(keys))
        if unknown_keys:
            errors.append(f"unknown stop_key: {', '.join(unknown_keys)}")
        if errors:
            raise ValueError("; ".join(errors))
        return self
