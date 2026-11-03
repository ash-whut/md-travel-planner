"""Session routes (03-contracts §3). Stage 1: create and fetch; list/rename/delete arrive in Stage 4."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.agent.fixed_messages import GREETING
from app.core.config import Settings, get_settings
from app.db import repositories
from app.db.engine import get_session
from app.schemas import SessionDetail

router = APIRouter()


@router.post("/sessions")
def create_session(
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SessionDetail:
    """Start a new trip: a fresh session whose only message is the fixed greeting."""
    session_row = repositories.create_session(db, llm_provider=settings.llm_provider, greeting=GREETING)
    return repositories.get_session_detail(db, session_row.id, settings.llm_provider)


@router.get("/sessions/{session_id}")
def get_session_detail(
    session_id: str,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SessionDetail:
    detail = repositories.get_session_detail(db, session_id, settings.llm_provider)
    if detail is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return detail
