"""Itinerary (03-contracts §2.2) and its validation rules.

Fields that later stages fill (coordinates, place ids, ratings, prices, weather, transit)
are nullable; in Stage 1 they are null. Validation error messages say what is wrong and
where, because the generate step (S1.10) sends them back to the LLM for one retry.
"""

import datetime as dt  # module import: fields named `date` would shadow a bare `date` type
import re
from collections import Counter
from collections.abc import Sequence
from itertools import pairwise
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.schemas.common import Link, Money, TimeHHMM, UtcDatetime

PlaceTag = Annotated[str, StringConstraints(pattern=r"^[A-Z]+$")]  # A..Z, AA, AB, ...
LodgingTag = Annotated[str, StringConstraints(pattern=r"^H[12]$")]  # H1, H2
Lat = Annotated[float, Field(ge=-90, le=90)]
Lng = Annotated[float, Field(ge=-180, le=180)]

PlaceCategory = Literal[
    "food", "sight", "nature", "nightlife", "shopping", "museum", "activity", "transport_hub", "other"
]
CostCategory = Literal["lodging", "food", "activities", "local_transport", "other"]
ItemKind = Literal["activity", "meal", "transit", "lodging", "free_time"]
TransitMode = Literal["walk", "transit", "drive", "rideshare", "flight", "train"]
ChecklistCategory = Literal["flights", "lodging", "activities", "local_transport", "documents", "packing"]


class City(BaseModel):
    name: str
    region: str
    country: str
    lat: Lat | None = None  # null until looked up (Stage 2)
    lng: Lng | None = None


class CostBreakdown(BaseModel):
    category: CostCategory
    low: float
    high: float


class CostEstimate(BaseModel):
    """Per person; flights excluded."""

    currency: Literal["USD"] = "USD"
    low: float
    high: float
    breakdown: list[CostBreakdown] = Field(default_factory=list)


class Place(BaseModel):
    tag: PlaceTag
    name: str
    address: str | None = None
    lat: Lat | None = None
    lng: Lng | None = None
    place_id: str | None = None
    category: PlaceCategory
    rating: float | None = None
    maps_url: str


class LodgingAlternative(BaseModel):
    name: str
    total_price: Money
    rating: float | None = None
    link: str


class Lodging(BaseModel):
    tag: LodgingTag
    name: str
    city: str
    address: str | None = None
    lat: Lat | None = None
    lng: Lng | None = None
    place_id: str | None = None
    check_in: dt.date
    check_out: dt.date
    nights: int = Field(ge=1)
    rating: float | None = None
    price_per_night: Money | None = None
    total_price: Money | None = None  # whole stay, whole room
    price_as_of: UtcDatetime | None = None
    price_source: Literal["serpapi_google_hotels", "none"]
    alternatives: list[LodgingAlternative] = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list)

    @model_validator(mode="after")
    def _no_prices_without_source(self) -> "Lodging":
        has_price = any(v is not None for v in (self.price_per_night, self.total_price, self.price_as_of))
        if self.price_source == "none" and has_price:
            raise ValueError(
                f"lodging {self.tag}: price_source is 'none', so price_per_night, total_price "
                "and price_as_of must be null"
            )
        return self


class Weather(BaseModel):
    high_f: float | None = None  # set for forecast/climate; null when "unavailable"
    low_f: float | None = None  # set for forecast/climate; null when "unavailable"
    condition: str | None = None  # may be null (e.g. a climate estimate)
    precip_chance: int | None = Field(default=None, ge=0, le=100)  # may be null
    source: Literal["forecast", "climate", "unavailable"]

    @model_validator(mode="after")
    def _numbers_match_source(self) -> "Weather":
        values = (self.high_f, self.low_f, self.condition, self.precip_chance)
        if self.source == "unavailable" and any(v is not None for v in values):
            raise ValueError(
                "weather: source is 'unavailable', so high_f, low_f, condition and precip_chance must be null"
            )
        if self.source != "unavailable" and (self.high_f is None or self.low_f is None):
            raise ValueError(f"weather: source is '{self.source}', so high_f and low_f are required")
        return self


class Transit(BaseModel):
    mode: TransitMode
    duration_min: int = Field(ge=0)
    distance_mi: float = Field(ge=0)


class Item(BaseModel):
    id: str
    kind: ItemKind
    title: str
    description: str
    start_time: TimeHHMM
    end_time: TimeHHMM
    place_tag: str | None = None  # place tag ("A"), lodging tag ("H1"), or null for generic items
    est_cost: Money | None = None  # per person
    booking_required: bool = False
    checklist_item_id: str | None = None
    transit_from_previous: Transit | None = None  # null for the first item and until Stage 3
    tips: str | None = None


