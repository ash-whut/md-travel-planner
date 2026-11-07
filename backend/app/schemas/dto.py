"""Session DTOs returned by the REST API (contracts §2.6)."""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel

from app.db.tables import MessageRow, SessionRow
from app.schemas.profile import TripProfile


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
    itinerary: None = None  # the latest Itinerary once plans exist (step 20+)
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


def session_detail(session_row: SessionRow, messages: list[MessageRow]) -> SessionDetail:
    return SessionDetail(
        id=session_row.id,
        title=session_row.title,
        status=session_row.status,  # type: ignore[arg-type]  (stored values are always intake|planned)
        trip_profile=TripProfile.model_validate(session_row.trip_profile),
        messages=[message_out(row) for row in messages],
        itinerary=None,
        created_at=as_utc(session_row.created_at),
        updated_at=as_utc(session_row.updated_at),
    )
