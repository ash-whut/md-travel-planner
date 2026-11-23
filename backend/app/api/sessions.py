"""Session routes (contracts §4): create, list, get, rename and delete sessions."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session

from app.core.auth import OptionalUser
from app.db import repo
from app.db.engine import get_db
from app.db.tables import SessionRow, UserRow
from app.schemas.dto import (
    RenameSessionBody,
    SessionDetail,
    SessionSummary,
    session_detail,
    session_summary,
)
from app.schemas.user import load_user_profile, seed_trip_profile

GREETING = "Hi, where do you want to go?"

router = APIRouter()

Db = Annotated[Session, Depends(get_db)]


def _require_session(db: Session, session_id: str, user: UserRow | None) -> SessionRow:
    # Another account's trip is a 404 too, so ids of other users' trips aren't confirmed.
    session_row = repo.get_session(db, session_id)
    if session_row is None or (user is not None and session_row.user_id != user.id):
        raise HTTPException(status_code=404, detail="Session not found")
    return session_row


@router.post("/sessions")
def create_session(db: Db, user: OptionalUser) -> SessionDetail:
    if user is None:
        session_row = repo.create_session(db)
    else:
        # A logged-in user's trip starts from their saved preferences (decisions D32).
        seed = seed_trip_profile(load_user_profile(user.profile))
        session_row = repo.create_session(db, user_id=user.id, trip_profile=seed)
    repo.add_message(db, session_row.id, "assistant", GREETING)
    db.refresh(session_row)
    return session_detail(session_row, repo.list_messages(db, session_row.id))


@router.get("/sessions")
def list_sessions(db: Db, user: OptionalUser) -> list[SessionSummary]:
    user_id = None if user is None else user.id
    return [session_summary(row) for row in repo.list_sessions(db, user_id)]


@router.get("/sessions/{session_id}")
def get_session(session_id: str, db: Db, user: OptionalUser) -> SessionDetail:
    session_row = _require_session(db, session_id, user)
    return session_detail(
        session_row, repo.list_messages(db, session_id), repo.get_latest_itinerary(db, session_id)
    )


@router.patch("/sessions/{session_id}")
def rename_session(
    session_id: str, body: RenameSessionBody, db: Db, user: OptionalUser
) -> SessionSummary:
    _require_session(db, session_id, user)
    return session_summary(repo.rename_session(db, session_id, body.title))


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str, db: Db, user: OptionalUser) -> Response:
    _require_session(db, session_id, user)
    repo.delete_session(db, session_id)
    return Response(status_code=204)
