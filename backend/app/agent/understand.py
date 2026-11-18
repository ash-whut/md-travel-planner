"""The understand step (architecture §4, step 2): one JSON call per user turn.

It returns a TurnAnalysis (contracts §2.4). Its `profile_updates` are merged into the session
profile, and `missing_required` is recomputed.
"""

import logging
from datetime import date

from app.agent import context
from app.llm.base import LLMProvider, Message
from app.schemas.profile import TripProfile, missing_required
from app.schemas.turn import ProfileUpdates, TurnAnalysis

logger = logging.getLogger(__name__)


async def analyze(llm: LLMProvider, profile: TripProfile, messages: list[Message]) -> TurnAnalysis:
    """Ask the LLM what the latest user message says. On failure: no updates, just chat.

    A failed understand call should not cost the user their reply, so it falls back to a
    plain chat turn (the chat reply can still ask again).
    """
    try:
        return await llm.complete_json(build_system(profile), messages, TurnAnalysis)
    except Exception:
        logger.warning("Understand call failed; treating the turn as plain chat", exc_info=True)
        return TurnAnalysis()


def build_system(profile: TripProfile, today: date | None = None) -> str:
    """System text for the understand call: its prompt plus today's date and the profile."""
    today = today or date.today()
    return "\n\n".join(
        [
            context.load_prompt("understand").strip(),
            "# Context",
            f"Today is {context.format_date(today)} ({today.isoformat()}).",
            "## Trip profile so far\n" + context.render_profile(profile),
        ]
    )


def merge_profile(profile: TripProfile, updates: ProfileUpdates) -> TripProfile:
    """A new profile with the given fields replaced (lists too) and `missing_required` filled."""
    data = profile.model_dump()
    data.update(updates.model_dump(exclude_none=True))
    merged = TripProfile.model_validate(data)
    merged.missing_required = missing_required(merged)
    return merged


def profile_changed(old: TripProfile, new: TripProfile) -> bool:
    """True when a profile field changed. `missing_required` is derived, so it is ignored."""
    ignore = {"missing_required"}
    return old.model_dump(exclude=ignore) != new.model_dump(exclude=ignore)
