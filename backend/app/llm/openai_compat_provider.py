"""OpenAI-compatible provider: TAMU AI or any OpenAI-style endpoint (04-backend-design §3.0).

Uses the official `openai` SDK; its types stay inside this file. TAMU AI quirks it handles:
- non-streaming replies have no usable `choices`, so every call streams (`stream=True`);
- the stream mixes real chunks with empty "filler" chunks and thinking fields
  (`reasoning_content`, `thinking_blocks`): only non-empty `delta.content` text is used;
- `data: [DONE]` can appear twice; the SDK stops at the first one, where all content has arrived.
`response_format` is unverified on TAMU AI, so `generate_json` asks for JSON in the prompt and
validates the reply with Pydantic (one retry with the errors).
"""

import json
import re
from collections.abc import AsyncIterator

import httpx
import openai
from pydantic import ValidationError

from app.llm.base import ChatMessage, LLMError, T

TIMEOUT_SECONDS = 60.0  # per connect/read; a reply keeps streaming chunks, so this is generous

JSON_INSTRUCTION = (
    "\n\nReply with only a JSON object (no prose, no code fences) that matches this JSON Schema:\n"
)

CODE_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def is_json_object(text: str) -> bool:
    try:
        return isinstance(json.loads(text), dict)
    except ValueError:
        return False


def extract_json(text: str) -> str:
    """The JSON object in a model reply, ignoring code fences and surrounding prose.

    A fenced block wins only if its content is a JSON object; otherwise the first `{` that
    decodes to a complete object is used (so `{placeholders}` in prose are skipped).
    Returns the text unchanged if there's no object, so Pydantic reports it as invalid JSON.
    """
    for fenced in CODE_FENCE.finditer(text):
        content = fenced.group(1).strip()
        if is_json_object(content):
            return content
    decoder = json.JSONDecoder()
    for start, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, end = decoder.raw_decode(text, start)
        except ValueError:
            continue
        if isinstance(value, dict):
            return text[start:end]
    return text


def describe_errors(err: ValidationError) -> str:
    """Short, model-readable list of validation errors (no pydantic URLs)."""
    lines = []
    for error in err.errors(include_url=False):
        where = ".".join(str(part) for part in error["loc"]) or "(whole reply)"
        lines.append(f"- {where}: {error['msg']}")
    return "\n".join(lines)


def to_llm_error(err: openai.APIError) -> LLMError:
    """Map an SDK error to `LLMError`; auth/config problems are not retryable."""
    if isinstance(err, openai.APIStatusError):
        status = err.status_code
        if status in (401, 403):
            return LLMError(
                f"LLM endpoint rejected the API key (HTTP {status}); check LLM_API_KEY in backend/.env.",
                retryable=False,
            )
        if status in (400, 404, 422):
            return LLMError(
                f"LLM endpoint refused the request (HTTP {status}: {err.message}); "
                "check LLM_BASE_URL and LLM_MODEL.",
                retryable=False,
            )
        return LLMError(f"LLM endpoint error (HTTP {status}): {err.message}", retryable=True)
    if isinstance(err, openai.APITimeoutError):
        return LLMError("LLM request timed out.", retryable=True)
    if isinstance(err, openai.APIConnectionError):
        return LLMError(f"Could not reach the LLM endpoint: {err.message}", retryable=True)
    return LLMError(f"LLM stream failed: {err.message}", retryable=True)  # e.g. error mid-stream


class OpenAICompatProvider:
    name = "openai_compat"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = TIMEOUT_SECONDS,
        max_retries: int = 2,
        http_client: httpx.AsyncClient | None = None,  # tests pass one with a mock transport
    ):
        self.model = model
        self.client = openai.AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            max_retries=max_retries,  # SDK retries connection errors, 429 and 5xx with backoff
            http_client=http_client,
        )

    async def stream_text(self, *, system: str, messages: list[ChatMessage]) -> AsyncIterator[str]:
        async for text in self._stream(system, messages):
            yield text

    async def generate_json(self, *, system: str, messages: list[ChatMessage], schema: type[T]) -> T:
        system = system + JSON_INSTRUCTION + json.dumps(schema.model_json_schema())
        reply = await self._collect(system, messages)
        try:
            return schema.model_validate_json(extract_json(reply))
        except ValidationError as err:
            errors = describe_errors(err)

        # One retry: show the model its reply and what was wrong with it.
        retry_messages: list[ChatMessage] = [
            *messages,
            {"role": "assistant", "content": reply},
            {
                "role": "user",
                "content": f"That reply did not match the JSON Schema:\n{errors}\n"
                "Reply again with only the corrected JSON object.",
            },
        ]
        reply = await self._collect(system, retry_messages)
        try:
            return schema.model_validate_json(extract_json(reply))
        except ValidationError as err:
            raise LLMError(
                f"Model reply was not a valid {schema.__name__} after one retry:\n{describe_errors(err)}",
                retryable=True,
            ) from err

    async def _collect(self, system: str, messages: list[ChatMessage]) -> str:
        return "".join([text async for text in self._stream(system, messages)])

    async def _stream(self, system: str, messages: list[ChatMessage]) -> AsyncIterator[str]:
        """Yield the non-empty text pieces of one streamed reply; raise `LLMError` on failure."""
        got_text = False
        try:
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}, *messages],
                stream=True,
            )
            async with stream:  # closes the HTTP response even if the caller stops early
                async for chunk in stream:
                    for choice in getattr(chunk, "choices", None) or []:  # usage/filler chunks may have none
                        text = choice.delta.content if choice.index == 0 and choice.delta else None
                        if text:  # filler and thinking chunks have empty content
                            got_text = True
                            yield text
        except openai.APIError as err:
            raise to_llm_error(err) from err
        except ValueError as err:  # a `data:` line that isn't JSON (the SDK's json.JSONDecodeError)
            raise LLMError("LLM stream was malformed.", retryable=True) from err
        if not got_text:
            raise LLMError("LLM returned an empty reply.", retryable=True)
