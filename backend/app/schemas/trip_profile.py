"""TripProfile (03-contracts §2.1). Filled by chat from Stage 3; empty in Stage 1."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

RequiredSlot = Literal["destination", "dates", "origin", "travelers", "interests"]


class TripProfile(BaseModel):
    cities: list[str] = Field(default_factory=list, max_length=2)
    vibe: str | None = None  # when the user wants suggestions, e.g. "beach, ≤4h drive"
    start_date: date | None = None
    end_date: date | None = None
    duration_days: int | None = Field(default=None, ge=1, le=7)
    rough_timing: str | None = None  # "a weekend in March" before exact dates are known
    origin: str | None = None
    travelers: int | None = Field(default=None, ge=1, le=6)  # adults
    budget_level: Literal["budget", "mid", "splurge"] = "budget"
    interests: list[str] = Field(default_factory=list)
    pace: Literal["relaxed", "balanced", "packed"] | None = None
    transport: Literal["car", "transit", "walk", "mixed"] | None = None
    must_see: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    dietary: str | None = None
    hotel_area: str | None = None
    notes: str | None = None
    missing_required: list[RequiredSlot] = Field(default_factory=list)  # computed server-side

    @field_validator("budget_level", mode="before")
    @classmethod
    def _budget_defaults_when_null(cls, value: object) -> object:
        """An explicit null means "not given": fall back to the default, budget."""
        return "budget" if value is None else value
