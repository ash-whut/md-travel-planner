"""Session DTOs (03-contracts §2.3). `from_attributes` lets routes build them from DB rows."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.common import UtcDatetime
from app.schemas.itinerary import Itinerary
from app.schemas.trip_profile import TripProfile

SessionStatus = Literal["intake", "planned"]


class Message(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role: Literal["user", "assistant"]
    content: str  # markdown
    itinerary_version: int | None = None  # set on the assistant message that produced a version
    created_at: UtcDatetime


class MessageCreate(BaseModel):
    """Body of POST /sessions/{id}/messages. Surrounding whitespace is trimmed, so a blank
    message is rejected."""

    content: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class SessionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    status: SessionStatus
    updated_at: UtcDatetime


class SessionDetail(BaseModel):
    id: str
    title: str
    status: SessionStatus
    trip_profile: TripProfile = Field(default_factory=TripProfile)
    messages: list[Message] = Field(default_factory=list)
    itinerary: Itinerary | None = None  # latest version
    chat_enabled: bool = True  # false if the session belongs to a different LLM provider
    created_at: UtcDatetime
    updated_at: UtcDatetime
