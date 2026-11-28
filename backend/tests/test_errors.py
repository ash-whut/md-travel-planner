"""Step 46: error + loading pass, backend side (D36, contracts §5).

Specified by plan step 46 and D36: Retry resends the text, and the server doesn't save the user
message again when the session's last user message is that same text with no finished reply
after it (only nothing or stopped replies without a plan version; a different message, or the same text after a
finished reply, is saved as usual); a reply that ends with
`error` is not saved; a Stop before any text saves no reply unless a plan version was saved in
that turn; a failed plan keeps the old plan; if `run_planner` raises outside `tool_turn`, the
"Choosing what to look up…" status still gets its error.

No network: FakeProvider / small scripted providers, TOOL_PROVIDER_MODE=mock, a temp DB.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlmodel import Session

from app.agent import planner, turn
from app.agent.planner import CHOOSING_LABEL, run_planner
from app.agent.turn import TurnLlms
from app.api.chat import get_llm
from app.db import repo
from app.db.tables import MessageRow
from app.llm.base import Message, ReplyCutOff, ToolCall, ToolRound, ToolSpec
from app.llm.fake_provider import CANNED_REPLY, FakeProvider
from app.schemas.itinerary import Itinerary
from app.schemas.profile import TripProfile

GREETING = "Hi, where do you want to go?"
MARKER = " *(stopped)*"

Event = tuple[str, dict[str, Any]]


# --- helpers --------------------------------------------------------------------------------


def _parse_sse(text: str) -> list[Event]:
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
    return _parse_sse(response.text)


def _generate(client: TestClient, session_id: str) -> list[Event]:
    response = client.post(f"/api/sessions/{session_id}/generate", json={})
    assert response.status_code == 200
    return _parse_sse(response.text)


def _stored(engine: Engine, session_id: str) -> list[MessageRow]:
    with Session(engine) as db:
        return repo.list_messages(db, session_id)


def _pairs(engine: Engine, session_id: str) -> list[tuple[str, str]]:
    return [(m.role, m.content) for m in _stored(engine, session_id)]


def _versions(engine: Engine, session_id: str) -> list[Itinerary]:
    with Session(engine) as db:
        return repo.list_itineraries(db, session_id)


def _use_provider(client: TestClient, provider: Any) -> None:
    client.app.dependency_overrides[get_llm] = lambda: TurnLlms(provider, provider)  # type: ignore[attr-defined]


def _use_real_fake(client: TestClient) -> None:
    client.app.dependency_overrides.pop(get_llm, None)  # type: ignore[attr-defined]


class RaisingProvider:
    """Streams `chunks_before` chunks, then raises (a reply that fails mid-stream)."""

    name = "raising"

    def __init__(self, chunks_before: int = 0) -> None:
        self.chunks_before = chunks_before

    async def stream_text(self, system: str, messages: list[Message]) -> AsyncIterator[str]:
        for i in range(self.chunks_before):
            yield f"part{i} "
        raise RuntimeError("provider blew up")

    async def complete_json(self, system: str, messages: list[Message], schema: type[BaseModel]) -> Any:
        raise RuntimeError("provider blew up")


class RecordingFake(FakeProvider):
    """The normal fake, recording the chat each reply is written for."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.chats: list[list[Message]] = []

    async def stream_text(self, system: str, messages: list[Message]) -> AsyncIterator[str]:
        self.chats.append([dict(m) for m in messages])  # type: ignore[misc]
        async for chunk in super().stream_text(system, messages):
            yield chunk


# --- Retry: the server doesn't save the same user message twice ------------------------------


def test_retry_after_a_failed_turn_saves_the_user_message_once(
    client: TestClient, db_engine: Engine
) -> None:
    session_id = _create_session(client)
    _use_provider(client, RaisingProvider())
    assert _send(client, session_id, "Plan Austin for me")[-1][0] == "error"

    _use_real_fake(client)
    events = _send(client, session_id, "Plan Austin for me")  # Retry resends the same text

    assert events[-1][0] == "done"
    assert _pairs(db_engine, session_id) == [
        ("assistant", GREETING),
        ("user", "Plan Austin for me"),
        ("assistant", CANNED_REPLY),
    ]


