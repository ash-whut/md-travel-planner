"""Plain repository functions: the only place routes and the orchestrator touch the tables.

Each function takes an open `Session` (from the `get_session` dependency or a short
`with Session(get_engine())` block) and commits its own writes.
"""

from sqlalchemy import text
from sqlmodel import Session, select

from app.db.tables import ItineraryRow, MessageRow, SessionRow
from app.schemas import Itinerary, Message, SessionDetail, TripProfile


def create_session(db: Session, llm_provider: str, greeting: str) -> SessionRow:
    """Insert a new session (03 §1 defaults) and its first assistant message, the greeting."""
    session_row = SessionRow(llm_provider=llm_provider)
    db.add(session_row)
    db.flush()  # no relationship() between the tables, so insert the parent row first
    db.add(MessageRow(session_id=session_row.id, role="assistant", content=greeting))
    db.commit()
    db.refresh(session_row)
    return session_row


def get_session_row(db: Session, session_id: str) -> SessionRow | None:
    return db.get(SessionRow, session_id)


def list_messages(db: Session, session_id: str) -> list[MessageRow]:
    """A session's display messages, oldest first.

    Ties on `created_at` (possible with a coarse clock) fall back to SQLite's `rowid`, i.e.
    insertion order. On another database, replace it with an explicit sequence column.
    """
    statement = (
        select(MessageRow)
        .where(MessageRow.session_id == session_id)
        .order_by(MessageRow.created_at, text("message.rowid"))
    )
    return list(db.exec(statement).all())


def get_latest_itinerary(db: Session, session_id: str) -> ItineraryRow | None:
    statement = (
        select(ItineraryRow)
        .where(ItineraryRow.session_id == session_id)
        .order_by(ItineraryRow.version.desc())
        .limit(1)
    )
    return db.exec(statement).first()


def get_session_detail(db: Session, session_id: str, current_provider: str) -> SessionDetail | None:
    """`SessionDetail` (03 §2.3) for one session, or None if it doesn't exist.

    `current_provider` is the configured LLM_PROVIDER; chat is disabled when the session's
    transcript belongs to a different provider (03 §1).
    """
    session_row = get_session_row(db, session_id)
    if session_row is None:
        return None
    itinerary_row = get_latest_itinerary(db, session_id)
    return SessionDetail(
        id=session_row.id,
        title=session_row.title,
        status=session_row.status,
        trip_profile=TripProfile.model_validate(session_row.trip_profile),
        messages=[Message.model_validate(m) for m in list_messages(db, session_id)],
        itinerary=Itinerary.model_validate(itinerary_row.data) if itinerary_row else None,
        chat_enabled=session_row.llm_provider == current_provider,
        created_at=session_row.created_at,
        updated_at=session_row.updated_at,
    )
