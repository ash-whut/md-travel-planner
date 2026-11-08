"""One chat turn (architecture §4): save the user message, understand it, then either stream a
reply (action=chat), or make / update the plan and stream a short summary (action=generate /
edit). Save the reply.

The turn is an async generator of SSE events (contracts §5). Order:
- chat:          message_start → [profile] → token… → done
- generate/edit: message_start → [profile] → status… → itinerary → token… → done
- failure:       message_start → … → error (if the plan was already saved, a fixed summary + done)
The Generate button runs the same turn with no user message (content=None). An edit with no
plan yet runs as chat.
If the client stops the stream early, the partial reply is saved with STOPPED_MARKER.
Two models per turn (D26): the chat one understands and replies, the planner one composes.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

from sqlmodel import Session

from app.agent import context, pipeline, sse, understand
from app.agent.postprocess import CityWeather
from app.agent.sse import SseEvent
from app.db import repo
from app.db.tables import new_id
from app.llm.base import LLMProvider, Message
from app.schemas.itinerary import Itinerary
from app.schemas.profile import TripProfile, load_profile
from app.schemas.turn import Action

logger = logging.getLogger(__name__)

ERROR_MESSAGE = "Sorry, something went wrong while I was replying. Please try again."
PLAN_ERROR_MESSAGE = (
    "Sorry, I couldn't make the plan this time. Your previous plan is unchanged. Please try again."
)
# Saved (and streamed) when the plan was saved but its summary reply failed (D19).
PLAN_READY_FALLBACK = "Your plan is ready on the left. Ask me to change any stop by its letter."
STOPPED_MARKER = " *(stopped)*"  # appended to a reply the user stopped (contracts §5)

# Added to the chat for the summary reply after a new plan was saved.
SUMMARY_REQUEST = (
    "The app just made the plan shown under \"Current plan\" in the context. In 1–3 short lines, "
    "tell me it is ready on the left, name 2–3 highlights by their [tags], and say I can ask for "
    "changes by letter. Don't list the whole plan."
)
# Added to the chat for the summary reply after an edit; {change_request} is what was asked.
EDIT_SUMMARY_REQUEST = (
    "The app just updated the plan as I asked ({change_request}). The new version is under "
    "\"Current plan\" in the context. In 1–3 short lines, say what changed, naming the stops by "
    "their [tags]. Don't list the whole plan."
)


@dataclass
class TurnLlms:
    """The two providers of a turn (D26): `chat` for understand and replies, `planner` for
    compose."""

    chat: LLMProvider
    planner: LLMProvider


async def run_turn(
    db: Session,
    session_id: str,
    content: str | None,
    chat_llm: LLMProvider,
    planner_llm: LLMProvider | None = None,
) -> AsyncIterator[SseEvent]:
    """Run one turn for an existing session (the route checks it exists).

    `content` is the user's message. None means the Generate button: no user message is saved,
    the understand step is skipped, and the turn makes the plan.
    `chat_llm` runs understand and the reply; `planner_llm` runs compose (None = `chat_llm`).
    """
    planner_llm = planner_llm or chat_llm
    message_id = new_id()  # the assistant message id, announced before the message is saved
    parts: list[str] = []  # streamed reply so far, saved with STOPPED_MARKER on Stop
    plan_version: int | None = None  # set once a new plan version is saved in this turn
    started = False  # message_start sent
    # The Generate button always makes the plan; a chat message's action is known after understand.
    action: Action | None = "generate" if content is None else None
    change_request = content  # what an edit should change; understand may phrase it better

    def remember_version(saved: Itinerary) -> None:
        nonlocal plan_version
        plan_version = saved.version

    try:
        # Saved first, so the user message is kept even if the reply fails.
        if content is not None:
            repo.add_message(db, session_id, "user", content)
        yield sse.message_start(message_id)
        started = True

        history = chat_history(db, session_id)
        profile = session_profile(db, session_id)
        if content is not None:
            analysis = await understand.analyze(chat_llm, profile, history)
            new_profile = understand.merge_profile(profile, analysis.profile_updates)
            if understand.profile_changed(profile, new_profile):
                # mode="json": the JSON column can't hold date objects.
                profile_json = new_profile.model_dump(mode="json")
                repo.update_profile(db, session_id, profile_json)
                yield sse.profile(profile_json)
            profile = new_profile
            action = analysis.action
            change_request = analysis.change_request or content

        if action == "edit" and repo.get_latest_itinerary(db, session_id) is None:
            action = "chat"  # nothing to edit yet; the reply sees "No plan yet" in its context

        reply_messages = history
        if action == "generate":
            async for event in pipeline.run_generation(
                db, session_id, planner_llm, profile, history, on_saved=remember_version
            ):
                yield event
            reply_messages = pipeline.with_request(history, SUMMARY_REQUEST)
        elif action == "edit":
            async for event in pipeline.run_generation(
                db, session_id, planner_llm, profile, history, on_saved=remember_version,
                change_request=change_request,
            ):
                yield event
            summary_request = EDIT_SUMMARY_REQUEST.format(change_request=change_request)
            reply_messages = pipeline.with_request(history, summary_request)

        plan = repo.get_latest_itinerary(db, session_id)
        weather: list[CityWeather] = []
        if action == "chat" and plan is None:
            # No plan (with its weather) yet: fetch the forecast for the profile's city and
            # dates, if known. Silently: chat turns emit no status lines.
            weather = [
                item async for item in pipeline.gather_weather(profile)
                if isinstance(item, CityWeather)
            ]
        system = context.build_system(profile, plan=plan, weather=weather)
        async for chunk in chat_llm.stream_text(system, reply_messages):
            parts.append(chunk)
            yield sse.token(chunk)

        repo.add_message(
            db, session_id, "assistant", "".join(parts),
            itinerary_version=plan_version, message_id=message_id,
        )
    except (GeneratorExit, asyncio.CancelledError):
        # Stop / client disconnect: the turn is closed (GeneratorExit) or its task cancelled.
        # Nothing can be sent any more, so save what was streamed and let the stop go on.
        stopped_text = "".join(parts).rstrip() + STOPPED_MARKER
        repo.add_message(
            db, session_id, "assistant", stopped_text,
            itinerary_version=plan_version, message_id=message_id,
        )
        raise
    except Exception:
        logger.exception("Turn failed for session %s", session_id)
        if not started:  # e.g. saving the user message failed; `error` always follows message_start
            yield sse.message_start(message_id)
        if plan_version is not None:
            # The plan is saved and was sent; only its summary failed. Every plan version gets a
            # chat message (D19), so finish the reply with a fixed line instead of an error.
            fallback = ("\n\n" if parts else "") + PLAN_READY_FALLBACK
            yield sse.token(fallback)
            repo.add_message(
                db, session_id, "assistant", "".join(parts) + fallback,
                itinerary_version=plan_version, message_id=message_id,
            )
            yield sse.done(message_id)
            return
        yield sse.error(PLAN_ERROR_MESSAGE if action in ("generate", "edit") else ERROR_MESSAGE)
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
