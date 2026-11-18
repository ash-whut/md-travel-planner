"""LLM provider for any OpenAI-compatible endpoint, used for TAMU AI (LLM_PROVIDER=openai_compat).

Endpoint quirks are recorded in decisions D16.
"""

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI
from pydantic import ValidationError

from app.llm.base import Message, T, ToolCall, ToolRound, ToolSpec

logger = logging.getLogger(__name__)


class OpenAICompatProvider:
    name = "openai_compat"

    def __init__(self, model: str, client: AsyncOpenAI) -> None:
        # `client` is injected so tests can pass a stub with the same `chat.completions.create`.
        self.model = model
        self.client = client

    async def stream_text(self, system: str, messages: list[Message]) -> AsyncIterator[str]:
        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=_with_system(system, messages),
            stream=True,
        )
        async for chunk in stream:
            # Some chunks carry no choices or an empty delta (D16); skip them.
            if not chunk.choices:
                continue
            text = chunk.choices[0].delta.content
            if text:
                yield text

    async def complete_json(self, system: str, messages: list[Message], schema: type[T]) -> T:
        # The schema goes in the prompt, not in `response_format: json_schema`: TAMU AI's
        # Bedrock backend rejects limits like maxItems/minimum and "too complex" schemas (D18).
        chat = _with_system(_with_schema(system, schema), messages)
        reply = await self._ask_json(chat)
        try:
            return _parse_json(reply, schema)
        except ValidationError as error:
            # One retry: show the model its bad reply and the parse error.
            chat = chat + [
                {"role": "assistant", "content": reply},
                {"role": "user", "content": f"That reply did not match the schema: {error}\nReply with corrected JSON only."},
            ]
            return _parse_json(await self._ask_json(chat), schema)

    async def _ask_json(self, chat: list[Message]) -> str:
        """Ask for one non-streamed JSON reply; return its raw text."""
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=chat,
            # Must be explicit: if left out, TAMU AI streams anyway (D16).
            stream=False,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content or ""

    async def tool_turn(
        self, system: str, messages: list[Message], rounds: list[ToolRound], tools: list[ToolSpec]
    ) -> list[ToolCall]:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[*_with_system(system, messages), *_round_messages(rounds)],
            tools=[_openai_tool(tool) for tool in tools],
            stream=False,  # must be explicit, or TAMU AI streams anyway (D16)
        )
        calls: list[ToolCall] = []
        for tool_call in response.choices[0].message.tool_calls or []:
            try:
                arguments = json.loads(tool_call.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = None
            if not isinstance(arguments, dict):
                logger.warning("Skipping tool call %s: bad arguments JSON", tool_call.function.name)
                continue
            calls.append(ToolCall(id=tool_call.id, name=tool_call.function.name, arguments=arguments))
        return calls


def _openai_tool(tool: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": tool.name, "description": tool.description, "parameters": tool.parameters},
    }


def _round_messages(rounds: list[ToolRound]) -> list[dict[str, Any]]:
    """Each earlier round as OpenAI messages: the assistant's `tool_calls`, then one
    `role: "tool"` message per result, in the same order as the calls."""
    chat: list[dict[str, Any]] = []
    for tool_round in rounds:
        chat.append({
            "role": "assistant",
            # TAMU AI rejects null or missing content here (422); an empty string works.
            "content": "",
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                }
                for call in tool_round.calls
            ],
        })
        for call, result in zip(tool_round.calls, tool_round.results, strict=True):
            chat.append({"role": "tool", "tool_call_id": call.id, "content": result})
    return chat


def _with_system(system: str, messages: list[Message]) -> list[Message]:
    return [{"role": "system", "content": system}, *messages]


def _with_schema(system: str, schema: type[T]) -> str:
    return (
        f"{system}\n\nReply with only one JSON object (no other text) that matches this JSON Schema:\n"
        f"{json.dumps(schema.model_json_schema())}"
    )


def _parse_json(reply: str, schema: type[T]) -> T:
    """Validate the first JSON object in `reply`, ignoring code fences or text around it."""
    start = reply.find("{")
    if start >= 0:
        try:
            _, end = json.JSONDecoder().raw_decode(reply, start)
            reply = reply[start:end]
        except json.JSONDecodeError:
            pass  # leave it whole; Pydantic reports the error
    return schema.model_validate_json(reply)
