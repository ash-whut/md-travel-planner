"""openai_compat (TAMU AI) adapter, 04-backend-design §3.0. No network.

Recorded and crafted SSE streams go through the real `openai` SDK (its HTTP client gets an
`httpx.MockTransport`), so the SDK's own SSE parsing and `[DONE]` handling are exercised.
"""

import json
from pathlib import Path

import httpx
import pytest
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.llm import ChatMessage, LLMError, get_provider
from app.llm.openai_compat_provider import OpenAICompatProvider, extract_json

RECORDED_STREAM = (Path(__file__).parent / "fixtures" / "tamu_stream_count.txt").read_bytes()
API_KEY = "test-key-123"
CHAT: list[ChatMessage] = [{"role": "user", "content": "Count to ten."}]


class TinyPlan(BaseModel):
    city: str
    days: int


def chunk(delta: dict, **extra) -> str:
    """One SSE line in TAMU's "real chunk" shape."""
    body = {"id": "chatcmpl-1", "object": "chat.completion.chunk", "created": 1, "model": "Claude-Opus-5"}
    return "data: " + json.dumps({**body, "choices": [{"index": 0, "delta": delta}], **extra}) + "\n\n"


def stream_of(*texts: str) -> bytes:
    """A stream whose content pieces are `texts`, with filler chunks around them, then [DONE]."""
    filler = chunk({"content": ""})
    return (filler + "".join(chunk({"content": t}) + filler for t in texts) + "data: [DONE]\n\n").encode()


def sse_response(body: bytes) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)


class FakeEndpoint:
    """MockTransport handler: replies with the queued responses in order and records requests."""

    def __init__(self, *replies: httpx.Response | Exception):
        self.replies = list(replies)
        self.requests: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.content))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def make_provider(endpoint: FakeEndpoint) -> OpenAICompatProvider:
    return OpenAICompatProvider(
        base_url="https://llm.test/openai",
        api_key=API_KEY,
        model="test-model",
        max_retries=0,  # tests check our error mapping, not the SDK's backoff
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(endpoint)),
    )


async def collect(provider: OpenAICompatProvider) -> list[str]:
    return [text async for text in provider.stream_text(system="You are a planner.", messages=CHAT)]


# --- stream_text -------------------------------------------------------------------------


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])  # git may check out CRLF
@pytest.mark.asyncio
async def test_recorded_tamu_stream_yields_only_real_text(newline):
    body = RECORDED_STREAM.replace(b"\r\n", b"\n").replace(b"\n", newline.encode())
    endpoint = FakeEndpoint(sse_response(body))

    chunks = await collect(make_provider(endpoint))

    assert "".join(chunks) == "1, 2, 3, 4, 5, 6, 7, 8, 9, 10."
    assert chunks == ["1,", " 2, 3, 4", ", 5, 6, ", "7, 8, 9,", " 10."]  # no empty filler chunks


@pytest.mark.asyncio
async def test_request_always_streams_with_system_prompt_first():
    endpoint = FakeEndpoint(sse_response(RECORDED_STREAM))

    await collect(make_provider(endpoint))

    sent = endpoint.requests[0]
    assert sent["stream"] is True
    assert sent["model"] == "test-model"
    assert sent["messages"] == [{"role": "system", "content": "You are a planner."}, *CHAT]


@pytest.mark.asyncio
async def test_thinking_fields_are_ignored():
    thinking = {
        "reasoning_content": "Let me think hard",
        "thinking_blocks": [{"type": "thinking", "thinking": "secret plan", "signature": "abc"}],
        "provider_specific_fields": {"reasoningContent": {"text": "secret plan"}},
        "content": "",
    }
    body = (chunk(thinking) + chunk({"content": "Hi!"}) + "data: [DONE]\n\n").encode()

    assert await collect(make_provider(FakeEndpoint(sse_response(body)))) == ["Hi!"]


@pytest.mark.asyncio
async def test_stops_at_first_done_and_skips_chunks_without_choices():
    body = (
        chunk({"content": "before"})
        + 'data: {"id": "chatcmpl-1", "object": "chat.completion.chunk", "created": 1, "model": "m", '
        '"choices": [], "usage": {"total_tokens": 3}}\n\n'
        + "data: [DONE]\n\n"
        + chunk({"content": "after"})
        + "data: [DONE]\n\n"
    ).encode()

    assert await collect(make_provider(FakeEndpoint(sse_response(body)))) == ["before"]


@pytest.mark.asyncio
async def test_stream_with_no_text_raises_retryable_error():
    body = (chunk({"content": ""}) + chunk({}) + "data: [DONE]\n\n").encode()

    with pytest.raises(LLMError, match="empty reply") as exc_info:
        await collect(make_provider(FakeEndpoint(sse_response(body))))

    assert exc_info.value.retryable is True


@pytest.mark.asyncio
async def test_error_event_mid_stream_raises_retryable_error():
    body = (chunk({"content": "Hel"}) + 'data: {"error": {"message": "overloaded"}}\n\n').encode()

    with pytest.raises(LLMError, match="overloaded") as exc_info:
        await collect(make_provider(FakeEndpoint(sse_response(body))))

    assert exc_info.value.retryable is True


