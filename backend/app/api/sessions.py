"""Session routes: POST /api/sessions and GET /api/sessions/{id} (contracts §4)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.db import repo
from app.db.engine import get_db
from app.schemas.dto import SessionDetail, session_detail

GREETING = "Hi, where do you want to go?"

router = APIRouter()

Db = Annotated[Session, Depends(get_db)]


@router.post("/sessions")
def create_session(db: Db) -> SessionDetail:
    session_row = repo.create_session(db)
    repo.add_message(db, session_row.id, "assistant", GREETING)
    db.refresh(session_row)
    return session_detail(session_row, repo.list_messages(db, session_row.id))


@router.get("/sessions/{session_id}")
def get_session(session_id: str, db: Db) -> SessionDetail:
    session_row = repo.get_session(db, session_id)
    if session_row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session_detail(session_row, repo.list_messages(db, session_id))
