"""Plain repository functions. Each one takes an open SQLModel Session and commits its change."""

from typing import Any, Literal

from sqlalchemy import literal_column
from sqlmodel import Session, select

from app.db.tables import AuthTokenRow, ItineraryRow, MessageRow, SessionRow, UserRow
from app.schemas.itinerary import Booking, BookingStatus, Itinerary
from app.schemas.user import LEARNED_FIELDS

Role = Literal["user", "assistant"]


def create_session(
    db: Session, user_id: str | None = None, trip_profile: dict[str, Any] | None = None
) -> SessionRow:
    session_row = SessionRow(user_id=user_id, trip_profile=dict(trip_profile or {}))
    db.add(session_row)
    db.commit()
    db.refresh(session_row)
    return session_row


def get_session(db: Session, session_id: str) -> SessionRow | None:
    return db.get(SessionRow, session_id)


def list_sessions(db: Session, user_id: str | None = None) -> list[SessionRow]:
    """Sessions for the history list, most recently updated first: the user's own trips, or
    the trips made without an account when user_id is None."""
    statement = select(SessionRow).where(SessionRow.user_id == user_id).order_by(
        SessionRow.updated_at.desc(),  # type: ignore[attr-defined]
        literal_column("session.rowid").desc(),  # newest-created first on a timestamp tie
    )
    return list(db.exec(statement).all())


def rename_session(db: Session, session_id: str, title: str) -> SessionRow:
    """The user's own title. It stops auto-titling for good. updated_at is left alone, so a
    rename doesn't move the trip to the top of the list."""
    session_row = _require_session(db, session_id)
    session_row.title = title
    session_row.title_is_custom = True
    db.add(session_row)
    db.commit()
    db.refresh(session_row)
    return session_row


def set_auto_title(db: Session, session_id: str, title: str) -> SessionRow:
    """A title built by code from the profile; title_is_custom stays False."""
    session_row = _require_session(db, session_id)
    session_row.title = title
    db.add(session_row)
    db.commit()
    db.refresh(session_row)
    return session_row


def delete_session(db: Session, session_id: str) -> None:
    """Delete the session. ON DELETE CASCADE (foreign keys are on, db/engine.py) removes its
    messages and itineraries."""
    db.delete(_require_session(db, session_id))
    db.commit()


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
    """Save the trip profile. For a logged-in user's trip, a preference the chat just set
    (LEARNED_FIELDS) is also kept in the user profile for future trips."""
    session_row = _require_session(db, session_id)
    if session_row.user_id is not None:
        _learn_preferences(db, session_row.user_id, session_row.trip_profile, trip_profile)
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


# --- Accounts (decisions D32) ---


def create_user(db: Session, username: str, password_hash: str) -> UserRow:
    user = UserRow(username=username, password_hash=password_hash)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user_by_username(db: Session, username: str) -> UserRow | None:
    return db.exec(select(UserRow).where(UserRow.username == username)).first()


def create_token(db: Session, user_id: str, token: str) -> str:
    db.add(AuthTokenRow(token=token, user_id=user_id))
    db.commit()
    return token


def get_user_by_token(db: Session, token: str) -> UserRow | None:
    row = db.get(AuthTokenRow, token)
    return None if row is None else db.get(UserRow, row.user_id)


def delete_token(db: Session, token: str) -> None:
    row = db.get(AuthTokenRow, token)
    if row is not None:
        db.delete(row)
        db.commit()


def set_user_profile(db: Session, user_id: str, profile: dict[str, Any]) -> UserRow:
    user = db.get(UserRow, user_id)
    if user is None:
        raise ValueError(f"Unknown user: {user_id}")
    user.profile = dict(profile)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _learn_preferences(
    db: Session, user_id: str, old: dict[str, Any], new: dict[str, Any]
) -> None:
    user = db.get(UserRow, user_id)
    if user is None:
        return
    learned = {
        key: new[key]
        for key in LEARNED_FIELDS
        if new.get(key) is not None and new.get(key) != old.get(key)
    }
    if learned:
        # Committed together with the trip profile by update_profile.
        user.profile = {**user.profile, **learned}
        db.add(user)