# --- errors ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "retryable", "hint"),
    [
        (401, False, "LLM_API_KEY"),
        (403, False, "LLM_API_KEY"),
        (404, False, "LLM_MODEL"),
        (429, True, "HTTP 429"),
        (500, True, "HTTP 500"),
        (503, True, "HTTP 503"),
    ],
)
@pytest.mark.asyncio
async def test_http_errors_map_to_llm_error(status, retryable, hint):
    endpoint = FakeEndpoint(httpx.Response(status, json={"detail": "nope"}))

    with pytest.raises(LLMError, match=hint) as exc_info:
        await collect(make_provider(endpoint))

    assert exc_info.value.retryable is retryable
    assert API_KEY not in str(exc_info.value)


@pytest.mark.parametrize(
    ("error", "message"),
    [(httpx.ConnectError("refused"), "Could not reach"), (httpx.ReadTimeout("slow"), "timed out")],
    ids=["connection", "timeout"],
)
@pytest.mark.asyncio
async def test_network_errors_are_retryable(error, message):
    with pytest.raises(LLMError, match=message) as exc_info:
        await collect(make_provider(FakeEndpoint(error)))

    assert exc_info.value.retryable is True


# --- generate_json -----------------------------------------------------------------------

PLAN = '{"city": "Austin", "days": 3}'


@pytest.mark.parametrize(
    "reply",
    [PLAN, f"```json\n{PLAN}\n```", f"Sure! Here is the plan:\n{PLAN}\nEnjoy."],
    ids=["plain", "fenced", "with-prose"],
)
@pytest.mark.asyncio
async def test_generate_json_returns_validated_model(reply):
    endpoint = FakeEndpoint(sse_response(stream_of(reply[:7], reply[7:])))  # JSON split across chunks

    plan = await make_provider(endpoint).generate_json(system="Draft a plan.", messages=CHAT, schema=TinyPlan)

    assert plan == TinyPlan(city="Austin", days=3)
    system = endpoint.requests[0]["messages"][0]["content"]
    assert system.startswith("Draft a plan.")
    assert "Reply with only a JSON object" in system
    assert json.dumps(TinyPlan.model_json_schema()) in system


@pytest.mark.asyncio
async def test_generate_json_retries_once_with_validation_errors():
    bad = '{"city": "Austin", "days": "three"}'
    endpoint = FakeEndpoint(sse_response(stream_of(bad)), sse_response(stream_of(PLAN)))

    plan = await make_provider(endpoint).generate_json(system="Draft.", messages=CHAT, schema=TinyPlan)

    assert plan == TinyPlan(city="Austin", days=3)
    assert len(endpoint.requests) == 2
    retry_messages = endpoint.requests[1]["messages"]
    assert retry_messages[:2] == endpoint.requests[0]["messages"]  # same system + history
    assert retry_messages[-2] == {"role": "assistant", "content": bad}
    assert retry_messages[-1]["role"] == "user"
    assert "days" in retry_messages[-1]["content"]  # the validation error names the field


@pytest.mark.asyncio
async def test_generate_json_invalid_twice_raises_llm_error():
    endpoint = FakeEndpoint(sse_response(stream_of("no json here")), sse_response(stream_of('{"city": 1}')))

    with pytest.raises(LLMError, match="not a valid TinyPlan") as exc_info:
        await make_provider(endpoint).generate_json(system="Draft.", messages=CHAT, schema=TinyPlan)

    assert len(endpoint.requests) == 2
    assert isinstance(exc_info.value.__cause__, ValidationError)
    assert exc_info.value.retryable is True


def test_extract_json():
    assert extract_json(PLAN) == PLAN
    assert extract_json(f"```\n{PLAN}\n```") == PLAN
    assert extract_json('Here: {"a": {"b": 1}} done') == '{"a": {"b": 1}}'
    assert extract_json("no object") == "no object"


# --- factory -----------------------------------------------------------------------------

TAMU = {"llm_base_url": "https://chat-api.tamu.ai/openai", "llm_model": "protected.Claude-Opus-5"}


def test_factory_builds_openai_compat_provider():
    provider = get_provider(Settings(_env_file=None, llm_provider="openai_compat", llm_api_key=API_KEY, **TAMU))

    assert isinstance(provider, OpenAICompatProvider)
    assert provider.name == "openai_compat"
    assert provider.model == "protected.Claude-Opus-5"


@pytest.mark.parametrize(
    ("overrides", "missing"),
    [
        ({"llm_api_key": ""}, "LLM_API_KEY"),
        ({"llm_model": ""}, "LLM_MODEL"),
        ({"llm_base_url": "", "llm_model": ""}, "LLM_BASE_URL, LLM_MODEL"),
    ],
)
def test_factory_names_missing_openai_compat_settings(overrides, missing):
    values = {**TAMU, "llm_api_key": API_KEY, **overrides}

    with pytest.raises(LLMError, match=f"needs {missing} ") as exc_info:
        get_provider(Settings(_env_file=None, llm_provider="openai_compat", **values))

    assert exc_info.value.retryable is False
    assert API_KEY not in str(exc_info.value)
