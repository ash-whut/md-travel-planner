"""Deterministic, offline LLM provider for tests and local dev (LLM_PROVIDER=fake)."""

import json
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from app.llm.base import Message, T
from app.schemas.itinerary import ItineraryDraft
from app.schemas.turn import TurnAnalysis

CANNED_REPLY = "Sounds fun! Tell me where you want to go, when, and who is coming along."
SUMMARY_REPLY = "Your plan is ready on the left! Ask me to change any stop by its letter."
# Matches the San Jose demo: v2 swaps Baconhouse [F] for Good Karma Kitchen [L].
EDIT_SUMMARY_REPLY = (
    "Done! I replaced [F] (Baconhouse) with [L] Good Karma Kitchen, a vegan brunch spot. "
    "Everything else stays the same."
)
FAKE_DATA_DIR = Path(__file__).parent / "fake_data"

# Keyword → interest label, for the scripted San Jose demo.
DEMO_INTERESTS = [("tech", "tech"), ("food", "food"), ("garden", "gardens")]
# Phrases that ask for the plan (action=generate).
GENERATE_PHRASES = ("generate", "make the plan", "make a plan", "make my plan")
# A message with a tag like [F] or one of these words asks for a change (action=edit). The turn
# turns an edit into chat when there is no plan yet (agent/turn.py), as architecture.md says.
EDIT_WORDS = ("replace", "change", "swap")
TAG_TOKEN = re.compile(r"\[[A-Z]{1,2}\]")
# The turn asks for a plan summary with these phrases (agent/turn.py SUMMARY_REQUEST and
# EDIT_SUMMARY_REQUEST).
SUMMARY_PHRASE = "just made the plan"
EDIT_SUMMARY_PHRASE = "just updated the plan"
# Compose asks for an edit with this phrase (agent/pipeline.py EDIT_REQUEST).
EDIT_PHRASE = "change only what was asked"


class FakeProvider:
    name = "fake"

    def __init__(
        self,
        reply: str = CANNED_REPLY,
        drafts: list[dict[str, Any]] | None = None,
        summary_reply: str = SUMMARY_REPLY,
        edit_summary_reply: str = EDIT_SUMMARY_REPLY,
    ) -> None:
        """`drafts`: raw ItineraryDraft JSON replies to give, one per compose call, in order
        (tests use it for bad-then-good drafts). Once used up, the San Jose v1 draft is given,
        or the v2 draft for an edit. `summary_reply` / `edit_summary_reply` are streamed instead
        of `reply` when the turn asks for a plan / edit summary."""
        self.reply = reply
        self.drafts = list(drafts or [])
        self.summary_reply = summary_reply
        self.edit_summary_reply = edit_summary_reply

    async def stream_text(self, system: str, messages: list[Message]) -> AsyncIterator[str]:
        last_text = last_user_text(messages).lower()
        if EDIT_SUMMARY_PHRASE in last_text:
            text = self.edit_summary_reply
        elif SUMMARY_PHRASE in last_text:
            text = self.summary_reply
        else:
            text = self.reply
        # One chunk per word (keeping the space) so callers see a real multi-chunk stream.
        words = text.split(" ")
        for i, word in enumerate(words):
            yield word if i == len(words) - 1 else word + " "

    async def complete_json(self, system: str, messages: list[Message], schema: type[T]) -> T:
        if schema is TurnAnalysis:
            return schema.model_validate(scripted_turn_analysis(last_user_text(messages)))
        if schema is ItineraryDraft:
            # Validated like a real reply, so a bad draft raises ValidationError.
            if self.drafts:
                draft = self.drafts.pop(0)
            elif EDIT_PHRASE in last_user_text(messages).lower():
                draft = load_fake_data("draft_sanjose_v2")
            else:
                draft = load_fake_data("draft_sanjose_v1")
            return schema.model_validate(draft)
        raise NotImplementedError(f"FakeProvider.complete_json has no scripted reply for {schema.__name__}")


def load_fake_data(name: str) -> dict[str, Any]:
    """The JSON in `llm/fake_data/<name>.json`."""
    return json.loads((FAKE_DATA_DIR / f"{name}.json").read_text(encoding="utf-8"))


def last_user_text(messages: list[Message]) -> str:
    for message in reversed(messages):
        if message["role"] == "user":
            return message["content"]
    return ""


def scripted_turn_analysis(text: str) -> dict[str, Any]:
    """A TurnAnalysis for the San Jose demo (frontend/src/fixtures/sanjose-*.json), by keywords.

    Messages without demo keywords give no profile updates. Asking for the plan ("make the plan",
    "generate") gives action=generate; a tag or an edit word ("change [F] to something vegan",
    "replace H with something outdoors") gives action=edit with the message as the change
    request; everything else is chat. Without a plan the turn runs an edit as chat.
    """
    original_text = text
    text = text.lower()
    is_edit = TAG_TOKEN.search(original_text) is not None or any(
        re.search(rf"\b{word}\b", text) for word in EDIT_WORDS
    )
    updates: dict[str, Any] = {}
    if "san jose" in text:
        updates["cities"] = ["San Jose, CA"]
    if "college station" in text:
        updates["origin"] = "College Station, TX"
    if "first weekend of march" in text:
        updates.update(
            rough_timing="first weekend of March",
            start_date="2027-03-05",
            end_date="2027-03-07",
            duration_days=3,
        )
    if "just me" in text or "solo" in text:
        updates["travelers"] = 1
    interests = [label for keyword, label in DEMO_INTERESTS if keyword in text]
    if interests:
        updates["interests"] = interests
    if "vegan" in text:
        updates["dietary"] = "vegan"
    if is_edit:
        return {"profile_updates": updates, "action": "edit", "change_request": original_text}
    action = "generate" if any(phrase in text for phrase in GENERATE_PHRASES) else "chat"
    return {"profile_updates": updates, "action": action, "change_request": None}
