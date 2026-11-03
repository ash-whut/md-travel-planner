"""Planning-agent phases as SSE event streams (04-backend-design §4.0, Stage 1: no tools).

Each phase is an async generator of SSE events (03-contracts §4) that the route hands to
`EventSourceResponse`. DB work happens in short `with Session(engine)` blocks, never held
across an LLM await (04 §7.0).
"""

import datetime as dt
import logging
from collections.abc import AsyncIterator
from functools import lru_cache
from itertools import dropwhile
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import Engine
from sqlmodel import Session

from app.agent.fixed_messages import PLAN_READY
from app.agent.postprocess import draft_to_itinerary
from app.core.config import Settings
from app.db import repositories
from app.db.tables import MessageRow, new_id
from app.llm import ChatMessage, LLMError, get_provider
from app.schemas import DoneData, ErrorData, ItineraryDraft, MessageStartData, StatusData, TokenData

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"

# Shown to the user instead of `str(err)`, which is for the server log only.
RETRY_MESSAGE = "Sorry, I couldn't get a reply from the AI model just now. Please try again."
SETUP_MESSAGE = (
    "The AI model isn't set up correctly on the server, so I can't reply. "
    "Check LLM_PROVIDER and the LLM_* settings in backend/.env (see docs/setup-guide.md)."
)

DRAFTING_LABEL = "Drafting your itinerary…"

SseEvent = dict[str, str]  # {"event": name, "data": JSON}, as EventSourceResponse expects


def sse(event: str, data: BaseModel) -> SseEvent:
    return {"event": event, "data": data.model_dump_json()}


def error_event(retryable: bool) -> SseEvent:
    return sse("error", ErrorData(message=RETRY_MESSAGE if retryable else SETUP_MESSAGE, retryable=retryable))


@lru_cache
def load_prompt(name: str) -> str:
    """A prompt file from `agent/prompts/`, read once per process (kept byte-stable)."""
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def chat_history(rows: list[MessageRow]) -> list[ChatMessage]:
    """Display messages as LLM turns, dropping the code-written greeting(s) before the first
    user message so every provider sees a conversation that starts with the user."""
    turns = [ChatMessage(role=row.role, content=row.content) for row in rows]
    return list(dropwhile(lambda turn: turn["role"] == "assistant", turns))


async def run_chat_turn(engine: Engine, settings: Settings, session_id: str, text: str) -> AsyncIterator[SseEvent]:
    """One chat turn: `message_start` → `token`* → `done`, or `error` in place of `done`.

    The user and assistant messages are saved together once the reply is complete, so a
    failed, aborted or empty turn saves nothing and the client can simply re-send the same text.
    """
    user_message = MessageRow(session_id=session_id, role="user", content=text)
    assistant_id = new_id()
    yield sse("message_start", MessageStartData(message_id=assistant_id))

    try:
        llm = get_provider(settings)  # raises LLMError if the provider isn't configured
        with Session(engine) as db:
            history = chat_history(repositories.list_messages(db, session_id))
        history.append(ChatMessage(role="user", content=text))

        chunks: list[str] = []
        async for chunk in llm.stream_text(system=load_prompt("system.md"), messages=history):
            chunks.append(chunk)
            yield sse("token", TokenData(text=chunk))
        reply = "".join(chunks)
        if not reply.strip():  # e.g. TAMU streamed only filler chunks, which openai_compat drops
            raise LLMError("model streamed no reply text", retryable=True)

        assistant_message = MessageRow(id=assistant_id, session_id=session_id, role="assistant", content=reply)
        with Session(engine) as db:
            repositories.add_messages(db, session_id, [user_message, assistant_message])
    except LLMError as err:
        logger.warning("Chat turn failed (session %s, retryable=%s): %s", session_id, err.retryable, err)
        yield error_event(err.retryable)
        return
    except Exception:
        logger.exception("Chat turn crashed (session %s)", session_id)
        yield error_event(retryable=True)
        return

    yield sse("done", DoneData(message_id=assistant_id))


def generation_request(today: dt.date) -> str:
    """The user turn that asks for the draft. It carries today's date (so "next weekend" can be
    resolved) and keeps `generate.md` byte-stable; it also makes the conversation end with the
    user, which every provider accepts."""
    return f"Today is {today:%A}, {today.isoformat()}. Draft the itinerary now from our conversation above."


async def run_generation(engine: Engine, settings: Settings, session_id: str) -> AsyncIterator[SseEvent]:
    """Generate a plan: `message_start` → `status` → `itinerary` → `token` → `done`, or `error`.

    One `generate_json` call drafts an `ItineraryDraft` from the chat history; the provider
    retries once itself if the reply isn't a valid draft (04 §4.0), so there is no second retry
    here. Postprocess turns the draft into an `Itinerary`; the new version, the fixed assistant
    message and `status = planned` are saved together before the `itinerary` event. On any
    failure nothing is saved and the previous version stays current.
    """
    message_id = new_id()
    yield sse("message_start", MessageStartData(message_id=message_id))

    try:
        llm = get_provider(settings)  # raises LLMError if the provider isn't configured
        with Session(engine) as db:
            history = chat_history(repositories.list_messages(db, session_id))
        history.append(ChatMessage(role="user", content=generation_request(dt.date.today())))

        yield sse("status", StatusData(label=DRAFTING_LABEL, tool=None, state="start"))
        draft = await llm.generate_json(system=load_prompt("generate.md"), messages=history, schema=ItineraryDraft)

        with Session(engine) as db:
            latest = repositories.get_latest_itinerary(db, session_id)
            itinerary = draft_to_itinerary(draft, version=latest.version + 1 if latest else 1)
            message = MessageRow(
                id=message_id,
                session_id=session_id,
                role="assistant",
                content=PLAN_READY,
                itinerary_version=itinerary.version,
            )
            repositories.add_itinerary(db, session_id, itinerary, message)
    except LLMError as err:
        logger.warning("Generation failed (session %s, retryable=%s): %s", session_id, err.retryable, err)
        yield error_event(err.retryable)
        return
    except Exception:  # e.g. postprocess ValidationError: a bug, since the draft was validated
        logger.exception("Generation crashed (session %s)", session_id)
        yield error_event(retryable=True)
        return

    yield sse("itinerary", itinerary)
    yield sse("token", TokenData(text=PLAN_READY))
    yield sse("done", DoneData(message_id=message_id))
