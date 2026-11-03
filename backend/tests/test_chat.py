"""Chat route (03-contracts §3, §4): POST /api/sessions/{id}/messages streams SSE events."""

import json
from collections.abc import AsyncIterator

import pytest
from sqlmodel import Session

from app.agent import orchestrator
from app.agent.fixed_messages import GREETING
from app.core.config import Settings, get_settings
from app.db.tables import SessionRow
from app.llm import ChatMessage, LLMError
from app.llm.fake_provider import canned_reply
from app.main import app


def parse_sse(text: str) -> list[tuple[str, dict]]:
    """`event:` / `data:` blocks of an SSE body as (event, data) pairs; pings are skipped."""
    events = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line and not line.startswith(":"))
        if "event" in fields:
            events.append((fields["event"], json.loads(fields["data"])))
    return events


def send(client, session_id: str, content: str) -> list[tuple[str, dict]]:
    response = client.post(f"/api/sessions/{session_id}/messages", json={"content": content})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    return parse_sse(response.text)


class RecordingProvider:
    """Streams fixed chunks, records what it was sent, and can fail after the first chunk."""

    name = "fake"

    def __init__(self, chunks=("Hello ", "there!"), error: Exception | None = None):
        self.chunks = chunks
        self.error = error
        self.calls: list[dict] = []

    async def stream_text(self, *, system: str, messages: list[ChatMessage]) -> AsyncIterator[str]:
        self.calls.append({"system": system, "messages": list(messages)})
        for index, chunk in enumerate(self.chunks):
            if index == 1 and self.error:
                raise self.error
            yield chunk


@pytest.fixture
def new_session(client) -> dict:
    return client.post("/api/sessions").json()


@pytest.fixture
def use_provider(monkeypatch):
    """Make the chat turn use the given provider instead of the one LLM_PROVIDER picks."""

    def install(provider):
        monkeypatch.setattr(orchestrator, "get_provider", lambda _settings: provider)
        return provider

    return install


def stored_messages(client, session_id: str) -> list[tuple[str, str]]:
    return [(m["role"], m["content"]) for m in client.get(f"/api/sessions/{session_id}").json()["messages"]]


# --- happy path ----------------------------------------------------------------------------


def test_events_are_message_start_tokens_done(client, new_session):
    events = send(client, new_session["id"], "Austin for 3 days")

    names = [name for name, _ in events]
    assert names[0] == "message_start" and names[-1] == "done"
    assert set(names[1:-1]) == {"token"} and len(names) > 3  # the fake streams several chunks
    assert events[0][1]["message_id"] == events[-1][1]["message_id"]
    reply = "".join(data["text"] for name, data in events if name == "token")
    assert reply == canned_reply([{"role": "user", "content": "Austin for 3 days"}])


def test_user_and_assistant_messages_are_saved(client, engine, new_session):
    with Session(engine) as db:
        updated_before = db.get(SessionRow, new_session["id"]).updated_at

    events = send(client, new_session["id"], "  Austin for 3 days\n")
    reply = "".join(data["text"] for name, data in events if name == "token")

    detail = client.get(f"/api/sessions/{new_session['id']}").json()

    assert [(m["role"], m["content"]) for m in detail["messages"]] == [
        ("assistant", GREETING),
        ("user", "Austin for 3 days"),  # surrounding whitespace trimmed
        ("assistant", reply),
    ]
    assert detail["messages"][-1]["id"] == events[-1][1]["message_id"]
    with Session(engine) as db:
        assert db.get(SessionRow, new_session["id"]).updated_at > updated_before  # API shows whole seconds


