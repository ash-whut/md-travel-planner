"""Step 15: Stop. When the client stops the stream, the turn saves the partial reply with
" *(stopped)*" appended (contracts §5). Async code is driven with asyncio.run (no pytest-asyncio)."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlmodel import Session

from app.agent import turn
from app.db import repo
from app.db.tables import MessageRow
from app.llm.base import Message
from app.llm.fake_provider import CANNED_REPLY, FakeProvider

MARKER = " *(stopped)*"  # the exact text from contracts §5


class ChunkProvider:
    """Streams the given chunks; with `hang=True` it then waits forever (a slow LLM)."""

    name = "chunks"

    def __init__(self, chunks: list[str], hang: bool = False) -> None:
        self.chunks = chunks
        self.hang = hang
        self.calls: list[list[Message]] = []

    async def stream_text(self, system: str, messages: list[Message]) -> AsyncIterator[str]:
        self.calls.append([dict(m) for m in messages])  # type: ignore[misc]
        for chunk in self.chunks:
            yield chunk
        if self.hang:
            await asyncio.Event().wait()

    async def complete_json(self, system: str, messages: list[Message], schema: type[BaseModel]) -> Any:
        raise NotImplementedError


def _stored(engine: Engine, session_id: str) -> list[MessageRow]:
    with Session(engine) as db:
        return repo.list_messages(db, session_id)


def _new_session(db: Session) -> str:
    return repo.create_session(db).id


async def _take_then_close(gen: AsyncIterator[dict[str, str]], n_tokens: int) -> list[dict[str, str]]:
    """Read message_start + `n_tokens` tokens, then close the generator like a client Stop."""
    seen: list[dict[str, str]] = []
    async for event in gen:
        seen.append(event)
        if sum(1 for e in seen if e["event"] == "token") >= n_tokens:
            break
    await gen.aclose()  # type: ignore[attr-defined]
    return seen


def _message_id(events: list[dict[str, str]]) -> str:
    start = events[0]
    assert start["event"] == "message_start"
    return json.loads(start["data"])["message_id"]


# --- closing the turn generator (client disconnect / Stop) ----------------------------------


def test_closing_early_saves_partial_text_plus_marker(db: Session, db_engine: Engine) -> None:
    session_id = _new_session(db)
    llm = ChunkProvider(["Austin ", "is ", "great ", "in ", "spring."])

    events = asyncio.run(_take_then_close(turn.run_turn(db, session_id, "Austin?", llm), 2))

    stored = _stored(db_engine, session_id)
    assert [(m.role, m.content) for m in stored] == [
        ("user", "Austin?"),
        ("assistant", "Austin is" + MARKER),
    ]
    streamed = "".join(json.loads(e["data"])["text"] for e in events if e["event"] == "token")
    assert stored[-1].content == streamed.rstrip() + MARKER


def test_stopped_message_uses_the_announced_message_id(db: Session, db_engine: Engine) -> None:
    session_id = _new_session(db)
    llm = ChunkProvider(["one", " two", " three"])

    events = asyncio.run(_take_then_close(turn.run_turn(db, session_id, "hi", llm), 1))

    stored = _stored(db_engine, session_id)
    assert stored[-1].id == _message_id(events)
    assert stored[-1].content == "one" + MARKER


def test_closing_early_with_the_fake_provider(db: Session, db_engine: Engine) -> None:
    session_id = _new_session(db)

    events = asyncio.run(_take_then_close(turn.run_turn(db, session_id, "hi", FakeProvider()), 2))

    content = _stored(db_engine, session_id)[-1].content
    streamed = "".join(json.loads(e["data"])["text"] for e in events if e["event"] == "token")
    assert content == streamed.rstrip() + MARKER
    assert content != CANNED_REPLY
    assert CANNED_REPLY.startswith(streamed)


def test_closing_before_any_token_saves_just_the_marker(db: Session, db_engine: Engine) -> None:
    session_id = _new_session(db)
    llm = ChunkProvider(["never", " sent"])

    async def stop_after_start() -> None:
        gen = turn.run_turn(db, session_id, "hi", llm)
        first = await gen.__anext__()
        assert first["event"] == "message_start"
        await gen.aclose()

    asyncio.run(stop_after_start())

    stored = _stored(db_engine, session_id)
    assert [m.role for m in stored] == ["user", "assistant"]
    assert stored[-1].content == MARKER


def test_stopped_turn_sends_no_done_or_error(db: Session) -> None:
    session_id = _new_session(db)
    llm = ChunkProvider(["a", "b", "c"])

    events = asyncio.run(_take_then_close(turn.run_turn(db, session_id, "hi", llm), 2))

    assert [e["event"] for e in events] == ["message_start", "token", "token"]


def test_stopped_reply_is_saved_once(db: Session, db_engine: Engine) -> None:
    session_id = _new_session(db)
    llm = ChunkProvider(["a", "b", "c"])

    asyncio.run(_take_then_close(turn.run_turn(db, session_id, "hi", llm), 2))

    assistant = [m for m in _stored(db_engine, session_id) if m.role == "assistant"]
    assert len(assistant) == 1


# --- cancelling the task that runs the turn --------------------------------------------------


def test_cancelling_the_turn_task_saves_partial_text_plus_marker(
    db: Session, db_engine: Engine
) -> None:
    session_id = _new_session(db)
    llm = ChunkProvider(["Slow ", "reply"], hang=True)  # waits forever after two chunks

    async def run_and_cancel() -> list[dict[str, str]]:
        seen: list[dict[str, str]] = []
        two_tokens = asyncio.Event()

        async def consume() -> None:
            async for event in turn.run_turn(db, session_id, "hi", llm):
                seen.append(event)
                if sum(1 for e in seen if e["event"] == "token") == 2:
                    two_tokens.set()

        task = asyncio.create_task(consume())
        await two_tokens.wait()
        await asyncio.sleep(0)  # let the turn reach the hanging await
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return seen

    events = asyncio.run(run_and_cancel())

    stored = _stored(db_engine, session_id)
    assert [(m.role, m.content) for m in stored] == [
        ("user", "hi"),
        ("assistant", "Slow reply" + MARKER),
    ]
    assert stored[-1].id == _message_id(events)


# --- the normal path is unchanged -----------------------------------------------------------


def test_a_finished_turn_has_no_marker(db: Session, db_engine: Engine) -> None:
    session_id = _new_session(db)
    llm = ChunkProvider(["All ", "done."])

    async def drain() -> list[str]:
        return [e["event"] async for e in turn.run_turn(db, session_id, "hi", llm)]

    names = asyncio.run(drain())

    assert names[-1] == "done"
    assert _stored(db_engine, session_id)[-1].content == "All done."


def test_next_turn_sees_the_stopped_reply_in_history(db: Session, db_engine: Engine) -> None:
    session_id = _new_session(db)
    asyncio.run(_take_then_close(turn.run_turn(db, session_id, "first", ChunkProvider(["Half", " way"])), 1))

    llm = ChunkProvider(["Sure."])

    async def drain() -> list[str]:
        return [e["event"] async for e in turn.run_turn(db, session_id, "second", llm)]

    assert asyncio.run(drain())[-1] == "done"
    history = llm.calls[0]
    assert {"role": "assistant", "content": "Half" + MARKER} in history
    assert history[-1] == {"role": "user", "content": "second"}
    assert [m.content for m in _stored(db_engine, session_id)] == [
        "first", "Half" + MARKER, "second", "Sure.",
    ]


def test_marker_constant_matches_the_contract() -> None:
    assert turn.STOPPED_MARKER == MARKER
