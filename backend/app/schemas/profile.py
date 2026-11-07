"""TripProfile (contracts §2.1). Every field is optional; the server fills `missing_required`."""

from datetime import date
from typing import Literal

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
    budget_level: BudgetLevel | None = None
    interests: list[str] = Field(default_factory=list)
    dietary: str | None = None
    pace: Pace | None = None
    transport: Transport | None = None
    notes: str | None = None
    missing_required: list[RequiredField] = Field(default_factory=list)
