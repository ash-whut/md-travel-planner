"""Step 23: POST /api/sessions/{id}/generate and "make the plan" from chat (contracts §4, §5).

Specified by plan step 23: SSE order (`itinerary` before `done`); v1 saved; status `planned`; on
failure no version is saved and `error` is emitted. Contracts §5:
`message_start → [profile] → status… → itinerary → token… → done`; the summary message gets
`itinerary_version`; `/generate` saves no user message; a failed generation is `status` with
state "error", then `error`. No network: FakeProvider + recorded JSON + a temp DB.
"""

import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session

from app.api.chat import get_llm
from app.db import repo
from app.db.tables import MessageRow
from app.llm.base import Message
from app.agent import turn
from app.llm.fake_provider import (
    CANNED_REPLY,
    SUMMARY_PHRASE,
    SUMMARY_REPLY,
    FakeProvider,
    load_fake_data,
)
from app.schemas.itinerary import Itinerary

GREETING = "Hi, where do you want to go?"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

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


def _names(events: list[Event]) -> list[str]:
    return [name for name, _ in events]


def _create_session(client: TestClient) -> str:
    response = client.post("/api/sessions")
    assert response.status_code == 200
    return response.json()["id"]


def _generate(client: TestClient, session_id: str) -> list[Event]:
    response = client.post(f"/api/sessions/{session_id}/generate", json={})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    return _parse_sse(response.text)


def _send(client: TestClient, session_id: str, content: str) -> list[Event]:
    response = client.post(f"/api/sessions/{session_id}/messages", json={"content": content})
    assert response.status_code == 200
    return _parse_sse(response.text)


def _messages(engine: Engine, session_id: str) -> list[MessageRow]:
    with Session(engine) as db:
        return repo.list_messages(db, session_id)


def _versions(engine: Engine, session_id: str) -> list[Itinerary]:
    with Session(engine) as db:
        return repo.list_itineraries(db, session_id)


def _session_status(engine: Engine, session_id: str) -> str:
    with Session(engine) as db:
        row = repo.get_session(db, session_id)
        assert row is not None
        return row.status


def _bad_draft() -> dict[str, Any]:
    # Parses as a draft, but postprocess rejects it (see test_pipeline.py).
    return json.loads((FIXTURES / "draft_bad.json").read_text(encoding="utf-8"))


def _good_draft() -> dict[str, Any]:
    return load_fake_data("draft_sanjose_v1")


def test_fake_summary_phrase_matches_the_turn_summary_request() -> None:
    assert SUMMARY_PHRASE in turn.SUMMARY_REQUEST.lower()


def _use_provider(client: TestClient, provider: Any) -> None:
    client.app.dependency_overrides[get_llm] = lambda: provider  # type: ignore[attr-defined]


def _failing_provider() -> FakeProvider:
    # Bad on the first try and on the repair try → the compose fails.
    return FakeProvider(drafts=[_bad_draft(), _bad_draft()])


