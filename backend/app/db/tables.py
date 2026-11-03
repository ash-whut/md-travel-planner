"""SQLModel tables (03-contracts §1). `api_cache` arrives in Stage 2.

Class names end in `Row` so they don't clash with SQLModel's `Session` or the Pydantic
DTOs in `app.schemas`. JSON columns are not change-tracked: to update one, assign a new
value (`row.data = {...}`) instead of mutating it in place.
"""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, Text, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.core.config import get_settings


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


def _configured_provider() -> str:
    return get_settings().llm_provider


class SessionRow(SQLModel, table=True):
    __tablename__ = "session"

    id: str = Field(default_factory=new_id, primary_key=True)
    title: str = "New trip"
    title_is_custom: bool = False  # true once the user renames -> stop auto-titling
    status: str = "intake"  # intake | planned
    trip_profile: dict = Field(default_factory=dict, sa_type=JSON)  # TripProfile
    llm_provider: str = Field(default_factory=_configured_provider)  # owns agent_transcript
    agent_transcript: list = Field(default_factory=list, sa_type=JSON)  # never sent to the UI
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)  # bump on each message


class MessageRow(SQLModel, table=True):
    __tablename__ = "message"

    id: str = Field(default_factory=new_id, primary_key=True)
    session_id: str = Field(foreign_key="session.id", ondelete="CASCADE", index=True)
    role: str  # user | assistant
    content: str = Field(sa_type=Text)  # markdown
    itinerary_version: int | None = None
    created_at: datetime = Field(default_factory=utc_now)


class ItineraryRow(SQLModel, table=True):
    __tablename__ = "itinerary"
    __table_args__ = (UniqueConstraint("session_id", "version"),)

    id: str = Field(default_factory=new_id, primary_key=True)
    session_id: str = Field(foreign_key="session.id", ondelete="CASCADE", index=True)
    version: int  # 1, 2, 3... per session
    data: dict = Field(sa_type=JSON)  # full Itinerary, as model_dump(mode="json")
    created_at: datetime = Field(default_factory=utc_now)