def test_llm_gets_system_prompt_and_history(client, new_session, use_provider):
    provider = use_provider(RecordingProvider())

    send(client, new_session["id"], "Austin for 3 days")
    send(client, new_session["id"], "Two friends, from Houston")

    system_prompt = (orchestrator.PROMPTS_DIR / "system.md").read_text(encoding="utf-8")
    assert all(call["system"] == system_prompt for call in provider.calls)
    assert "Generate plan" in system_prompt
    # The code-written greeting is left out; the conversation starts with the user.
    assert provider.calls[1]["messages"] == [
        {"role": "user", "content": "Austin for 3 days"},
        {"role": "assistant", "content": "Hello there!"},
        {"role": "user", "content": "Two friends, from Houston"},
    ]


# --- errors --------------------------------------------------------------------------------


def test_unconfigured_provider_sends_error_event_not_500(client, new_session):
    # openai_compat with no LLM_* settings: the factory raises LLMError(retryable=False).
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, llm_provider="openai_compat")

    events = send(client, new_session["id"], "Austin for 3 days")

    assert [name for name, _ in events] == ["message_start", "error"]
    error = events[1][1]
    assert error == {"message": orchestrator.SETUP_MESSAGE, "retryable": False}
    assert "LLM_API_KEY" not in error["message"]  # the raw LLMError text stays in the log
    assert stored_messages(client, new_session["id"]) == [("assistant", GREETING)]


def test_llm_error_mid_stream_sends_retryable_error_and_saves_nothing(client, new_session, use_provider):
    use_provider(RecordingProvider(error=LLMError("HTTP 503 from upstream", retryable=True)))

    events = send(client, new_session["id"], "Austin for 3 days")

    assert [name for name, _ in events] == ["message_start", "token", "error"]
    assert events[-1][1] == {"message": orchestrator.RETRY_MESSAGE, "retryable": True}
    assert stored_messages(client, new_session["id"]) == [("assistant", GREETING)]


@pytest.mark.parametrize("chunks", [(), (" ", "\n")], ids=["no-chunks", "whitespace-only"])
def test_empty_reply_sends_retryable_error_and_saves_nothing(client, new_session, use_provider, chunks):
    # openai_compat drops filler chunks, so a TAMU reply can stream no text at all.
    use_provider(RecordingProvider(chunks=chunks))

    events = send(client, new_session["id"], "Austin for 3 days")

    assert [name for name, _ in events] == ["message_start"] + ["token"] * len(chunks) + ["error"]
    assert events[-1][1] == {"message": orchestrator.RETRY_MESSAGE, "retryable": True}
    assert stored_messages(client, new_session["id"]) == [("assistant", GREETING)]


def test_unexpected_exception_becomes_error_event(client, new_session, use_provider):
    use_provider(RecordingProvider(error=RuntimeError("boom")))

    events = send(client, new_session["id"], "Austin for 3 days")

    assert [name for name, _ in events] == ["message_start", "token", "error"]
    assert events[-1][1] == {"message": orchestrator.RETRY_MESSAGE, "retryable": True}
    assert "boom" not in json.dumps(events)


def test_unknown_session_is_404(client):
    response = client.post("/api/sessions/no-such-session/messages", json={"content": "hi"})

    assert response.status_code == 404
    assert response.json() == {"detail": "Session not found"}


@pytest.mark.parametrize("body", [{"content": ""}, {"content": "   "}, {"content": "x" * 4001}, {}])
def test_invalid_body_is_400_with_detail(client, engine, body):
    with Session(engine) as db:
        db.add(row := SessionRow(llm_provider="fake"))
        db.commit()
        session_id = row.id

    response = client.post(f"/api/sessions/{session_id}/messages", json=body)

    assert response.status_code == 400
    assert response.json()["detail"].startswith("content: ")


def test_malformed_json_is_400_with_readable_detail(client, new_session):
    response = client.post(
        f"/api/sessions/{new_session['id']}/messages",
        content='{"content": "hi"',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Request body is not valid JSON"}


def test_4000_characters_is_accepted(client, new_session):
    events = send(client, new_session["id"], "x" * 4000)

    assert events[-1][0] == "done"
