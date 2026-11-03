"""`data` payloads of the Stage 1 SSE events (03-contracts §4).

The `itinerary` event's payload is the `Itinerary` model itself. `profile` (Stage 3) and
`title` (Stage 4) payloads are added in those stages.
"""

from typing import Literal

from pydantic import BaseModel


class MessageStartData(BaseModel):
    """event: message_start — the assistant message begins."""

    message_id: str


class TokenData(BaseModel):
    """event: token — a chunk of streamed assistant text."""

    text: str


class StatusData(BaseModel):
    """event: status — tool activity or a phase like "Drafting your itinerary…" (tool is null)."""

    label: str
    tool: str | None = None
    state: Literal["start", "end", "error"]


class ErrorData(BaseModel):
    """event: error — failure; the stream ends."""

    message: str  # user-friendly text
    retryable: bool


class DoneData(BaseModel):
    """event: done — complete; the assistant message is persisted."""

    message_id: str
