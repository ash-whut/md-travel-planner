"""Step 11: POST /api/sessions/{id}/messages streams one chat turn as SSE (contracts §4, §5)."""

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlmodel import Session

from app.api.chat import get_llm
from app.db import repo
from app.db.tables import MessageRow
from app.llm.base import Message
from app.llm.fake_provider import CANNED_REPLY

GREETING = "Hi, where do you want to go?"

Event = tuple[str, dict[str, Any]]


# --- helpers --------------------------------------------------------------------------------


def _parse_sse(text: str) -> list[Event]:
    """Parse a text/event-stream body into (event name, JSON data) pairs."""
    events: list[Event] = []
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    for block in normalized.split("\n\n"):
        name = "message"
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:"):].lstrip(" "))
        if data_lines:
            events.append((name, json.loads("\n".join(data_lines))))
    return events


def _create_session(client: TestClient) -> str:
    response = client.post("/api/sessions")
    assert response.status_code == 200
    return response.json()["id"]


def _send(client: TestClient, session_id: str, content: str) -> list[Event]:
    response = client.post(f"/api/sessions/{session_id}/messages", json={"content": content})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    return _parse_sse(response.text)


def _stored(engine: Engine, session_id: str) -> list[MessageRow]:
    # A fresh DB session, so nothing cached from before the request hides the new rows.
    with Session(engine) as db:
        return repo.list_messages(db, session_id)


class RaisingProvider:
    """Raises from stream_text after yielding `chunks_before` chunks."""

    name = "raising"

    def __init__(self, chunks_before: int = 0) -> None:
        self.chunks_before = chunks_before

    async def stream_text(self, system: str, messages: list[Message]) -> AsyncIterator[str]:
        for i in range(self.chunks_before):
            yield f"part{i} "
        raise RuntimeError("provider blew up")

    async def complete_json(self, system: str, messages: list[Message], schema: type[BaseModel]) -> Any:
        raise RuntimeError("provider blew up")


class RecordingProvider:
    """Streams a fixed reply and records what it was called with."""

    name = "recording"

    def __init__(self, reply_chunks: list[str]) -> None:
        self.reply_chunks = reply_chunks
        self.calls: list[tuple[str, list[Message]]] = []

    async def stream_text(self, system: str, messages: list[Message]) -> AsyncIterator[str]:
        self.calls.append((system, [dict(m) for m in messages]))
        for chunk in self.reply_chunks:
            yield chunk

    async def complete_json(self, system: str, messages: list[Message], schema: type[BaseModel]) -> Any:
        raise NotImplementedError


def _use_provider(client: TestClient, provider: Any) -> None:
    client.app.dependency_overrides[get_llm] = lambda: provider  # type: ignore[attr-defined]


# --- happy path: event order ----------------------------------------------------------------


def test_event_order_is_message_start_tokens_done(client: TestClient) -> None:
    session_id = _create_session(client)

    events = _send(client, session_id, "I want to visit San Jose")
    names = [name for name, _ in events]

    assert names[0] == "message_start"
    assert names[-1] == "done"
    # Step 16: "San Jose" changes the profile, so `profile` comes right before the tokens.
    assert names[1] == "profile"
    assert set(names[2:-1]) == {"token"}
    # The fake provider streams one chunk per word, so there are several tokens.
    assert len(names[2:-1]) > 1


def test_tokens_join_to_the_full_reply(client: TestClient) -> None:
    session_id = _create_session(client)

    events = _send(client, session_id, "Hello")

    tokens = [data for name, data in events if name == "token"]
    assert all(set(data) == {"text"} for data in tokens)
    assert "".join(data["text"] for data in tokens) == CANNED_REPLY


def test_message_start_and_done_share_a_uuid_message_id(client: TestClient) -> None:
    session_id = _create_session(client)

    events = _send(client, session_id, "Hello")

    start, done = events[0][1], events[-1][1]
    assert set(start) == {"message_id"}
    assert set(done) == {"message_id"}
    assert start["message_id"] == done["message_id"]
    assert uuid.UUID(done["message_id"]).version == 4


def test_no_error_event_on_success(client: TestClient) -> None:
    session_id = _create_session(client)

    events = _send(client, session_id, "Hello")

    assert "error" not in [name for name, _ in events]


# --- persistence ----------------------------------------------------------------------------


