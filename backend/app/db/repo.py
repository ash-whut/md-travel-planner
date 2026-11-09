"""Plain repository functions. Each one takes an open SQLModel Session and commits its change."""

from typing import Any, Literal

from sqlalchemy import literal_column
from sqlmodel import Session, select

from app.db.tables import ItineraryRow, MessageRow, SessionRow
from app.schemas.itinerary import Booking, BookingStatus, Itinerary

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
    message_id: str | None = None,
) -> MessageRow:
    session_row = _require_session(db, session_id)
    message = MessageRow(
        session_id=session_id, role=role, content=content, itinerary_version=itinerary_version
    )
    # A chat turn announces the assistant message id (SSE message_start) before saving it.
    if message_id is not None:
        message.id = message_id
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


def save_itinerary(db: Session, session_id: str, itinerary: Itinerary) -> Itinerary:
    """Save as the session's next version (1, 2, 3…) and return it with that version set.

    Also sets the session to "planned" in the same commit, so a saved plan never sits next to
    an "intake" status.
    """
    session_row = _require_session(db, session_id)
    latest = _latest_itinerary_row(db, session_id)
    version = 1 if latest is None else latest.version + 1
    saved = itinerary.model_copy(update={"version": version})
    row = ItineraryRow(
        session_id=session_id, version=version, data=saved.model_dump(mode="json")
    )
    session_row.status = "planned"
    db.add(row)
    db.add(session_row)
    db.commit()
    return saved


def get_latest_itinerary(db: Session, session_id: str) -> Itinerary | None:
    row = _latest_itinerary_row(db, session_id)
    return None if row is None else Itinerary.model_validate(row.data)


def list_itineraries(db: Session, session_id: str) -> list[Itinerary]:
    """All versions of a session's plan, oldest first."""
    statement = (
        select(ItineraryRow)
        .where(ItineraryRow.session_id == session_id)
        .order_by(ItineraryRow.version)  # type: ignore[arg-type]
    )
    return [Itinerary.model_validate(row.data) for row in db.exec(statement).all()]


def update_booking_status(
    db: Session, session_id: str, booking_id: str, status: BookingStatus
) -> Booking | None:
    """Set one booking's status in the session's latest itinerary, in place (no new version).

    Returns the updated booking, or None when there is no plan or no booking with that id.
    """
    row = _latest_itinerary_row(db, session_id)
    if row is None:
        return None
    itinerary = Itinerary.model_validate(row.data)
    booking = next((entry for entry in itinerary.bookings if entry.id == booking_id), None)
    if booking is None:
        return None
    booking.status = status
    # Assign new data (not an in-place edit) so SQLAlchemy sees the JSON column changed.
    row.data = itinerary.model_dump(mode="json")
    db.add(row)
    db.commit()
    return booking


def _latest_itinerary_row(db: Session, session_id: str) -> ItineraryRow | None:
    statement = (
        select(ItineraryRow)
        .where(ItineraryRow.session_id == session_id)
        .order_by(ItineraryRow.version.desc())  # type: ignore[attr-defined]
        .limit(1)
    )
    return db.exec(statement).first()


def _require_session(db: Session, session_id: str) -> SessionRow:
    session_row = get_session(db, session_id)
    if session_row is None:
        raise ValueError(f"Unknown session: {session_id}")
    return session_row