class RecordingFake(FakeProvider):
    """FakeProvider that records the system text of every stream_text call."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.systems: list[str] = []

    async def stream_text(self, system: str, messages: list[Message]) -> AsyncIterator[str]:
        self.systems.append(system)
        async for chunk in super().stream_text(system, messages):
            yield chunk


def _assert_generation_shape(names: list[str], *, with_profile: bool) -> None:
    """message_start → [profile] → status… → itinerary → token… → done."""
    assert names[0] == "message_start"
    rest = names[1:]
    if with_profile:
        assert rest[0] == "profile"
        rest = rest[1:]
    else:
        assert "profile" not in rest
    i = rest.index("itinerary")
    assert i >= 1 and set(rest[:i]) == {"status"}
    assert rest[-1] == "done"
    tokens = rest[i + 1:-1]
    assert tokens and set(tokens) == {"token"}
    assert names.count("itinerary") == 1
    assert "error" not in names


# --- Generate button: SSE order -------------------------------------------------------------


def test_generate_event_order(client: TestClient) -> None:
    session_id = _create_session(client)

    names = _names(_generate(client, session_id))

    _assert_generation_shape(names, with_profile=False)
    assert names.index("itinerary") < names.index("done")


def test_generate_status_events_start_then_end_with_drafting_label(client: TestClient) -> None:
    session_id = _create_session(client)

    statuses = [data for name, data in _generate(client, session_id) if name == "status"]

    assert all(set(s) == {"label", "state"} for s in statuses)
    assert statuses[0] == {"label": "Drafting your plan…", "state": "start"}
    assert statuses[-1]["state"] == "end"
    assert all(s["state"] in ("start", "end") for s in statuses)


def test_generate_message_start_and_done_share_an_id(client: TestClient) -> None:
    session_id = _create_session(client)

    events = _generate(client, session_id)

    assert events[0][1]["message_id"] == events[-1][1]["message_id"]
    assert uuid.UUID(events[-1][1]["message_id"]).version == 4


def test_generate_itinerary_event_is_a_valid_v1_plan(client: TestClient) -> None:
    session_id = _create_session(client)

    data = next(d for name, d in _generate(client, session_id) if name == "itinerary")

    plan = Itinerary.model_validate(data)
    assert plan.version == 1
    tags = [stop.tag for stop in plan.stops]
    assert tags == [chr(ord("A") + i) for i in range(len(tags))]
    # Tools don't exist yet: no coordinates, no weather, no bookings from the LLM.
    assert all(stop.lat is None and stop.lng is None for stop in plan.stops)


# --- Generate button: persistence -----------------------------------------------------------


def test_generate_saves_v1_and_sets_status_planned(
    client: TestClient, db_engine: Engine
) -> None:
    session_id = _create_session(client)
    assert _session_status(db_engine, session_id) == "intake"

    events = _generate(client, session_id)

    versions = _versions(db_engine, session_id)
    assert [v.version for v in versions] == [1]
    assert _session_status(db_engine, session_id) == "planned"
    streamed = next(d for name, d in events if name == "itinerary")
    assert versions[0].model_dump(mode="json") == streamed


def test_generate_saves_no_user_message_and_a_summary_with_itinerary_version(
    client: TestClient, db_engine: Engine
) -> None:
    session_id = _create_session(client)

    events = _generate(client, session_id)

    stored = _messages(db_engine, session_id)
    assert [m.role for m in stored] == ["assistant", "assistant"]
    assert stored[0].content == GREETING and stored[0].itinerary_version is None
    summary = stored[1]
    assert summary.id == events[-1][1]["message_id"]
    assert summary.itinerary_version == 1
    streamed = "".join(d["text"] for name, d in events if name == "token")
    assert summary.content == streamed == SUMMARY_REPLY


def test_get_session_after_generate_shows_plan_and_status(client: TestClient) -> None:
    session_id = _create_session(client)
    _generate(client, session_id)

    body = client.get(f"/api/sessions/{session_id}").json()

    assert body["status"] == "planned"
    assert body["itinerary"]["version"] == 1
    assert body["messages"][-1]["itinerary_version"] == 1


def test_second_generate_saves_v2(client: TestClient, db_engine: Engine) -> None:
    session_id = _create_session(client)
    _generate(client, session_id)

    events = _generate(client, session_id)

    assert next(d for n, d in events if n == "itinerary")["version"] == 2
    assert [v.version for v in _versions(db_engine, session_id)] == [1, 2]
    assert [m.itinerary_version for m in _messages(db_engine, session_id)] == [None, 1, 2]


def test_generate_succeeds_after_one_repair(client: TestClient, db_engine: Engine) -> None:
    _use_provider(client, FakeProvider(drafts=[_bad_draft(), _good_draft()]))
    session_id = _create_session(client)

    names = _names(_generate(client, session_id))

    _assert_generation_shape(names, with_profile=False)
    assert [v.version for v in _versions(db_engine, session_id)] == [1]


def test_generate_only_touches_its_own_session(client: TestClient, db_engine: Engine) -> None:
    first = _create_session(client)
    second = _create_session(client)

    _generate(client, second)

    assert _versions(db_engine, first) == []
    assert _session_status(db_engine, first) == "intake"
    assert [m.content for m in _messages(db_engine, first)] == [GREETING]


# --- Generate button: failure ---------------------------------------------------------------


def test_failed_generate_emits_status_error_then_error(client: TestClient) -> None:
    _use_provider(client, _failing_provider())
    session_id = _create_session(client)

    events = _generate(client, session_id)
    names = _names(events)

    assert names[0] == "message_start"
    assert names[-1] == "error"
    assert names.count("error") == 1
    assert "itinerary" not in names and "done" not in names and "token" not in names
    status_before_error = events[-2]
    assert status_before_error[0] == "status"
    assert status_before_error[1]["state"] == "error"


def test_failed_generate_error_is_friendly(client: TestClient) -> None:
    _use_provider(client, _failing_provider())
    session_id = _create_session(client)

    data = _generate(client, session_id)[-1][1]

    assert set(data) == {"message", "retryable"}
    assert "unchanged" in data["message"].lower()
    assert isinstance(data["retryable"], bool)
    assert "ComposeError" not in data["message"]
    assert "could not be made:" not in data["message"]  # the raw rule errors don't leak


def test_failed_generate_saves_nothing(client: TestClient, db_engine: Engine) -> None:
    _use_provider(client, _failing_provider())
    session_id = _create_session(client)

    _generate(client, session_id)

    assert _versions(db_engine, session_id) == []
    assert _session_status(db_engine, session_id) == "intake"
    assert [m.content for m in _messages(db_engine, session_id)] == [GREETING]
    assert client.get(f"/api/sessions/{session_id}").json()["itinerary"] is None


def test_failed_generate_keeps_the_previous_plan(client: TestClient, db_engine: Engine) -> None:
    session_id = _create_session(client)
    _generate(client, session_id)
    before = _versions(db_engine, session_id)[0].model_dump(mode="json")

    _use_provider(client, _failing_provider())
    events = _generate(client, session_id)

    assert events[-1][0] == "error"
    versions = _versions(db_engine, session_id)
    assert [v.version for v in versions] == [1]
    assert versions[0].model_dump(mode="json") == before
    assert _session_status(db_engine, session_id) == "planned"
    assert client.get(f"/api/sessions/{session_id}").json()["itinerary"]["version"] == 1
    assert [m.itinerary_version for m in _messages(db_engine, session_id)] == [None, 1]


def test_session_can_generate_after_a_failure(client: TestClient, db_engine: Engine) -> None:
    session_id = _create_session(client)
    _use_provider(client, _failing_provider())
    _generate(client, session_id)

    client.app.dependency_overrides.pop(get_llm)  # type: ignore[attr-defined]
    events = _generate(client, session_id)

    assert events[-1][0] == "done"
    assert [v.version for v in _versions(db_engine, session_id)] == [1]


# --- Generate button: unknown session -------------------------------------------------------


@pytest.mark.parametrize("session_id", [str(uuid.uuid4()), "not-a-uuid"])
def test_generate_unknown_session_returns_404(
    client: TestClient, db_engine: Engine, session_id: str
) -> None:
    provider = RecordingFake()
    _use_provider(client, provider)

    response = client.post(f"/api/sessions/{session_id}/generate", json={})

    assert response.status_code == 404
    assert response.json() == {"detail": "Session not found"}
    assert provider.systems == []
    assert _versions(db_engine, session_id) == []


# --- "make the plan" from chat --------------------------------------------------------------


def test_chat_make_the_plan_produces_a_plan(client: TestClient, db_engine: Engine) -> None:
    session_id = _create_session(client)

    events = _send(client, session_id, "Just make the plan")
    names = _names(events)

    _assert_generation_shape(names, with_profile=False)
    assert [v.version for v in _versions(db_engine, session_id)] == [1]
    assert _session_status(db_engine, session_id) == "planned"
    stored = _messages(db_engine, session_id)
    assert [(m.role, m.content, m.itinerary_version) for m in stored] == [
        ("assistant", GREETING, None),
        ("user", "Just make the plan", None),
        ("assistant", SUMMARY_REPLY, 1),
    ]
    assert stored[-1].id == events[-1][1]["message_id"]


def test_chat_generate_with_profile_change_sends_profile_first(client: TestClient) -> None:
    session_id = _create_session(client)

    events = _send(client, session_id, "San Jose, just me. Make the plan please")

    _assert_generation_shape(_names(events), with_profile=True)
    assert events[1][1]["cities"] == ["San Jose, CA"]


@pytest.mark.parametrize("content", ["generate", "Make a plan", "make my plan"])
def test_chat_generate_phrases(client: TestClient, db_engine: Engine, content: str) -> None:
    session_id = _create_session(client)

    names = _names(_send(client, session_id, content))

    assert "itinerary" in names and names[-1] == "done"
    assert [v.version for v in _versions(db_engine, session_id)] == [1]


def test_plain_chat_makes_no_plan(client: TestClient, db_engine: Engine) -> None:
    session_id = _create_session(client)

    names = _names(_send(client, session_id, "Hello there"))

    assert "itinerary" not in names and "status" not in names
    assert _versions(db_engine, session_id) == []
    assert _session_status(db_engine, session_id) == "intake"
    assert _messages(db_engine, session_id)[-1].itinerary_version is None
    assert _messages(db_engine, session_id)[-1].content == CANNED_REPLY


def test_failed_chat_generate_keeps_user_message_and_saves_no_plan(
    client: TestClient, db_engine: Engine
) -> None:
    _use_provider(client, _failing_provider())
    session_id = _create_session(client)

    events = _send(client, session_id, "make the plan")
    names = _names(events)

    assert names[0] == "message_start" and names[-1] == "error"
    assert events[-2][0] == "status" and events[-2][1]["state"] == "error"
    assert "itinerary" not in names and "done" not in names
    assert _versions(db_engine, session_id) == []
    assert _session_status(db_engine, session_id) == "intake"
    assert [(m.role, m.content) for m in _messages(db_engine, session_id)] == [
        ("assistant", GREETING),
        ("user", "make the plan"),
    ]


# --- the current plan is in the per-turn context --------------------------------------------


def test_context_says_no_plan_before_generation(client: TestClient) -> None:
    provider = RecordingFake()
    _use_provider(client, provider)
    session_id = _create_session(client)

    _send(client, session_id, "Hello")

    assert "## Current plan\nNo plan yet." in provider.systems[-1]


def test_context_includes_the_plan_after_generation(client: TestClient) -> None:
    provider = RecordingFake()
    _use_provider(client, provider)
    session_id = _create_session(client)
    _generate(client, session_id)

    _send(client, session_id, "What's on day 1?")

    system = provider.systems[-1]
    assert "## Current plan (version 1)" in system
    assert "No plan yet." not in system
    assert "[A]" in system
    # The summary reply after generation is also written with the new plan in context.
    assert "## Current plan (version 1)" in provider.systems[0]


# --- failures outside compose ---------------------------------------------------------------


class SummaryFailsFake(FakeProvider):
    """Makes the plan, then fails while streaming the summary (after one chunk)."""

    async def stream_text(self, system: str, messages: list[Message]) -> AsyncIterator[str]:
        yield "Your plan "
        raise RuntimeError("network dropped")


class ComposeCrashesFake(FakeProvider):
    """The compose call fails with a non-ComposeError (e.g. a network error)."""

    async def complete_json(self, system: str, messages: list[Message], schema: Any) -> Any:
        raise RuntimeError("network dropped")


def test_summary_failure_after_save_keeps_a_message_with_the_version(
    client: TestClient, db_engine: Engine
) -> None:
    _use_provider(client, SummaryFailsFake())
    session_id = _create_session(client)

    events = _generate(client, session_id)

    assert _names(events)[-1] == "done"
    assert [v.version for v in _versions(db_engine, session_id)] == [1]
    summary = _messages(db_engine, session_id)[-1]
    assert summary.itinerary_version == 1
    assert summary.content == "".join(d["text"] for name, d in events if name == "token")
    assert summary.content.endswith(turn.PLAN_READY_FALLBACK)


def test_failure_right_after_save_still_takes_the_plan_saved_path(
    client: TestClient, db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_read(db: Session, session_id: str) -> Itinerary | None:
        raise RuntimeError("database hiccup")

    monkeypatch.setattr(repo, "get_latest_itinerary", broken_read)
    session_id = _create_session(client)

    events = _generate(client, session_id)
    names = _names(events)

    assert "itinerary" in names and names[-1] == "done" and "error" not in names
    assert [v.version for v in _versions(db_engine, session_id)] == [1]
    summary = _messages(db_engine, session_id)[-1]
    assert summary.itinerary_version == 1
    assert summary.content == turn.PLAN_READY_FALLBACK


def test_failed_save_emits_status_error_not_end(
    client: TestClient, db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_save(db: Session, session_id: str, itinerary: Itinerary) -> Itinerary:
        raise RuntimeError("database hiccup")

    monkeypatch.setattr(repo, "save_itinerary", broken_save)
    session_id = _create_session(client)

    events = _generate(client, session_id)
    states = [data["state"] for name, data in events if name == "status"]

    assert states == ["start", "error"]
    assert events[-1] == ("error", {"message": turn.PLAN_ERROR_MESSAGE, "retryable": True})
    assert _versions(db_engine, session_id) == []


def test_non_compose_generation_failure_uses_the_plan_error(
    client: TestClient, db_engine: Engine
) -> None:
    _use_provider(client, ComposeCrashesFake())
    session_id = _create_session(client)

    events = _generate(client, session_id)

    assert events[-1] == ("error", {"message": turn.PLAN_ERROR_MESSAGE, "retryable": True})
    assert _versions(db_engine, session_id) == []
