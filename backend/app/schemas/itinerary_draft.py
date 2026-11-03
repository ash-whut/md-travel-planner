"""ItineraryDraft: what the LLM fills in before code turns it into an Itinerary (04 §5.0).

It has no tags, IDs, links, coordinates, prices or weather: those come from code
(`agent/tags.py`, `agent/postprocess.py`) and, in later stages, from tools.

Top-level fields are all required with no defaults and unknown top-level keys are rejected:
`extract_json` can pull an inner object (say, one place) out of a truncated reply, and that
must fail validation rather than pass as an empty plan. Nested optional fields default to
null so a slightly terse model reply still validates.

Validation messages say what is wrong and where, because `generate_json` sends them back to
the LLM for one retry. Everything the LLM can get wrong is checked here, so postprocess can
assume a consistent draft.
"""

import datetime as dt  # module import: fields named `date` would shadow a bare `date` type
from collections import Counter
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.core.text import normalize_name
from app.schemas.common import Money, TimeHHMM
from app.schemas.itinerary import CostEstimate, ItemKind, PlaceCategory, day_problems

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class DraftCity(BaseModel):
    name: Name
    region: str  # state or region, e.g. "TX"
    country: str


class DraftPlace(BaseModel):
    name: Name
    category: PlaceCategory
    address: str | None = None


class DraftLodging(BaseModel):
    name: Name
    city: str
    check_in: dt.date
    check_out: dt.date  # nights are computed by code from the two dates


class DraftItem(BaseModel):
    kind: ItemKind
    title: str
    description: str
    start_time: TimeHHMM
    end_time: TimeHHMM
    place: DraftPlace | None = None  # null for free time, transit or generic items
    lodging_ref: str | None = Field(
        default=None, description="Exact name of one of the lodging entries, for hotel check-in/out items"
    )
    est_cost: Money | None = None  # per person
    booking_required: bool = False
    tips: str | None = None


class DraftDay(BaseModel):
    day_number: int
    date: dt.date
    title: str
    city: str
    items: list[DraftItem]


class ItineraryDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    summary: str
    start_date: dt.date
    end_date: dt.date
    travelers: int = Field(ge=1)
    cities: list[DraftCity] = Field(min_length=1, max_length=2)
    cost_estimate: CostEstimate | None  # per person, flights excluded; null if not estimated
    assumptions: list[str]
    lodging: list[DraftLodging] = Field(max_length=2)
    days: list[DraftDay] = Field(min_length=1, max_length=7)

    @model_validator(mode="after")
    def _check_consistency(self) -> "ItineraryDraft":
        problems = day_problems(self.start_date, self.end_date, self.days)

        for hotel in self.lodging:
            if hotel.check_out <= hotel.check_in:
                problems.append(
                    f"lodging '{hotel.name}': check_out {hotel.check_out} must be after check_in {hotel.check_in}"
                )
            # The last trip day is the departure day (no hotel night), so check_out <= end_date.
            if hotel.check_in < self.start_date or hotel.check_out > self.end_date:
                problems.append(
                    f"lodging '{hotel.name}': stay {hotel.check_in} to {hotel.check_out} must be within the trip "
                    f"(check_in on or after {self.start_date}, check_out on or before {self.end_date})"
                )
        hotels = sorted(self.lodging, key=lambda h: h.check_in)
        for first, second in zip(hotels, hotels[1:]):
            if second.check_in < first.check_out:
                problems.append(
                    f"lodging '{second.name}': check_in {second.check_in} is before check_out {first.check_out} "
                    f"of '{first.name}'; hotel stays must not overlap"
                )
        names = Counter(normalize_name(h.name) for h in self.lodging)
        if any(count > 1 for count in names.values()):
            problems.append("lodging entries must have different names")

        for day in self.days:
            for i, item in enumerate(day.items):
                if item.lodging_ref is not None and normalize_name(item.lodging_ref) not in names:
                    problems.append(
                        f"day {day.day_number} items[{i}]: lodging_ref '{item.lodging_ref}' "
                        "does not match the name of any lodging entry"
                    )

        if problems:
            raise ValueError("; ".join(problems))
        return self
