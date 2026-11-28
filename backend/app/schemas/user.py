"""Accounts and the user profile (contracts §2.7)."""

from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.schemas.profile import BudgetLevel, Pace, Transport, TravelMode


class UserProfile(BaseModel):
    """Long-lived preferences, kept across trips. Each new trip's TripProfile starts from it."""

    home_city: str | None = Field(default=None, max_length=120)
    budget_level: BudgetLevel | None = None
    dietary: str | None = Field(default=None, max_length=120)
    pace: Pace | None = None
    transport: Transport | None = None
    travel_mode: TravelMode | None = None
    interests: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("home_city", "dietary", mode="before")
    @classmethod
    def blank_to_none(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("interests", mode="before")
    @classmethod
    def clean_interests(cls, value: object) -> object:
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        return value


class AuthBody(BaseModel):
    """Body of POST /api/auth/register and /api/auth/login."""

    username: str = Field(min_length=3, max_length=40, pattern=r"^[a-z0-9_.-]+$")
    password: str = Field(min_length=6, max_length=200)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value: object) -> object:
        # Usernames are case-insensitive: stored and compared lower-case.
        return value.strip().lower() if isinstance(value, str) else value


class User(BaseModel):
    id: str
    username: str
    profile: UserProfile


class AuthResponse(BaseModel):
    token: str
    user: User


# Preferences a trip can teach the account: when a chat turn sets one of these on the trip,
# the user profile keeps it for future trips (Phase 2 scenario: "change F to something vegan").
LEARNED_FIELDS = ("dietary", "budget_level", "pace", "transport")


def load_user_profile(data: dict[str, Any]) -> UserProfile:
    return UserProfile.model_validate(data or {})


def seed_trip_profile(profile: UserProfile) -> dict[str, Any]:
    """The starting TripProfile for a new trip: the user's saved preferences, nothing else."""
    seed: dict[str, Any] = {
        "origin": profile.home_city,
        "budget_level": profile.budget_level,
        "dietary": profile.dietary,
        "pace": profile.pace,
        "transport": profile.transport,
        "travel_mode": profile.travel_mode,
        "interests": list(profile.interests),
    }
    return {k: v for k, v in seed.items() if v not in (None, [])}
