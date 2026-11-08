"""Generation pipeline (architecture §4.1): gather → compose → postprocess → save.

For now there is no gather step; tool results arrive with the tool steps.
"""

from collections.abc import AsyncIterator, Callable
from datetime import date

from pydantic import ValidationError
from sqlmodel import Session

from app.agent import context, sse
from app.agent.postprocess import build_itinerary
from app.agent.sse import SseEvent
from app.db import repo
from app.llm.base import LLMProvider, Message
from app.schemas.itinerary import Itinerary, ItineraryDraft
from app.schemas.profile import TripProfile

COMPOSE_REQUEST = "Make the full trip plan now."
DRAFTING_LABEL = "Drafting your plan…"


async def run_generation(
    db: Session,
    session_id: str,
    llm: LLMProvider,
    profile: TripProfile,
    messages: list[Message],
    on_saved: Callable[[Itinerary], None],
    today: date | None = None,
) -> AsyncIterator[SseEvent]:
    """Make the session's next plan version and save it. Events: status start → status end →
    itinerary.

    `on_saved` is called right after the save, so the caller knows the new version even if a
    later step fails or the stream is stopped. If compose or the save fails, it emits status
    "error" and re-raises; nothing is saved, so the previous plan stays. The caller turns the
    exception into an `error` event.
    """
    yield sse.status(DRAFTING_LABEL, "start")
    try:
        plan = await compose(llm, profile, messages, repo.list_itineraries(db, session_id), today)
        saved = repo.save_itinerary(db, session_id, plan)  # also sets the status to "planned"
    except Exception:
        yield sse.status(DRAFTING_LABEL, "error")
        raise
    on_saved(saved)
    yield sse.status(DRAFTING_LABEL, "end")
    yield sse.itinerary(saved.model_dump(mode="json"))


class ComposeError(Exception):
    """Compose failed twice (the first try and the one repair try). `errors` says why."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("The plan could not be made: " + "; ".join(errors))
        self.errors = errors


async def compose(
    llm: LLMProvider,
    profile: TripProfile,
    messages: list[Message],
    previous_versions: list[Itinerary] | None = None,
    today: date | None = None,
) -> Itinerary:
    """Ask the LLM for an ItineraryDraft and postprocess it into a valid Itinerary.

    If the draft breaks a rule, compose once more with the errors included. Raises
    ComposeError when the repair try fails too.
    """
    previous_versions = previous_versions or []
    system = build_system(profile, today)

    result = await _compose_once(llm, system, messages, COMPOSE_REQUEST, previous_versions, profile)
    if isinstance(result, Itinerary):
        return result

    result = await _compose_once(
        llm, system, messages, repair_request(result), previous_versions, profile
    )
    if isinstance(result, Itinerary):
        return result
    raise ComposeError(result)


async def _compose_once(
    llm: LLMProvider,
    system: str,
    messages: list[Message],
    request: str,
    previous_versions: list[Itinerary],
    profile: TripProfile,
) -> Itinerary | list[str]:
    """One compose call + postprocess: the Itinerary, or the errors that broke it."""
    try:
        draft = await llm.complete_json(system, with_request(messages, request), ItineraryDraft)
    except ValidationError as error:
        # The reply didn't fit the draft schema (e.g. an unknown stop_key); worth one repair.
        return [
            f"{'.'.join(str(part) for part in detail['loc'])}: {detail['msg']}"
            for detail in error.errors()
        ]
    return build_itinerary(draft, previous_versions, profile)


def with_request(messages: list[Message], request: str) -> list[Message]:
    """The chat plus the compose request as the last user message.

    If the chat already ends with a user message, the request is added to it, so roles keep
    alternating (some backends reject two user messages in a row).
    """
    if messages and messages[-1]["role"] == "user":
        last = messages[-1]
        return [*messages[:-1], {"role": "user", "content": f"{last['content']}\n\n{request}"}]
    return [*messages, {"role": "user", "content": request}]


def repair_request(errors: list[str]) -> str:
    """The user message for the repair try: the request again plus what was wrong."""
    error_lines = "\n".join(f"- {error}" for error in errors)
    return (
        f"{COMPOSE_REQUEST}\n\n"
        f"Your last plan broke these rules. Fix them and reply with the whole corrected plan:\n"
        f"{error_lines}"
    )


def build_system(profile: TripProfile, today: date | None = None) -> str:
    """System text for the compose call: its prompt plus today's date and the profile."""
    today = today or date.today()
    return "\n\n".join(
        [
            context.load_prompt("compose").strip(),
            "# Context",
            f"Today is {context.format_date(today)} ({today.isoformat()}).",
            "## Trip profile\n" + context.render_profile(profile),
        ]
    )
