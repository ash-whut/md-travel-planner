"""LLM provider for any OpenAI-compatible endpoint, used for TAMU AI (LLM_PROVIDER=openai_compat).

Endpoint quirks are recorded in decisions D16.
"""

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI
from pydantic import ValidationError

from app.llm.base import Message, ReplyCutOff, T, ToolCall, ToolRound, ToolSpec

logger = logging.getLogger(__name__)

# Output cap for JSON replies. Without it TAMU AI's default cap cut 3-day plans off mid-JSON (D33).
MAX_JSON_TOKENS = 16000


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
        # Buffer for stripping <think>…</think> blocks that may span chunk boundaries.
        think_buf = ""
        inside_think = False
        async for chunk in stream:
            # Some chunks carry no choices or an empty delta (D16); skip them.
            if not chunk.choices:
                continue
            text = chunk.choices[0].delta.content
            if not text:
                continue
            # Accumulate into buffer and strip any complete or partial <think> blocks.
            think_buf += text
            think_buf, inside_think, out = _strip_think(think_buf, inside_think)
            if out:
                yield out

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
            max_tokens=MAX_JSON_TOKENS,
        )
        choice = response.choices[0]
        if getattr(choice, "finish_reason", None) == "length":
            # The JSON is incomplete. Fail now instead of retrying: every retry would be cut off
            # at the same limit, and the user would wait through all of them.
            message = f"JSON reply was cut off at the {MAX_JSON_TOKENS}-token output limit"
            logger.warning(message)
            raise ReplyCutOff(message)
        return choice.message.content or ""

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


def _strip_think(buf: str, inside: bool) -> tuple[str, bool, str]:
    """Remove all complete `<think>…</think>` blocks from `buf`, and track partial ones.

    Returns `(remaining_buf, still_inside, safe_text_to_yield)`. `remaining_buf` is whatever
    hasn't been released yet (a partial tag or partial block). `safe_text_to_yield` is the
    text outside any think block that is safe to send to the frontend now.

    The caller accumulates `buf` across chunks so a tag that arrives split across two chunks
    ("…<thi" then "nk>…") is handled correctly.
    """
    OPEN = "<think>"
    CLOSE = "</think>"
    out_parts: list[str] = []
    pos = 0
    while pos < len(buf):
        if inside:
            # Looking for the closing tag.
            end = buf.find(CLOSE, pos)
            if end == -1:
                # Closing tag not yet arrived; hold the whole remaining buffer.
                return buf[pos:], True, "".join(out_parts)
            # Skip past </think>
            pos = end + len(CLOSE)
            inside = False
        else:
            # Looking for an opening tag.
            start = buf.find(OPEN, pos)
            if start == -1:
                # No opening tag. But a trailing "<" could be the start of a partial "<think>",
                # so keep at most len(OPEN)-1 chars buffered when the buffer ends with "<…".
                last_lt = buf.rfind("<", pos)
                if last_lt != -1 and last_lt > len(buf) - len(OPEN):
                    # Possible partial tag at the end: release everything before the "<".
                    out_parts.append(buf[pos:last_lt])
                    return buf[last_lt:], False, "".join(out_parts)
                # No possible partial tag: release everything.
                out_parts.append(buf[pos:])
                return "", False, "".join(out_parts)
            # Everything before the opening tag is safe to release.
            out_parts.append(buf[pos:start])
            pos = start + len(OPEN)
            inside = True
    return "", inside, "".join(out_parts)
