"""Deterministic, offline LLM provider for tests and local dev (LLM_PROVIDER=fake)."""

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from app.llm.base import Message, T
from app.schemas.itinerary import ItineraryDraft
from app.schemas.turn import TurnAnalysis

CANNED_REPLY = "Sounds fun! Tell me where you want to go, when, and who is coming along."
SUMMARY_REPLY = "Your plan is ready on the left! Ask me to change any stop by its letter."
FAKE_DATA_DIR = Path(__file__).parent / "fake_data"

# Keyword → interest label, for the scripted San Jose demo.
DEMO_INTERESTS = [("tech", "tech"), ("food", "food"), ("garden", "gardens")]
# Phrases that ask for the plan (action=generate).
GENERATE_PHRASES = ("generate", "make the plan", "make a plan", "make my plan")
# The turn asks for a plan summary with this phrase (agent/turn.py SUMMARY_REQUEST).
SUMMARY_PHRASE = "just made the plan"


class FakeProvider:
    name = "fake"

    def __init__(
        self,
        reply: str = CANNED_REPLY,
        drafts: list[dict[str, Any]] | None = None,
        summary_reply: str = SUMMARY_REPLY,
    ) -> None:
        """`drafts`: raw ItineraryDraft JSON replies to give, one per compose call, in order
        (tests use it for bad-then-good drafts). Once used up, the San Jose v1 draft is given.
        `summary_reply` is streamed instead of `reply` when the turn asks for a plan summary."""
        self.reply = reply
        self.drafts = list(drafts or [])
        self.summary_reply = summary_reply

    async def stream_text(self, system: str, messages: list[Message]) -> AsyncIterator[str]:
        wants_summary = SUMMARY_PHRASE in last_user_text(messages).lower()
        text = self.summary_reply if wants_summary else self.reply
        # One chunk per word (keeping the space) so callers see a real multi-chunk stream.
        words = text.split(" ")
        for i, word in enumerate(words):
            yield word if i == len(words) - 1 else word + " "

    async def complete_json(self, system: str, messages: list[Message], schema: type[T]) -> T:
        if schema is TurnAnalysis:
            return schema.model_validate(scripted_turn_analysis(last_user_text(messages)))
        if schema is ItineraryDraft:
            # Validated like a real reply, so a bad draft raises ValidationError.
            draft = self.drafts.pop(0) if self.drafts else load_fake_data("draft_sanjose_v1")
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
    "generate") gives action=generate; everything else is chat (edit arrives in step 25).
    """
    text = text.lower()
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
    action = "generate" if any(phrase in text for phrase in GENERATE_PHRASES) else "chat"
    return {"profile_updates": updates, "action": action, "change_request": None}