class Day(BaseModel):
    day_number: int
    date: dt.date
    title: str
    city: str
    lodging_tag: str | None = None  # e.g. no hotel on the departure day
    weather: Weather | None = None  # whole object null until Stage 3
    items: list[Item] = Field(default_factory=list)


class ChecklistItem(BaseModel):
    id: str
    category: ChecklistCategory
    title: str
    details: str | None = None
    date: dt.date | None = None
    recommended_option: str | None = None
    links: list[Link] = Field(default_factory=list)
    bookable_by_us: bool = False  # "Book for me" is "coming soon" in the MVP
    status: Literal["todo", "done"] = "todo"


class Itinerary(BaseModel):
    id: str
    version: int = Field(ge=1)
    title: str
    summary: str
    start_date: dt.date
    end_date: dt.date
    travelers: int = Field(ge=1)
    cities: list[City] = Field(min_length=1, max_length=2)
    cost_estimate: CostEstimate | None = None
    weather_summary: str | None = None  # null until Stage 3
    assumptions: list[str] = Field(default_factory=list)
    places: list[Place] = Field(default_factory=list)
    lodging: list[Lodging] = Field(default_factory=list, max_length=2)
    days: list[Day] = Field(min_length=1, max_length=7)
    checklist: list[ChecklistItem] = Field(default_factory=list)
    created_at: UtcDatetime

    @model_validator(mode="after")
    def _check_consistency(self) -> "Itinerary":
        """Cross-field rules from 03 §2.2. Collects every problem into one error."""
        problems: list[str] = day_problems(self.start_date, self.end_date, self.days)

        # Tags and IDs are unique.
        place_tags = {p.tag for p in self.places}
        lodging_tags = {h.tag for h in self.lodging}
        checklist_ids = {c.id for c in self.checklist}
        item_ids = [item.id for day in self.days for item in day.items]
        for label, values in (
            ("places tag", [p.tag for p in self.places]),
            ("lodging tag", [h.tag for h in self.lodging]),
            ("checklist id", [c.id for c in self.checklist]),
            ("item id", item_ids),
        ):
            for value in _duplicates(values):
                problems.append(f"{label} '{value}' is used more than once")

        # Items are sorted and every reference resolves.
        for day in self.days:
            if day.lodging_tag is not None and day.lodging_tag not in lodging_tags:
                problems.append(f"day {day.day_number}: lodging_tag '{day.lodging_tag}' not found in lodging")
            for prev, item in pairwise(day.items):
                if item.start_time < prev.start_time:
                    problems.append(
                        f"day {day.day_number}: items not sorted by start_time "
                        f"({item.id} at {item.start_time} is listed after {prev.id} at {prev.start_time})"
                    )
            for item in day.items:
                where = f"day {day.day_number} item {item.id}"
                if item.place_tag is not None:
                    is_lodging = _is_lodging_tag(item.place_tag)
                    if item.place_tag not in (lodging_tags if is_lodging else place_tags):
                        target = "lodging" if is_lodging else "places"
                        problems.append(f"{where}: place_tag '{item.place_tag}' not found in {target}")
                if item.checklist_item_id is not None and item.checklist_item_id not in checklist_ids:
                    problems.append(
                        f"{where}: checklist_item_id '{item.checklist_item_id}' not found in checklist"
                    )
                if item.booking_required and item.checklist_item_id is None:
                    problems.append(f"{where}: booking_required is true but checklist_item_id is null")

        if problems:
            raise ValueError("; ".join(problems))
        return self


class _DayLike(Protocol):
    day_number: int
    date: dt.date


def day_problems(start_date: dt.date, end_date: dt.date, days: Sequence[_DayLike]) -> list[str]:
    """Days line up with the date range. Shared with `ItineraryDraft`, so a bad draft fails early."""
    problems: list[str] = []
    span = (end_date - start_date).days + 1
    if span < 1:
        problems.append(f"end_date {end_date} is before start_date {start_date}")
    elif len(days) != span:
        problems.append(f"{len(days)} days given, but {start_date} to {end_date} is {span} days")
    for i, day in enumerate(days):
        if day.day_number != i + 1:
            problems.append(f"days[{i}]: day_number is {day.day_number}, expected {i + 1}")
        expected_date = start_date + dt.timedelta(days=i)
        if day.date != expected_date:
            problems.append(f"day {day.day_number}: date is {day.date}, expected {expected_date}")
    return problems


def _is_lodging_tag(tag: str) -> bool:
    """Lodging tags are H + digits (H1, H2); a bare "H" is an ordinary place tag."""
    return re.fullmatch(r"H\d+", tag) is not None


def _duplicates(values: list[str]) -> list[str]:
    return [value for value, count in Counter(values).items() if count > 1]
