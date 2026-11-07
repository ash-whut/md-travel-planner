"""Plain repository functions. Each one takes an open SQLModel Session and commits its change."""

from typing import Any, Literal

from sqlalchemy import literal_column
from sqlmodel import Session, select

from app.db.tables import MessageRow, SessionRow

Role = Literal["user", "assistant"]


def create_session(db: Session) -> SessionRow:
    session_row = SessionRow()
    db.add(session_row)
    db.commit()
    db.refresh(session_row)
    return session_row


def get_session(db: Session, session_id: str) -> SessionRow | None:
    return db.get(SessionRow, session_id)


def add_message(
    db: Session,
    session_id: str,
    role: Role,
    content: str,
    itinerary_version: int | None = None,
) -> MessageRow:
    session_row = _require_session(db, session_id)
    message = MessageRow(
        session_id=session_id, role=role, content=content, itinerary_version=itinerary_version
    )
    # A new message moves the session to the top of the history list.
    session_row.updated_at = message.created_at
    db.add(message)
    db.add(session_row)
    db.commit()
    db.refresh(message)
    return message


def list_messages(db: Session, session_id: str) -> list[MessageRow]:
    statement = (
        select(MessageRow)
        .where(MessageRow.session_id == session_id)
        # rowid (insertion order) breaks ties when two messages share a timestamp.
        .order_by(MessageRow.created_at, literal_column("message.rowid"))
    )
    return list(db.exec(statement).all())


def update_profile(db: Session, session_id: str, trip_profile: dict[str, Any]) -> SessionRow:
    session_row = _require_session(db, session_id)
    # Assign a new dict (not an in-place edit) so SQLAlchemy sees the JSON column changed.
    session_row.trip_profile = dict(trip_profile)
    db.add(session_row)
    db.commit()
    db.refresh(session_row)
    return session_row


def _require_session(db: Session, session_id: str) -> SessionRow:
    session_row = get_session(db, session_id)
    if session_row is None:
        raise ValueError(f"Unknown session: {session_id}")
    return session_row