def test_retry_reply_is_written_for_a_chat_with_the_message_once(
    client: TestClient, db_engine: Engine
) -> None:
    session_id = _create_session(client)
    _use_provider(client, RaisingProvider())
    _send(client, session_id, "hello there")

    provider = RecordingFake()
    _use_provider(client, provider)
    _send(client, session_id, "hello there")

    chat = provider.chats[-1]
    assert chat[-1] == {"role": "user", "content": "hello there"}
    assert sum(1 for m in chat if m["content"] == "hello there") == 1


def test_several_retries_still_save_the_message_once(client: TestClient, db_engine: Engine) -> None:
    session_id = _create_session(client)
    _use_provider(client, RaisingProvider())
    for _ in range(3):
        assert _send(client, session_id, "again")[-1][0] == "error"

    assert _pairs(db_engine, session_id) == [("assistant", GREETING), ("user", "again")]


def test_a_different_message_after_a_failure_is_saved(client: TestClient, db_engine: Engine) -> None:
    session_id = _create_session(client)
    _use_provider(client, RaisingProvider())
    _send(client, session_id, "first try")

    _use_real_fake(client)
    _send(client, session_id, "something else")

    assert _pairs(db_engine, session_id) == [
        ("assistant", GREETING),
        ("user", "first try"),
        ("user", "something else"),
        ("assistant", CANNED_REPLY),
    ]


def test_same_text_after_a_saved_reply_is_saved_again(client: TestClient, db_engine: Engine) -> None:
    # Only a resend right after a reply-less turn is a retry; repeating yourself later is not.
    session_id = _create_session(client)
    _send(client, session_id, "hello")
    _send(client, session_id, "hello")

    assert _pairs(db_engine, session_id) == [
        ("assistant", GREETING),
        ("user", "hello"),
        ("assistant", CANNED_REPLY),
        ("user", "hello"),
        ("assistant", CANNED_REPLY),
    ]


def test_dedupe_compares_the_exact_text(client: TestClient, db_engine: Engine) -> None:
    session_id = _create_session(client)
    _use_provider(client, RaisingProvider())
    _send(client, session_id, "hello")
    _send(client, session_id, "Hello")

    assert [c for r, c in _pairs(db_engine, session_id) if r == "user"] == ["hello", "Hello"]


def test_dedupe_only_looks_at_its_own_session(client: TestClient, db_engine: Engine) -> None:
    first = _create_session(client)
    second = _create_session(client)
    _use_provider(client, RaisingProvider())
    _send(client, first, "same text")

    _send(client, second, "same text")

    assert _pairs(db_engine, second) == [("assistant", GREETING), ("user", "same text")]


def test_is_retry_helper(db: Session) -> None:
    session_id = repo.create_session(db).id
    assert turn.is_retry(db, session_id, "hi") is False  # no messages at all

    repo.add_message(db, session_id, "user", "hi")
    assert turn.is_retry(db, session_id, "hi") is True
    assert turn.is_retry(db, session_id, "bye") is False

    repo.add_message(db, session_id, "assistant", "part of a reply" + MARKER)  # stopped / dropped
    assert turn.is_retry(db, session_id, "hi") is True
    assert turn.is_retry(db, session_id, "bye") is False

    repo.add_message(db, session_id, "assistant", "hi")  # a finished reply (same text, not a user message)
    assert turn.is_retry(db, session_id, "hi") is False


def test_same_text_after_a_stopped_reply_that_saved_a_plan_is_a_new_message(db: Session) -> None:
    # A Stop after the plan was saved still leaves a finished edit: "replace [F]" again is new.
    session_id = repo.create_session(db).id
    repo.add_message(db, session_id, "user", "replace [F]")
    repo.add_message(db, session_id, "assistant", MARKER.strip(), itinerary_version=2)

    assert turn.is_retry(db, session_id, "replace [F]") is False


def test_retry_after_the_client_dropped_mid_reply_saves_the_message_once(
    db: Session, db_engine: Engine
) -> None:
    # The connection drops after some text: the server keeps the partial with the stopped marker,
    # and the Retry that follows must not save the user message a second time.
    session_id = repo.create_session(db).id

    async def drop_after_a_token() -> None:
        gen = turn.run_turn(db, session_id, "hi", FakeProvider())
        async for event in gen:
            if event["event"] == "token":
                break
        await gen.aclose()  # type: ignore[attr-defined]

    asyncio.run(drop_after_a_token())

    async def drain() -> list[str]:
        return [e["event"] async for e in turn.run_turn(db, session_id, "hi", FakeProvider())]

    assert asyncio.run(drain())[-1] == "done"
    pairs = _pairs(db_engine, session_id)
    assert [r for r, _ in pairs] == ["user", "assistant", "assistant"]
    assert pairs[0] == ("user", "hi")
    assert pairs[1][1].endswith(MARKER)
    assert pairs[2] == ("assistant", CANNED_REPLY)


