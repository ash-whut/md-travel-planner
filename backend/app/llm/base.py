"""The LLMProvider protocol (architecture §6). Provider SDKs are imported only in app/llm/."""

from collections.abc import AsyncIterator
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

# One chat message: {"role": "user" | "assistant", "content": "..."}
Message = dict[str, str]


class LLMProvider(Protocol):
    name: str

    def stream_text(self, system: str, messages: list[Message]) -> AsyncIterator[str]:
        """Yield the reply text in chunks as it arrives."""
        ...

    async def complete_json(self, system: str, messages: list[Message], schema: type[T]) -> T:
        """Return one reply parsed into `schema`."""
        ...
