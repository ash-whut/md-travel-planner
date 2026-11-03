"""Fake LLM provider: deterministic, offline, no API key (04-backend-design §3.0).

Default `LLM_PROVIDER`. It lets the whole app (and tests) run without a real model:
- `stream_text` streams a short canned reply that quotes the last user message;
- `generate_json` returns a JSON fixture from `app/llm/fixtures/<snake_case schema name>.json`
  (e.g. `ItineraryDraft` → `itinerary_draft.json`).
"""

import asyncio
import re
from collections.abc import AsyncIterator
from pathlib import Path

from pydantic import ValidationError

from app.llm.base import ChatMessage, LLMError, T

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Asked in turn, one per user message, so the conversation moves forward in a demo.
FOLLOW_UPS = [
    "Who's coming along, and what are you into: food, museums, outdoors, nightlife?",
    "Got it. Any dates in mind, and where are you starting from?",
    "Sounds good! When you're ready, click **Generate plan** and I'll draft an itinerary.",
]


def canned_reply(messages: list[ChatMessage]) -> str:
    """The fake's reply: same messages in, same text out."""
    user_texts = [m["content"] for m in messages if m["role"] == "user"]
    if not user_texts:
        return "Hi! I'm the demo planner (no AI model is connected). Where would you like to go?"

    quote = " ".join(user_texts[-1].split())  # one line, collapsed whitespace
    if len(quote) > 80:
        quote = quote[:77] + "..."
    follow_up = FOLLOW_UPS[min(len(user_texts), len(FOLLOW_UPS)) - 1]
    return f'You said: "{quote}". (Demo reply: no AI model is connected.) {follow_up}'


def fixture_name(schema_name: str) -> str:
    """`ItineraryDraft` → `itinerary_draft.json`."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", schema_name).lower() + ".json"


class FakeProvider:
    name = "fake"

    def __init__(self, *, chunk_size: int = 30, delay: float = 0.03, fixtures_dir: Path = FIXTURES_DIR):
        self.chunk_size = chunk_size
        self.delay = delay  # seconds between chunks, so the UI shows streaming; tests use 0
        self.fixtures_dir = fixtures_dir

    async def stream_text(self, *, system: str, messages: list[ChatMessage]) -> AsyncIterator[str]:
        reply = canned_reply(messages)
        for start in range(0, len(reply), self.chunk_size):
            if start and self.delay:
                await asyncio.sleep(self.delay)
            yield reply[start : start + self.chunk_size]

    async def generate_json(self, *, system: str, messages: list[ChatMessage], schema: type[T]) -> T:
        path = self.fixtures_dir / fixture_name(schema.__name__)
        if not path.is_file():
            raise LLMError(
                f"Fake provider has no fixture for {schema.__name__}: {path} not found", retryable=False
            )
        try:
            return schema.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError as err:
            # Same error type a real adapter raises for unusable model output.
            raise LLMError(
                f"Fake fixture {path.name} is not a valid {schema.__name__}:\n{err}", retryable=False
            ) from err
