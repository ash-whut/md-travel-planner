"""The LLM provider interface (04-backend-design §3.0, Stage 1: text + JSON, no tools).

Everything outside `app/llm/` talks to a model only through `LLMProvider`, so providers can be
swapped with `LLM_PROVIDER` and no SDK types leak into the rest of the app.
"""

from collections.abc import AsyncIterator
from typing import Literal, Protocol, TypedDict, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class ChatMessage(TypedDict):
    """One chat turn sent to the model, built from the `message` table."""

    role: Literal["user", "assistant"]
    content: str


class LLMError(Exception):
    """A provider failed (network, auth, bad output, misconfiguration).

    Adapters raise only this, so callers can turn it into an SSE `error` event
    (`ErrorData(message, retryable)`) without knowing any SDK. `str(err)` is meant for logs;
    show the user a friendly message instead.
    """

    def __init__(self, message: str, *, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable  # False when trying again can't help (e.g. bad config)


class LLMProvider(Protocol):
    name: str  # "fake" | "openai_compat" | "anthropic"

    def stream_text(self, *, system: str, messages: list[ChatMessage]) -> AsyncIterator[str]:
        """Stream the assistant reply as text chunks (implement as an `async def` generator)."""
        ...

    async def generate_json(self, *, system: str, messages: list[ChatMessage], schema: type[T]) -> T:
        """Return the model's answer validated as `schema`; raise `LLMError` if it can't."""
        ...