def test_retry_after_a_stop_before_any_text_saves_the_message_once(
    db: Session, db_engine: Engine
) -> None:
    session_id = repo.create_session(db).id

    async def stop_after_start() -> None:
        gen = turn.run_turn(db, session_id, "hi", FakeProvider())
        assert (await gen.__anext__())["event"] == "message_start"
        await gen.aclose()

    asyncio.run(stop_after_start())

    async def drain() -> list[str]:
        return [e["event"] async for e in turn.run_turn(db, session_id, "hi", FakeProvider())]

    assert asyncio.run(drain())[-1] == "done"
    assert _pairs(db_engine, session_id) == [("user", "hi"), ("assistant", CANNED_REPLY)]


# --- a failed reply isn't saved --------------------------------------------------------------


def test_reply_failing_mid_stream_is_not_saved(client: TestClient, db_engine: Engine) -> None:
    _use_provider(client, RaisingProvider(chunks_before=2))
    session_id = _create_session(client)

    events = _send(client, session_id, "Hello")

    assert [n for n, _ in events if n == "token"] == ["token", "token"]
    assert events[-1][0] == "error"
    assert _pairs(db_engine, session_id) == [("assistant", GREETING), ("user", "Hello")]
    body = client.get(f"/api/sessions/{session_id}").json()
    assert all("part0" not in m["content"] for m in body["messages"])


def test_failed_reply_message_id_is_never_saved(client: TestClient, db_engine: Engine) -> None:
    _use_provider(client, RaisingProvider(chunks_before=1))
    session_id = _create_session(client)

    events = _send(client, session_id, "Hello")

    announced = events[0][1]["message_id"]
    assert announced not in [m.id for m in _stored(db_engine, session_id)]


# --- Stop before any text --------------------------------------------------------------------


def test_stop_before_any_text_on_generate_saves_nothing(db: Session, db_engine: Engine) -> None:
    session_id = repo.create_session(db).id

    async def stop_after_start() -> None:
        gen = turn.run_turn(db, session_id, None, FakeProvider())
        assert (await gen.__anext__())["event"] == "message_start"
        await gen.aclose()

    asyncio.run(stop_after_start())

    assert _stored(db_engine, session_id) == []
    assert _versions(db_engine, session_id) == []


def test_stop_after_the_plan_is_saved_keeps_a_reply_with_the_version(
    db: Session, db_engine: Engine
) -> None:
    # D19: every plan version keeps its chat message, even with no summary text yet.
    session_id = repo.create_session(db).id

    async def stop_after_itinerary() -> list[str]:
        names: list[str] = []
        gen = turn.run_turn(db, session_id, None, FakeProvider())
        async for event in gen:
            names.append(event["event"])
            if event["event"] == "itinerary":
                break
        await gen.aclose()  # type: ignore[attr-defined]
        return names

    names = asyncio.run(stop_after_itinerary())

    assert "token" not in names
    assert [v.version for v in _versions(db_engine, session_id)] == [1]
    stored = _stored(db_engine, session_id)
    assert len(stored) == 1
    assert stored[0].role == "assistant"
    assert stored[0].itinerary_version == 1
    assert stored[0].content.endswith(MARKER.strip())


# --- a failed plan keeps the old one, with a friendly text -----------------------------------


class ComposeCutOffFake(FakeProvider):
    """The planner's compose reply hits the output limit (D33)."""

    async def complete_json(self, system: str, messages: list[Message], schema: Any) -> Any:
        raise ReplyCutOff("length")


class ComposeCrashesFake(FakeProvider):
    async def complete_json(self, system: str, messages: list[Message], schema: Any) -> Any:
        raise RuntimeError("network dropped")


