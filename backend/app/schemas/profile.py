"""TripProfile (contracts §2.1). Every field is optional; the server fills `missing_required`."""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

BudgetLevel = Literal["budget", "mid", "splurge"]
Pace = Literal["relaxed", "balanced", "packed"]
Transport = Literal["car", "transit", "rideshare", "mixed"]
RequiredField = Literal["destination", "dates", "origin", "travelers", "interests"]


class TripProfile(BaseModel):
    cities: list[str] = Field(default_factory=list, max_length=2)
    vibe: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    duration_days: int | None = Field(default=None, ge=1, le=7)
    rough_timing: str | None = None
    origin: str | None = None
    travelers: int | None = Field(default=None, ge=1, le=6)
    # null until the user states it; plans then assume "budget" (decisions D17).
    budget_level: BudgetLevel | None = None
    interests: list[str] = Field(default_factory=list)
    dietary: str | None = None
    pace: Pace | None = None
    transport: Transport | None = None
    notes: str | None = None
    missing_required: list[RequiredField] = Field(default_factory=list)


def missing_required(profile: TripProfile) -> list[RequiredField]:
    """The required details still unknown, in the order the agent asks for them (spec F2)."""
    has_destination = bool(profile.cities) or profile.vibe is not None
    # Dates are known as exact dates, or as a length plus rough timing ("a weekend in March").
    exact_dates = profile.start_date is not None and (
        profile.end_date is not None or profile.duration_days is not None
    )
    rough_dates = profile.rough_timing is not None and profile.duration_days is not None

    missing: list[RequiredField] = []
    if not has_destination:
        missing.append("destination")
    if not (exact_dates or rough_dates):
        missing.append("dates")
    if profile.origin is None:
        missing.append("origin")
    if profile.travelers is None:
        missing.append("travelers")
    if not profile.interests:
        missing.append("interests")
    return missing


def load_profile(data: dict[str, Any]) -> TripProfile:
    """A stored profile as a TripProfile, with `missing_required` recomputed so it is never stale."""
    profile = TripProfile.model_validate(data)
    profile.missing_required = missing_required(profile)
    return profile
