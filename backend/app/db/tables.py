"""Database tables (contracts §1)."""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Column, ForeignKey, String, UniqueConstraint
from sqlmodel import Field, SQLModel


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    # Timezone-aware UTC: SQLModel rejects naive datetimes in datetime columns.
    return datetime.now(timezone.utc)


class SessionRow(SQLModel, table=True):
    __tablename__ = "session"

    id: str = Field(default_factory=new_id, primary_key=True)
    title: str = "New trip"
    title_is_custom: bool = False
    status: str = "intake"  # intake | planned
    trip_profile: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class MessageRow(SQLModel, table=True):
    __tablename__ = "message"

    id: str = Field(default_factory=new_id, primary_key=True)
    session_id: str = Field(
        sa_column=Column(
            String, ForeignKey("session.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    role: str  # user | assistant
    content: str
    itinerary_version: int | None = None
    created_at: datetime = Field(default_factory=utcnow)


class ItineraryRow(SQLModel, table=True):
    """One saved plan version. `data` holds the full Itinerary (contracts §2.2) as JSON."""

    __tablename__ = "itinerary"
    __table_args__ = (UniqueConstraint("session_id", "version"),)

    id: str = Field(default_factory=new_id, primary_key=True)
    session_id: str = Field(
        sa_column=Column(
            String, ForeignKey("session.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    version: int  # 1, 2, 3… per session
    data: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=utcnow)


class ApiCacheRow(SQLModel, table=True):
    """A cached tool result. Read and written only through `tools/common.py`."""

    __tablename__ = "api_cache"

    key: str = Field(primary_key=True)  # "{tool}:{sha256 of the args JSON}"
    value: Any = Field(sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=utcnow)
    ttl_seconds: int
