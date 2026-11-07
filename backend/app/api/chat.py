"""Chat route: POST /api/sessions/{id}/messages streams one turn as SSE (contracts §4, §5)."""

from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session
from sse_starlette.sse import EventSourceResponse

from app.agent.sse import SseEvent
from app.agent.turn import run_turn
from app.core.config import Settings, get_settings
from app.db import repo
from app.db.engine import get_db, get_engine
from app.llm.base import LLMProvider
from app.llm.factory import get_provider
from app.schemas.dto import SendMessageBody

router = APIRouter()


def get_llm(settings: Annotated[Settings, Depends(get_settings)]) -> LLMProvider:
    """FastAPI dependency for the LLM provider (tests override it)."""
    return get_provider(settings)


Db = Annotated[Session, Depends(get_db)]
Llm = Annotated[LLMProvider, Depends(get_llm)]


@router.post("/sessions/{session_id}/messages")
def send_message(
    session_id: str, body: SendMessageBody, db: Db, llm: Llm
) -> EventSourceResponse:
    # Check here, before the stream opens, so an unknown id is a plain 404.
    if repo.get_session(db, session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return EventSourceResponse(_turn_events(session_id, body.content, llm))


async def _turn_events(session_id: str, content: str, llm: LLMProvider) -> AsyncIterator[SseEvent]:
    # The stream outlives the request's DB session, so it opens its own.
    # aclosing() makes sure the turn is closed (e.g. on Stop) while this DB session is still open.
    with Session(get_engine()) as db:
        async with aclosing(run_turn(db, session_id, content, llm)) as events:
            async for event in events:
                yield event
