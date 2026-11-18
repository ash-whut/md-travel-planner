"""Chat routes (contracts §4, §5): POST /api/sessions/{id}/messages and /generate stream one
turn as SSE."""

from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session
from sse_starlette.sse import EventSourceResponse

from app.agent.sse import SseEvent
from app.agent.turn import TurnLlms, run_turn
from app.core.config import Settings, get_settings
from app.db import repo
from app.db.engine import get_db, get_engine
from app.llm.factory import get_provider
from app.schemas.dto import SendMessageBody

router = APIRouter()


def get_llm(settings: Annotated[Settings, Depends(get_settings)]) -> TurnLlms:
    """FastAPI dependency for the turn's chat and planner providers (D26; tests override it)."""
    return TurnLlms(chat=get_provider(settings, "chat"), planner=get_provider(settings, "planner"))


Db = Annotated[Session, Depends(get_db)]
Llm = Annotated[TurnLlms, Depends(get_llm)]


@router.post("/sessions/{session_id}/messages")
def send_message(
    session_id: str, body: SendMessageBody, db: Db, llm: Llm
) -> EventSourceResponse:
    # Check here, before the stream opens, so an unknown id is a plain 404.
    if repo.get_session(db, session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return EventSourceResponse(_turn_events(session_id, body.content, llm))


@router.post("/sessions/{session_id}/generate")
def generate(session_id: str, db: Db, llm: Llm) -> EventSourceResponse:
    """The Generate button: make (or remake) the plan. The body is `{}` and is ignored."""
    if repo.get_session(db, session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return EventSourceResponse(_turn_events(session_id, None, llm))


async def _turn_events(
    session_id: str, content: str | None, llm: TurnLlms
) -> AsyncIterator[SseEvent]:
    # The stream outlives the request's DB session, so it opens its own.
    # aclosing() makes sure the turn is closed (e.g. on Stop) while this DB session is still open.
    with Session(get_engine()) as db:
        async with aclosing(run_turn(db, session_id, content, llm.chat, llm.planner)) as events:
            async for event in events:
                yield event
