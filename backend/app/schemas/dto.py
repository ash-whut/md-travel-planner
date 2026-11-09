"""Session DTOs returned by the REST API (contracts §2.6)."""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.db.tables import MessageRow, SessionRow
from app.schemas.itinerary import BookingStatus, Itinerary
from app.schemas.profile import TripProfile, load_profile


class SendMessageBody(BaseModel):
    """Body of POST /api/sessions/{id}/messages."""

    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content", mode="before")
    @classmethod
    def strip_content(cls, value: object) -> object:
        # Strip first, so whitespace-only content fails min_length (422).
        return value.strip() if isinstance(value, str) else value


class UpdateBookingBody(BaseModel):
    """Body of PATCH /api/sessions/{id}/bookings/{booking_id}."""

    status: BookingStatus


class MessageOut(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    itinerary_version: int | None
    created_at: datetime


class SessionDetail(BaseModel):
    id: str
    title: str
    status: Literal["intake", "planned"]
    trip_profile: TripProfile
    messages: list[MessageOut]
    itinerary: Itinerary | None = None  # the latest version, null until a plan exists
    created_at: datetime
    updated_at: datetime


def as_utc(value: datetime) -> datetime:
    # SQLite drops the timezone on read, so stored values come back naive (they are UTC).
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def message_out(row: MessageRow) -> MessageOut:
    return MessageOut(
        id=row.id,
        role=row.role,  # type: ignore[arg-type]  (stored values are always user|assistant)
        content=row.content,
        itinerary_version=row.itinerary_version,
        created_at=as_utc(row.created_at),
    )


def session_detail(
    session_row: SessionRow, messages: list[MessageRow], itinerary: Itinerary | None = None
) -> SessionDetail:
    return SessionDetail(
        id=session_row.id,
        title=session_row.title,
        status=session_row.status,  # type: ignore[arg-type]  (stored values are always intake|planned)
        trip_profile=load_profile(session_row.trip_profile),
        messages=[message_out(row) for row in messages],
        itinerary=itinerary,
        created_at=as_utc(session_row.created_at),
        updated_at=as_utc(session_row.updated_at),
    )