def test_user_and_assistant_messages_are_saved(client: TestClient, db_engine: Engine) -> None:
    session_id = _create_session(client)

    events = _send(client, session_id, "I want to visit San Jose")

    stored = _stored(db_engine, session_id)
    assert [(m.role, m.content) for m in stored] == [
        ("assistant", GREETING),
        ("user", "I want to visit San Jose"),
        ("assistant", CANNED_REPLY),
    ]
    assert stored[-1].id == events[-1][1]["message_id"]


def test_saved_assistant_content_equals_streamed_tokens(
    client: TestClient, db_engine: Engine
) -> None:
    provider = RecordingProvider(["Great ", "choice, ", "[A] ", "is fun."])
    _use_provider(client, provider)
    session_id = _create_session(client)

    events = _send(client, session_id, "Go")

    streamed = "".join(data["text"] for name, data in events if name == "token")
    assert streamed == "Great choice, [A] is fun."
    assert _stored(db_engine, session_id)[-1].content == streamed


def test_get_session_shows_the_new_messages(client: TestClient) -> None:
    session_id = _create_session(client)
    events = _send(client, session_id, "Hello there")

    body = client.get(f"/api/sessions/{session_id}").json()

    assert [(m["role"], m["content"]) for m in body["messages"]] == [
        ("assistant", GREETING),
        ("user", "Hello there"),
        ("assistant", CANNED_REPLY),
    ]
    assert body["messages"][-1]["id"] == events[-1][1]["message_id"]


def test_two_turns_append_in_order_with_distinct_ids(
    client: TestClient, db_engine: Engine
) -> None:
    session_id = _create_session(client)

    first = _send(client, session_id, "first")
    second = _send(client, session_id, "second")

    assert first[-1][1]["message_id"] != second[-1][1]["message_id"]
    stored = _stored(db_engine, session_id)
    assert [(m.role, m.content) for m in stored] == [
        ("assistant", GREETING),
        ("user", "first"),
        ("assistant", CANNED_REPLY),
        ("user", "second"),
        ("assistant", CANNED_REPLY),
    ]


def test_provider_sees_history_ending_with_the_user_message(client: TestClient) -> None:
    provider = RecordingProvider(["ok"])
    _use_provider(client, provider)
    session_id = _create_session(client)

    _send(client, session_id, "Plan me a weekend")

    assert len(provider.calls) == 1
    system, messages = provider.calls[0]
    assert isinstance(system, str) and system
    assert messages[0] == {"role": "assistant", "content": GREETING}
    assert messages[-1] == {"role": "user", "content": "Plan me a weekend"}


def test_messages_only_go_to_their_own_session(client: TestClient, db_engine: Engine) -> None:
    first = _create_session(client)
    second = _create_session(client)

    _send(client, second, "only in the second")

    assert [m.content for m in _stored(db_engine, first)] == [GREETING]


# --- unknown session ------------------------------------------------------------------------


@pytest.mark.parametrize("session_id", [str(uuid.uuid4()), "not-a-uuid"])
def test_unknown_session_returns_404(
    client: TestClient, db_engine: Engine, session_id: str
) -> None:
    response = client.post(f"/api/sessions/{session_id}/messages", json={"content": "hi"})

    assert response.status_code == 404
    assert response.json() == {"detail": "Session not found"}
    assert _stored(db_engine, session_id) == []


def test_unknown_session_does_not_call_the_provider(client: TestClient) -> None:
    provider = RecordingProvider(["ok"])
    _use_provider(client, provider)

    response = client.post(f"/api/sessions/{uuid.uuid4()}/messages", json={"content": "hi"})

    assert response.status_code == 404
    assert provider.calls == []


# --- provider failure -----------------------------------------------------------------------


def test_raising_provider_emits_error_last(client: TestClient) -> None:
    _use_provider(client, RaisingProvider())
    session_id = _create_session(client)

    events = _send(client, session_id, "Hello")
    names = [name for name, _ in events]

    assert names[0] == "message_start"
    assert names[-1] == "error"
    assert "done" not in names
    assert names.count("error") == 1


