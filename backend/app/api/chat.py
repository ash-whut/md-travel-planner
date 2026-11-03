"""Streaming routes (03-contracts §3, §4): chat messages and plan generation, both as SSE."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Engine
from sqlmodel import Session
from sse_starlette import EventSourceResponse

from app.agent import orchestrator
from app.core.config import Settings, get_settings
from app.db import repositories
from app.db.engine import get_engine
from app.schemas import MessageCreate

router = APIRouter()


def require_session(engine: Engine, session_id: str) -> None:
    """404 if the session doesn't exist. A short DB session; the stream opens its own (04 §7.0)."""
    with Session(engine) as db:
        if repositories.get_session_row(db, session_id) is None:
            raise HTTPException(status_code=404, detail="Session not found")


@router.post("/sessions/{session_id}/messages")
def send_message(
    session_id: str,
    body: MessageCreate,
    engine: Engine = Depends(get_engine),
    settings: Settings = Depends(get_settings),
) -> EventSourceResponse:
    require_session(engine, session_id)
    return EventSourceResponse(orchestrator.run_chat_turn(engine, settings, session_id, body.content))


@router.post("/sessions/{session_id}/generate")
def generate(
    session_id: str,
    engine: Engine = Depends(get_engine),
    settings: Settings = Depends(get_settings),
) -> EventSourceResponse:
    """The body is `{}` (03 §3) and is not read."""
    require_session(engine, session_id)
    return EventSourceResponse(orchestrator.run_generation(engine, settings, session_id))
