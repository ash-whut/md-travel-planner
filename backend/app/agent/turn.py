"""One chat turn (architecture §4): save the user message, understand it, stream the reply, save it.

The turn is an async generator of SSE events (contracts §5). Order:
message_start → [profile] → token… → done, or message_start → … → error.
If the client stops the stream early, the partial reply is saved with STOPPED_MARKER.
"""

import asyncio
import logging
from collections.abc import AsyncIterator

from sqlmodel import Session

from app.agent import context, sse, understand
from app.agent.sse import SseEvent
from app.db import repo
from app.db.tables import new_id
from app.llm.base import LLMProvider, Message
from app.schemas.profile import TripProfile, load_profile

logger = logging.getLogger(__name__)

ERROR_MESSAGE = "Sorry, something went wrong while I was replying. Please try again."
STOPPED_MARKER = " *(stopped)*"  # appended to a reply the user stopped (contracts §5)


async def run_turn(
    db: Session, session_id: str, content: str, llm: LLMProvider
) -> AsyncIterator[SseEvent]:
    """Run one chat turn for an existing session (the route checks it exists)."""
    message_id = new_id()  # the assistant message id, announced before the message is saved
    parts: list[str] = []  # streamed reply so far, saved with STOPPED_MARKER on Stop
    started = False  # message_start sent
    try:
        # Saved first, so the user message is kept even if the reply fails.
        repo.add_message(db, session_id, "user", content)
        yield sse.message_start(message_id)
        started = True

        history = chat_history(db, session_id)
        old_profile = session_profile(db, session_id)
        analysis = await understand.analyze(llm, old_profile, history)
        profile = understand.merge_profile(old_profile, analysis.profile_updates)
        if understand.profile_changed(old_profile, profile):
            # mode="json": the JSON column can't hold date objects.
            profile_json = profile.model_dump(mode="json")
            repo.update_profile(db, session_id, profile_json)
            yield sse.profile(profile_json)

        # Only action=chat is handled so far; generate and edit arrive in later steps.
        system = context.build_system(profile)
        async for chunk in llm.stream_text(system, history):
            parts.append(chunk)
            yield sse.token(chunk)

        repo.add_message(db, session_id, "assistant", "".join(parts), message_id=message_id)
    except (GeneratorExit, asyncio.CancelledError):
        # Stop / client disconnect: the turn is closed (GeneratorExit) or its task cancelled.
        # Nothing can be sent any more, so save what was streamed and let the stop go on.
        stopped_text = "".join(parts).rstrip() + STOPPED_MARKER
        repo.add_message(db, session_id, "assistant", stopped_text, message_id=message_id)
        raise
    except Exception:
        logger.exception("Chat turn failed for session %s", session_id)
        if not started:  # e.g. saving the user message failed; `error` always follows message_start
            yield sse.message_start(message_id)
        yield sse.error(ERROR_MESSAGE)
        return
    yield sse.done(message_id)


def session_profile(db: Session, session_id: str) -> TripProfile:
    """The saved trip profile of the session, with `missing_required` filled for the prompts."""
    session_row = repo.get_session(db, session_id)
    return load_profile(session_row.trip_profile if session_row else {})


def chat_history(db: Session, session_id: str) -> list[Message]:
    """All saved messages of the session, oldest first, in the LLM message format."""
    return [
        {"role": row.role, "content": row.content}
        for row in repo.list_messages(db, session_id)
    ]
