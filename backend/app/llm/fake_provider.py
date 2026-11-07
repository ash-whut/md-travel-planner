"""Deterministic, offline LLM provider for tests and local dev (LLM_PROVIDER=fake)."""

from collections.abc import AsyncIterator
from typing import Any

from app.llm.base import Message, T
from app.schemas.turn import TurnAnalysis

CANNED_REPLY = "Sounds fun! Tell me where you want to go, when, and who is coming along."

# Keyword → interest label, for the scripted San Jose demo.
DEMO_INTERESTS = [("tech", "tech"), ("food", "food"), ("garden", "gardens")]


class FakeProvider:
    name = "fake"

    def __init__(self, reply: str = CANNED_REPLY) -> None:
        self.reply = reply

    async def stream_text(self, system: str, messages: list[Message]) -> AsyncIterator[str]:
        # One chunk per word (keeping the space) so callers see a real multi-chunk stream.
        words = self.reply.split(" ")
        for i, word in enumerate(words):
            yield word if i == len(words) - 1 else word + " "

    async def complete_json(self, system: str, messages: list[Message], schema: type[T]) -> T:
        if schema is TurnAnalysis:
            return schema.model_validate(scripted_turn_analysis(last_user_text(messages)))
        # The scripted ItineraryDraft arrives in a later step.
        raise NotImplementedError(f"FakeProvider.complete_json has no scripted reply for {schema.__name__}")


def last_user_text(messages: list[Message]) -> str:
    for message in reversed(messages):
        if message["role"] == "user":
            return message["content"]
    return ""


def scripted_turn_analysis(text: str) -> dict[str, Any]:
    """A TurnAnalysis for the San Jose demo (frontend/src/fixtures/sanjose-*.json), by keywords.

    Messages without demo keywords give no profile updates. The action is always "chat" for now.
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
    return {"profile_updates": updates, "action": "chat", "change_request": None}