def test_error_event_has_friendly_message_and_retryable_flag(client: TestClient) -> None:
    _use_provider(client, RaisingProvider())
    session_id = _create_session(client)

    data = _send(client, session_id, "Hello")[-1][1]

    assert set(data) == {"message", "retryable"}
    assert isinstance(data["message"], str) and data["message"]
    assert isinstance(data["retryable"], bool)
    # User-friendly text: the raw exception text must not leak to the client.
    assert "provider blew up" not in data["message"]
    assert "RuntimeError" not in data["message"]


def test_raising_provider_keeps_the_user_message(client: TestClient, db_engine: Engine) -> None:
    _use_provider(client, RaisingProvider())
    session_id = _create_session(client)

    _send(client, session_id, "Keep me please")

    stored = _stored(db_engine, session_id)
    assert [(m.role, m.content) for m in stored] == [
        ("assistant", GREETING),
        ("user", "Keep me please"),
    ]


def test_provider_failing_mid_stream_ends_with_error(
    client: TestClient, db_engine: Engine
) -> None:
    _use_provider(client, RaisingProvider(chunks_before=2))
    session_id = _create_session(client)

    events = _send(client, session_id, "Hello")
    names = [name for name, _ in events]

    assert names == ["message_start", "token", "token", "error"]
    stored = _stored(db_engine, session_id)
    assert [m.role for m in stored] == ["assistant", "user"]
    assert stored[-1].content == "Hello"


def test_failed_user_message_save_emits_message_start_then_error(
    client: TestClient, db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = _create_session(client)
    provider = RecordingProvider(["ok"])
    _use_provider(client, provider)
    real_add_message = repo.add_message

    def failing_add_message(db: Session, sid: str, role: str, content: str, **kwargs: Any) -> Any:
        if role == "user":
            raise RuntimeError("db write failed")
        return real_add_message(db, sid, role, content, **kwargs)

    # turn.py calls repo.add_message through the module, so patching the attribute is enough.
    monkeypatch.setattr(repo, "add_message", failing_add_message)

    events = _send(client, session_id, "Hello")

    # contracts §5: message_start always comes first, even when the turn fails at once.
    assert [name for name, _ in events] == ["message_start", "error"]
    assert set(events[0][1]) == {"message_id"}
    assert "db write failed" not in events[1][1]["message"]
    assert provider.calls == []
    assert [m.content for m in _stored(db_engine, session_id)] == [GREETING]


def test_session_still_works_after_a_failed_turn(client: TestClient, db_engine: Engine) -> None:
    session_id = _create_session(client)
    _use_provider(client, RaisingProvider())
    _send(client, session_id, "first try")

    client.app.dependency_overrides.pop(get_llm)  # type: ignore[attr-defined]
    events = _send(client, session_id, "second try")

    assert events[-1][0] == "done"
    assert [m.content for m in _stored(db_engine, session_id)] == [
        GREETING, "first try", "second try", CANNED_REPLY,
    ]


# --- body validation (content is 1–4000 chars) ----------------------------------------------


@pytest.mark.parametrize("body", [{"content": ""}, {"content": "x" * 4001}, {}])
def test_invalid_body_is_rejected_and_nothing_saved(
    client: TestClient, db_engine: Engine, body: dict[str, Any]
) -> None:
    session_id = _create_session(client)

    response = client.post(f"/api/sessions/{session_id}/messages", json=body)

    # FastAPI's default validation status is 422; contracts §4 lists 400 for bad input.
    assert response.status_code in (400, 422)
    assert [m.content for m in _stored(db_engine, session_id)] == [GREETING]


@pytest.mark.parametrize("content", ["   ", "\n\t  "])
def test_whitespace_only_content_is_rejected_and_nothing_saved(
    client: TestClient, db_engine: Engine, content: str
) -> None:
    provider = RecordingProvider(["ok"])
    _use_provider(client, provider)
    session_id = _create_session(client)

    response = client.post(f"/api/sessions/{session_id}/messages", json={"content": content})

    assert response.status_code == 422
    assert [m.content for m in _stored(db_engine, session_id)] == [GREETING]
    assert provider.calls == []


@pytest.mark.parametrize("content", ["x", "x" * 4000])
def test_boundary_lengths_are_accepted(
    client: TestClient, db_engine: Engine, content: str
) -> None:
    session_id = _create_session(client)

    events = _send(client, session_id, content)

    assert events[-1][0] == "done"
    assert _stored(db_engine, session_id)[1].content == content
