"""Session routes (contracts §4): create, list, get, rename and delete sessions."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session

from app.db import repo
from app.db.engine import get_db
from app.db.tables import SessionRow
from app.schemas.dto import (
    RenameSessionBody,
    SessionDetail,
    SessionSummary,
    session_detail,
    session_summary,
)

GREETING = "Hi, where do you want to go?"

router = APIRouter()

Db = Annotated[Session, Depends(get_db)]


def _require_session(db: Session, session_id: str) -> SessionRow:
    session_row = repo.get_session(db, session_id)
    if session_row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session_row


@router.post("/sessions")
def create_session(db: Db) -> SessionDetail:
    session_row = repo.create_session(db)
    repo.add_message(db, session_row.id, "assistant", GREETING)
    db.refresh(session_row)
    return session_detail(session_row, repo.list_messages(db, session_row.id))


@router.get("/sessions")
def list_sessions(db: Db) -> list[SessionSummary]:
    return [session_summary(row) for row in repo.list_sessions(db)]


@router.get("/sessions/{session_id}")
def get_session(session_id: str, db: Db) -> SessionDetail:
    session_row = _require_session(db, session_id)
    return session_detail(
        session_row, repo.list_messages(db, session_id), repo.get_latest_itinerary(db, session_id)
    )


@router.patch("/sessions/{session_id}")
def rename_session(session_id: str, body: RenameSessionBody, db: Db) -> SessionSummary:
    _require_session(db, session_id)
    return session_summary(repo.rename_session(db, session_id, body.title))


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str, db: Db) -> Response:
    _require_session(db, session_id)
    repo.delete_session(db, session_id)
    return Response(status_code=204)
