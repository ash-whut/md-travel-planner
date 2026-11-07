"""Deterministic, offline LLM provider for tests and local dev (LLM_PROVIDER=fake)."""

from collections.abc import AsyncIterator

from app.llm.base import Message, T

CANNED_REPLY = "Sounds fun! Tell me where you want to go, when, and who is coming along."


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
        # Scripted answers per schema (TurnAnalysis, ItineraryDraft) arrive in later steps.
        raise NotImplementedError(f"FakeProvider.complete_json has no scripted reply for {schema.__name__}")
