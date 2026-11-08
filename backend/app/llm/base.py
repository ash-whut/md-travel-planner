"""The LLMProvider protocol (architecture §6). Provider SDKs are imported only in app/llm/."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

# One chat message: {"role": "user" | "assistant", "content": "..."}
Message = dict[str, str]


@dataclass
class ToolSpec:
    """A tool the model may call. `parameters` is the JSON schema of its arguments."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class ToolCall:
    """One tool call the model asked for. `id` pairs it with its result in the next round."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolRound:
    """One finished round: the calls the model asked for and their results, in the same order."""

    calls: list[ToolCall]
    results: list[str]


class LLMProvider(Protocol):
    name: str

    def stream_text(self, system: str, messages: list[Message]) -> AsyncIterator[str]:
        """Yield the reply text in chunks as it arrives."""
        ...

    async def complete_json(self, system: str, messages: list[Message], schema: type[T]) -> T:
        """Return one reply parsed into `schema`."""
        ...

    async def tool_turn(
        self, system: str, messages: list[Message], rounds: list[ToolRound], tools: list[ToolSpec]
    ) -> list[ToolCall]:
        """Ask which tools to call next, given the earlier `rounds`. [] means no more tools."""
        ...
