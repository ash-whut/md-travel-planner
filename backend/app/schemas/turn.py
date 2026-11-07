"""TurnAnalysis (contracts §2.4): the result of the one "understand" JSON call per user turn."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.profile import BudgetLevel, Pace, Transport

Action = Literal["chat", "generate", "edit"]


class ProfileUpdates(BaseModel):
    """A partial TripProfile: only the fields the user just stated. null / left out = no change.

    Same fields and limits as TripProfile, minus `missing_required` (the server computes it).
    """

    cities: list[str] | None = Field(default=None, max_length=2)
    vibe: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    duration_days: int | None = Field(default=None, ge=1, le=7)
    rough_timing: str | None = None
    origin: str | None = None
    travelers: int | None = Field(default=None, ge=1, le=6)
    budget_level: BudgetLevel | None = None
    interests: list[str] | None = None
    dietary: str | None = None
    pace: Pace | None = None
    transport: Transport | None = None
    notes: str | None = None


class TurnAnalysis(BaseModel):
    profile_updates: ProfileUpdates = Field(default_factory=ProfileUpdates)
    action: Action = "chat"
    # For edit: what to change, in plain words, e.g. "replace [F] with a vegan brunch spot".
    change_request: str | None = None
