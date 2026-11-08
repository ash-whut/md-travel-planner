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
from app.schemas.itinerary import (
    DraftCity,
    DraftDay,
    DraftItem,
    DraftLodging,
    DraftStop,
    Itinerary,
    ItineraryDraft,
)
from app.schemas.profile import TripProfile

COMPOSE_REQUEST = "Make the full trip plan now."
# For an edit; the fake provider spots edits by "change only what was asked".
EDIT_REQUEST = (
    "Update the current plan: {change_request}\n"
    "Change only what was asked. Copy every other day, item and stop exactly as it is in the "
    "current plan (same names, keys, times and descriptions), and reply with the whole updated "
    "plan."
)
DRAFTING_LABEL = "Drafting your plan…"
UPDATING_LABEL = "Updating your plan…"


async def run_generation(
    db: Session,
    session_id: str,
    llm: LLMProvider,
    profile: TripProfile,
    messages: list[Message],
    on_saved: Callable[[Itinerary], None],
    today: date | None = None,
    change_request: str | None = None,
) -> AsyncIterator[SseEvent]:
    """Make the session's next plan version and save it. Events: status start → status end →
    itinerary.

    `change_request` (an edit) makes compose update the latest plan instead of making a new one.
    `on_saved` is called right after the save, so the caller knows the new version even if a
    later step fails or the stream is stopped. If compose or the save fails, it emits status
    "error" and re-raises; nothing is saved, so the previous plan stays. The caller turns the
    exception into an `error` event.
    """
    label = UPDATING_LABEL if change_request else DRAFTING_LABEL
    yield sse.status(label, "start")
    try:
        previous_versions = repo.list_itineraries(db, session_id)
        plan = await compose(llm, profile, messages, previous_versions, today, change_request)
        saved = repo.save_itinerary(db, session_id, plan)  # also sets the status to "planned"
    except Exception:
        yield sse.status(label, "error")
        raise
    on_saved(saved)
    yield sse.status(label, "end")
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
    change_request: str | None = None,
) -> Itinerary:
    """Ask the LLM for an ItineraryDraft and postprocess it into a valid Itinerary.

    With a `change_request` and an earlier version, it is an edit: compose gets the latest plan
    and is told to change only what was asked. If the draft breaks a rule, compose once more
    with the errors included. Raises ComposeError when the repair try fails too.
    """
    previous_versions = previous_versions or []
    latest = max(previous_versions, key=lambda itinerary: itinerary.version, default=None)
    if change_request and latest is not None:
        request = EDIT_REQUEST.format(change_request=change_request)
        system = build_system(profile, today, current_plan=latest)
    else:
        request = COMPOSE_REQUEST
        system = build_system(profile, today)

    result = await _compose_once(llm, system, messages, request, previous_versions, profile)
    if isinstance(result, Itinerary):
        return result

    result = await _compose_once(
        llm, system, messages, repair_request(result, request), previous_versions, profile
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


def repair_request(errors: list[str], request: str = COMPOSE_REQUEST) -> str:
    """The user message for the repair try: the request again plus what was wrong."""
    error_lines = "\n".join(f"- {error}" for error in errors)
    return (
        f"{request}\n\n"
        f"Your last plan broke these rules. Fix them and reply with the whole corrected plan:\n"
        f"{error_lines}"
    )


def build_system(
    profile: TripProfile, today: date | None = None, current_plan: Itinerary | None = None
) -> str:
    """System text for the compose call: its prompt plus today's date and the profile.

    For an edit, `current_plan` is the latest version. It is given in the draft shape compose
    replies with, so unchanged parts can be copied as they are.
    """
    today = today or date.today()
    parts = [
        context.load_prompt("compose").strip(),
        "# Context",
        f"Today is {context.format_date(today)} ({today.isoformat()}).",
        "## Trip profile\n" + context.render_profile(profile),
    ]
    if current_plan is not None:
        parts.append(
            f"## Current plan (version {current_plan.version})\n"
            "The plan to update, as an ItineraryDraft. Its stop keys are the stops' letter tags.\n"
            + as_draft(current_plan).model_dump_json(exclude_none=True)
        )
    return "\n\n".join(parts)


def as_draft(plan: Itinerary) -> ItineraryDraft:
    """A saved itinerary in the ItineraryDraft shape, with each stop's tag as its key.

    Code-owned fields (ids, weather, transit, links…) are dropped, as in a reply from the LLM.
    """
    return ItineraryDraft(
        title=plan.title,
        summary=plan.summary,
        start_date=plan.start_date,
        end_date=plan.end_date,
        travelers=plan.travelers,
        cities=[DraftCity.model_validate(city.model_dump()) for city in plan.cities],
        cost_estimate=plan.cost_estimate,
        assumptions=plan.assumptions,
        stops=[
            DraftStop.model_validate({**stop.model_dump(), "key": stop.tag}) for stop in plan.stops
        ],
        lodging=[
            DraftLodging.model_validate({**lodging.model_dump(), "stop_key": lodging.stop_tag})
            for lodging in plan.lodging
        ],
        days=[
            DraftDay(
                day_number=day.day_number,
                date=day.date,
                title=day.title,
                city=day.city,
                items=[
                    DraftItem.model_validate({**item.model_dump(), "stop_key": item.stop_tag})
                    for item in day.items
                ],
            )
            for day in plan.days
        ],
    )