def test_failed_regenerate_keeps_the_old_plan_and_says_so(
    client: TestClient, db_engine: Engine
) -> None:
    session_id = _create_session(client)
    _generate(client, session_id)
    before = _versions(db_engine, session_id)[0].model_dump(mode="json")

    _use_provider(client, ComposeCrashesFake())
    events = _generate(client, session_id)

    assert events[-1] == ("error", {"message": turn.PLAN_ERROR_MESSAGE, "retryable": True})
    assert "unchanged" in turn.PLAN_ERROR_MESSAGE
    assert [v.model_dump(mode="json") for v in _versions(db_engine, session_id)] == [before]
    assert client.get(f"/api/sessions/{session_id}").json()["itinerary"]["version"] == 1


def test_cut_off_plan_gets_the_too_long_text(client: TestClient, db_engine: Engine) -> None:
    _use_provider(client, ComposeCutOffFake())
    session_id = _create_session(client)

    data = _generate(client, session_id)[-1]

    assert data[0] == "error"
    assert data[1]["message"] == turn.PLAN_TOO_LONG_MESSAGE
    assert "length" not in data[1]["message"]
    assert _versions(db_engine, session_id) == []


def test_error_text_picks_a_friendly_message() -> None:
    assert turn.error_text(RuntimeError("x"), planning=False) == turn.ERROR_MESSAGE
    assert turn.error_text(ReplyCutOff("x"), planning=False) == turn.ERROR_MESSAGE
    assert turn.error_text(RuntimeError("x"), planning=True) == turn.PLAN_ERROR_MESSAGE
    assert turn.error_text(ReplyCutOff("x"), planning=True) == turn.PLAN_TOO_LONG_MESSAGE


# --- run_planner raising outside tool_turn closes its Choosing line --------------------------


class OneCallPlanner(FakeProvider):
    """Asks for one search_places call in the first round, then for nothing."""

    def __init__(self) -> None:
        super().__init__()
        self.turns = 0

    async def tool_turn(
        self, system: str, messages: list[Message], rounds: list[ToolRound], tools: list[ToolSpec]
    ) -> list[ToolCall]:
        self.turns += 1
        if self.turns > 1:
            return []
        return [ToolCall(id="c1", name="search_places", arguments={"city": "San Jose, CA"})]


def _profile() -> TripProfile:
    return TripProfile(
        budget_level="budget", cities=["San Jose, CA"], travelers=1,
        start_date=date(2027, 3, 5), end_date=date(2027, 3, 7), interests=["food"],
    )


def _break_numbering(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("numbering broke")

    monkeypatch.setattr(planner, "number_items", broken)


def test_planner_raising_after_tools_ends_choosing_in_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _break_numbering(monkeypatch)
    statuses: list[dict[str, str]] = []

    async def collect() -> None:
        request: list[Message] = [{"role": "user", "content": planner.PLANNER_REQUEST}]
        async for item in run_planner(OneCallPlanner(), _profile(), request, today=date(2027, 2, 1)):
            assert not isinstance(item, list), "no findings after a failure"
            statuses.append(json.loads(item["data"]))

    with pytest.raises(RuntimeError, match="numbering broke"):
        asyncio.run(asyncio.wait_for(collect(), timeout=30))

    choosing = [s["state"] for s in statuses if s["label"] == CHOOSING_LABEL]
    assert choosing == ["start", "error"]
    assert statuses[-1] == {"label": CHOOSING_LABEL, "state": "error"}
    # Every line that started got its end/error.
    for label in {s["label"] for s in statuses}:
        states = [s["state"] for s in statuses if s["label"] == label]
        assert states[0] == "start" and len(states) == 2 and states[1] in ("end", "error")


def test_generate_with_a_raising_planner_closes_choosing_and_keeps_old_plan(
    client: TestClient, db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = _create_session(client)
    _generate(client, session_id)  # v1
    _break_numbering(monkeypatch)
    _use_provider(client, OneCallPlanner())

    events = _generate(client, session_id)

    choosing = [d["state"] for n, d in events if n == "status" and d["label"] == CHOOSING_LABEL]
    assert choosing == ["start", "error"]
    assert events[-1] == ("error", {"message": turn.PLAN_ERROR_MESSAGE, "retryable": True})
    assert "itinerary" not in [n for n, _ in events]
    assert [v.version for v in _versions(db_engine, session_id)] == [1]
