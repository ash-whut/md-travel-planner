"""Chat route (03-contracts §3, §4): POST /api/sessions/{id}/messages streams the reply as SSE."""

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


@router.post("/sessions/{session_id}/messages")
def send_message(
    session_id: str,
    body: MessageCreate,
    engine: Engine = Depends(get_engine),
    settings: Settings = Depends(get_settings),
) -> EventSourceResponse:
    # A short session just for the 404 check; the stream opens its own (04 §7.0).
    with Session(engine) as db:
        if repositories.get_session_row(db, session_id) is None:
            raise HTTPException(status_code=404, detail="Session not found")
    return EventSourceResponse(orchestrator.run_chat_turn(engine, settings, session_id, body.content))
