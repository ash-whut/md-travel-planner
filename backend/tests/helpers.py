"""Helpers shared by test modules (import with `from helpers import ...`; pytest puts
`backend/tests` on sys.path). Nothing here touches the network or `backend/travel.db`."""

import json

import httpx

from app.llm.openai_compat_provider import OpenAICompatProvider

API_KEY = "test-key-123"


def parse_sse(text: str) -> list[tuple[str, dict]]:
    """`event:` / `data:` blocks of an SSE body as (event, data) pairs; pings are skipped."""
    events = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line and not line.startswith(":"))
        if "event" in fields:
            events.append((fields["event"], json.loads(fields["data"])))
    return events


# --- a mock OpenAI-compatible endpoint for the real `openai` SDK -------------------------------


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
