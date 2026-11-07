"""Step 16: the understand step, profile merge, missing_required and the `profile` SSE event.

Specified by plan step 16, contracts §2.1 (TripProfile, missing_required), §2.4 (TurnAnalysis),
§5 (`profile` event "the profile changed"), spec F2 (required fields) and decisions D17.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError
from sqlalchemy.engine import Engine
from sqlmodel import Session

from app.agent import understand
from app.api.chat import get_llm
from app.db import repo
from app.llm.base import Message
from app.llm.fake_provider import CANNED_REPLY, FakeProvider
from app.schemas.profile import TripProfile, missing_required
from app.schemas.turn import ProfileUpdates, TurnAnalysis

ALL_REQUIRED = {"destination", "dates", "origin", "travelers", "interests"}
FIXTURES = Path(__file__).resolve().parents[2] / "frontend" / "src" / "fixtures"

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


def _names(events: list[Event]) -> list[str]:
    return [name for name, _ in events]


def _profile_events(events: list[Event]) -> list[dict[str, Any]]:
    return [data for name, data in events if name == "profile"]


def _stored_profile(engine: Engine, session_id: str) -> dict[str, Any]:
    with Session(engine) as db:
        row = repo.get_session(db, session_id)
        assert row is not None
        return row.trip_profile


def _use_provider(client: TestClient, provider: Any) -> None:
    client.app.dependency_overrides[get_llm] = lambda: provider  # type: ignore[attr-defined]


def _full_profile(**overrides: Any) -> TripProfile:
    data: dict[str, Any] = json.loads((FIXTURES / "sanjose-profile.json").read_text("utf-8"))
    data.update(overrides)
    return TripProfile.model_validate(data)


class ScriptedProvider:
    """Returns a fixed TurnAnalysis per call (in order) and records every call."""

    name = "scripted"

    def __init__(self, analyses: list[dict[str, Any]], reply: str = "ok") -> None:
        self.analyses = list(analyses)
        self.reply = reply
        self.json_calls: list[tuple[str, list[Message], type[BaseModel]]] = []
        self.stream_systems: list[str] = []

    async def stream_text(self, system: str, messages: list[Message]) -> AsyncIterator[str]:
        self.stream_systems.append(system)
        yield self.reply

    async def complete_json(self, system: str, messages: list[Message], schema: type[BaseModel]) -> Any:
        self.json_calls.append((system, [dict(m) for m in messages], schema))  # type: ignore[misc]
        return schema.model_validate(self.analyses.pop(0))


class FailingUnderstandProvider:
    """complete_json fails, stream_text works (D17: the turn continues as plain chat)."""

    name = "failing-understand"

    async def stream_text(self, system: str, messages: list[Message]) -> AsyncIterator[str]:
        yield "still "
        yield "here"

    async def complete_json(self, system: str, messages: list[Message], schema: type[BaseModel]) -> Any:
        raise RuntimeError("understand blew up")


# --- missing_required (contracts §2.1, spec F2) ---------------------------------------------


def test_missing_required_empty_profile_lists_all_five() -> None:
    assert set(missing_required(TripProfile())) == ALL_REQUIRED
    assert len(missing_required(TripProfile())) == 5


def test_missing_required_full_profile_is_empty() -> None:
    assert missing_required(_full_profile()) == []


def test_missing_required_partial_profile() -> None:
    profile = TripProfile(cities=["San Jose, CA"], origin="College Station, TX")
    assert set(missing_required(profile)) == {"dates", "travelers", "interests"}


def test_missing_required_values_are_contract_names_only() -> None:
    for profile in [TripProfile(), TripProfile(cities=["Austin, TX"]), _full_profile()]:
        assert set(missing_required(profile)) <= ALL_REQUIRED


def test_vibe_counts_as_destination() -> None:
    profile = _full_profile(cities=[], vibe="beach, ≤4h drive")
    assert missing_required(profile) == []


def test_no_city_and_no_vibe_misses_destination() -> None:
    assert missing_required(_full_profile(cities=[], vibe=None)) == ["destination"]


@pytest.mark.parametrize(
    "dates",
    [
        {"start_date": "2027-03-05", "end_date": "2027-03-07"},
        {"rough_timing": "first weekend of March", "duration_days": 3},
    ],
    ids=["exact-dates", "rough-timing-plus-length"],
)
def test_dates_known(dates: dict[str, Any]) -> None:
    no_dates = {"start_date": None, "end_date": None, "duration_days": None, "rough_timing": None}
    profile = _full_profile(**{**no_dates, **dates})
    assert "dates" not in missing_required(profile)


@pytest.mark.parametrize(
    "dates",
    [
        {},
        {"rough_timing": "sometime in March"},
        {"duration_days": 3},
        {"start_date": "2027-03-05"},
        {"end_date": "2027-03-07"},
    ],
    ids=["nothing", "rough-timing-only", "length-only", "start-only", "end-only"],
)
def test_dates_missing(dates: dict[str, Any]) -> None:
    no_dates = {"start_date": None, "end_date": None, "duration_days": None, "rough_timing": None}
    profile = _full_profile(**{**no_dates, **dates})
    assert missing_required(profile) == ["dates"]


@pytest.mark.parametrize(
    ("override", "missing"),
    [
        ({"origin": None}, "origin"),
        ({"travelers": None}, "travelers"),
        ({"interests": []}, "interests"),
    ],
)
def test_single_missing_field(override: dict[str, Any], missing: str) -> None:
    assert missing_required(_full_profile(**override)) == [missing]


def test_optional_fields_are_never_required() -> None:
    # budget_level (D17), dietary, pace, transport and notes are optional (spec F2).
    profile = _full_profile(budget_level=None, dietary=None, pace=None, transport=None, notes=None)
    assert missing_required(profile) == []


# --- TurnAnalysis schema (contracts §2.4) ---------------------------------------------------


def test_turn_analysis_parses_contract_shape() -> None:
    analysis = TurnAnalysis.model_validate(
        {
            "profile_updates": {"cities": ["San Jose, CA"], "start_date": "2027-03-05"},
            "action": "chat",
            "change_request": None,
        }
    )
    assert analysis.action == "chat"
    assert analysis.profile_updates.cities == ["San Jose, CA"]
    assert analysis.change_request is None


@pytest.mark.parametrize("action", ["chat", "generate", "edit"])
def test_turn_analysis_accepts_all_actions(action: str) -> None:
    assert TurnAnalysis.model_validate({"profile_updates": {}, "action": action}).action == action


@pytest.mark.parametrize(
    "bad",
    [
        {"profile_updates": {}, "action": "book"},
        {"profile_updates": {"travelers": 7}, "action": "chat"},
        {"profile_updates": {"cities": ["A", "B", "C"]}, "action": "chat"},
        {"profile_updates": {"budget_level": "cheap"}, "action": "chat"},
    ],
)
def test_turn_analysis_rejects_out_of_contract_values(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        TurnAnalysis.model_validate(bad)


def test_profile_updates_have_no_missing_required() -> None:
    # The server computes missing_required; the LLM can't set it.
    assert "missing_required" not in ProfileUpdates.model_fields


# --- merge rules ----------------------------------------------------------------------------


def test_merge_applies_only_given_fields() -> None:
    old = TripProfile(cities=["San Jose, CA"], origin="College Station, TX", travelers=2)

    merged = understand.merge_profile(old, ProfileUpdates(travelers=1))

    assert merged.travelers == 1
    assert merged.cities == ["San Jose, CA"]
    assert merged.origin == "College Station, TX"


def test_merge_null_fields_do_not_clear_values() -> None:
    old = TripProfile(origin="College Station, TX", dietary="vegan")

    merged = understand.merge_profile(
        old, ProfileUpdates.model_validate({"origin": None, "dietary": None, "pace": "relaxed"})
    )

    assert merged.origin == "College Station, TX"
    assert merged.dietary == "vegan"
    assert merged.pace == "relaxed"


def test_merge_empty_updates_keeps_profile() -> None:
    old = _full_profile()

    merged = understand.merge_profile(old, ProfileUpdates())

    assert merged.model_dump(exclude={"missing_required"}) == old.model_dump(
        exclude={"missing_required"}
    )


def test_merge_replaces_lists() -> None:
    old = TripProfile(cities=["San Jose, CA"], interests=["tech", "food"])

    merged = understand.merge_profile(
        old, ProfileUpdates(cities=["San Francisco, CA"], interests=["gardens"])
    )

    assert merged.cities == ["San Francisco, CA"]
    assert merged.interests == ["gardens"]


def test_merge_overwrites_scalar_values() -> None:
    old = TripProfile(origin="Houston, TX", travelers=3)

    merged = understand.merge_profile(old, ProfileUpdates(origin="College Station, TX"))

    assert merged.origin == "College Station, TX"
    assert merged.travelers == 3


def test_merge_recomputes_missing_required() -> None:
    old = TripProfile(missing_required=["destination", "dates", "origin", "travelers", "interests"])

    merged = understand.merge_profile(old, ProfileUpdates(cities=["San Jose, CA"]))

    assert set(merged.missing_required) == {"dates", "origin", "travelers", "interests"}


def test_merge_to_full_profile_has_nothing_missing() -> None:
    old = _full_profile(travelers=None, missing_required=["travelers"])

    merged = understand.merge_profile(old, ProfileUpdates(travelers=1))

    assert merged.missing_required == []


def test_merge_does_not_fill_budget_default() -> None:
    # D17: budget_level stays null until the user states it.
    merged = understand.merge_profile(TripProfile(), ProfileUpdates(cities=["San Jose, CA"]))
    assert merged.budget_level is None


def test_merge_keeps_stated_budget() -> None:
    merged = understand.merge_profile(TripProfile(), ProfileUpdates(budget_level="mid"))
    assert merged.budget_level == "mid"


# --- the fake provider's scripted San Jose demo ---------------------------------------------


def _fake_analysis(text: str) -> TurnAnalysis:
    provider = FakeProvider()
    return asyncio.run(
        provider.complete_json("system", [{"role": "user", "content": text}], TurnAnalysis)
    )


def test_fake_understand_returns_turn_analysis_with_chat_action() -> None:
    analysis = _fake_analysis("San Jose, CA")
    assert isinstance(analysis, TurnAnalysis)
    assert analysis.action == "chat"
    assert analysis.profile_updates.cities == ["San Jose, CA"]


def test_fake_understand_no_keywords_gives_no_updates() -> None:
    analysis = _fake_analysis("Hello there")
    assert analysis.profile_updates.model_dump(exclude_none=True) == {}


def test_fake_understand_first_weekend_of_march() -> None:
    updates = _fake_analysis("first weekend of march please").profile_updates
    assert str(updates.start_date) == "2027-03-05"
    assert str(updates.end_date) == "2027-03-07"
    assert updates.duration_days == 3


# --- the turn: one understand call, `profile` event, DB save (via the API) ------------------


def test_profile_event_follows_message_start_and_precedes_tokens(client: TestClient) -> None:
    session_id = _create_session(client)

    names = _names(_send(client, session_id, "I want to visit San Jose"))

    assert names[:2] == ["message_start", "profile"]
    assert names.count("profile") == 1
    assert set(names[2:-1]) == {"token"}
    assert names[-1] == "done"


def test_profile_event_carries_the_full_merged_profile(client: TestClient) -> None:
    session_id = _create_session(client)

    (data,) = _profile_events(_send(client, session_id, "I want to visit San Jose"))

    assert set(data) == set(TripProfile.model_fields)
    assert data["cities"] == ["San Jose, CA"]
    assert set(data["missing_required"]) == {"dates", "origin", "travelers", "interests"}
    assert data["budget_level"] is None  # D17


def test_no_profile_event_when_nothing_changed(client: TestClient) -> None:
    session_id = _create_session(client)

    events = _send(client, session_id, "Hello there")

    assert "profile" not in _names(events)
    assert _names(events)[-1] == "done"


def test_no_profile_event_when_the_same_value_is_repeated(client: TestClient) -> None:
    session_id = _create_session(client)
    first = _send(client, session_id, "San Jose")

    second = _send(client, session_id, "Yes, San Jose")

    assert "profile" in _names(first)
    assert "profile" not in _names(second)


def test_profile_event_on_each_turn_that_changes_something(client: TestClient) -> None:
    session_id = _create_session(client)

    a = _profile_events(_send(client, session_id, "San Jose"))
    b = _profile_events(_send(client, session_id, "from College Station"))

    assert len(a) == 1 and len(b) == 1
    assert b[0]["cities"] == ["San Jose, CA"]  # earlier fields survive the merge
    assert b[0]["origin"] == "College Station, TX"


def test_profile_is_saved_to_the_db_as_json(client: TestClient, db_engine: Engine) -> None:
    session_id = _create_session(client)

    events = _send(client, session_id, "San Jose, first weekend of march")

    stored = _stored_profile(db_engine, session_id)
    (event_data,) = _profile_events(events)
    assert stored == event_data
    # Dates are stored as ISO strings (model_dump(mode="json")).
    assert stored["start_date"] == "2027-03-05"
    assert stored["end_date"] == "2027-03-07"
    assert stored["duration_days"] == 3


def test_get_session_returns_the_saved_profile(client: TestClient) -> None:
    session_id = _create_session(client)
    _send(client, session_id, "San Jose from College Station")

    profile = client.get(f"/api/sessions/{session_id}").json()["trip_profile"]

    assert profile["cities"] == ["San Jose, CA"]
    assert profile["origin"] == "College Station, TX"
    assert set(profile["missing_required"]) == {"dates", "travelers", "interests"}


def test_san_jose_demo_walk_fills_the_fixture_profile(
    client: TestClient, db_engine: Engine
) -> None:
    messages = json.loads((FIXTURES / "sanjose-messages.json").read_text("utf-8"))
    user_turns = [m["content"] for m in messages if m["role"] == "user"]
    user_turns = [t for t in user_turns if "[" not in t]  # intake turns only, no edits by tag
    session_id = _create_session(client)

    for text in user_turns + ["just me, and I'm vegan"]:
        _send(client, session_id, text)

    expected = json.loads((FIXTURES / "sanjose-profile.json").read_text("utf-8"))
    assert _stored_profile(db_engine, session_id) == expected
    assert client.get(f"/api/sessions/{session_id}").json()["trip_profile"] == expected


def test_one_understand_call_per_turn_with_turn_analysis_schema(client: TestClient) -> None:
    provider = ScriptedProvider([{"profile_updates": {}}, {"profile_updates": {}}])
    _use_provider(client, provider)
    session_id = _create_session(client)

    _send(client, session_id, "first")
    _send(client, session_id, "second")

    assert len(provider.json_calls) == 2
    assert all(schema is TurnAnalysis for _, _, schema in provider.json_calls)
    _, messages, _ = provider.json_calls[1]
    assert messages[-1] == {"role": "user", "content": "second"}


def test_understand_sees_the_current_profile(client: TestClient) -> None:
    provider = ScriptedProvider(
        [{"profile_updates": {"origin": "Bryan, TX"}}, {"profile_updates": {}}]
    )
    _use_provider(client, provider)
    session_id = _create_session(client)

    _send(client, session_id, "from Bryan")
    _send(client, session_id, "ok")

    system, _, _ = provider.json_calls[1]
    assert "Bryan, TX" in system


def test_chat_reply_context_uses_the_merged_profile(client: TestClient) -> None:
    provider = ScriptedProvider([{"profile_updates": {"cities": ["Austin, TX"]}}])
    _use_provider(client, provider)
    session_id = _create_session(client)

    _send(client, session_id, "Austin")

    assert "Austin, TX" in provider.stream_systems[0]


def test_scripted_list_update_replaces_stored_list(client: TestClient, db_engine: Engine) -> None:
    provider = ScriptedProvider(
        [
            {"profile_updates": {"interests": ["tech", "food"]}},
            {"profile_updates": {"interests": ["gardens"]}},
        ]
    )
    _use_provider(client, provider)
    session_id = _create_session(client)

    _send(client, session_id, "tech and food")
    _send(client, session_id, "actually just gardens")

    assert _stored_profile(db_engine, session_id)["interests"] == ["gardens"]


def test_failed_understand_continues_as_plain_chat(client: TestClient, db_engine: Engine) -> None:
    _use_provider(client, FailingUnderstandProvider())
    session_id = _create_session(client)
    before = _stored_profile(db_engine, session_id)

    events = _send(client, session_id, "San Jose please")

    names = _names(events)
    assert names[0] == "message_start"
    assert names[-1] == "done"
    assert "profile" not in names and "error" not in names
    assert "".join(d["text"] for n, d in events if n == "token") == "still here"
    assert _stored_profile(db_engine, session_id) == before


def test_fake_provider_turn_still_streams_the_canned_reply(client: TestClient) -> None:
    session_id = _create_session(client)

    events = _send(client, session_id, "San Jose")

    assert "".join(d["text"] for n, d in events if n == "token") == CANNED_REPLY


# --- missing_required on a new session (contracts §2.1: "The server computes missing_required")


def test_new_session_lists_all_missing_required(client: TestClient) -> None:
    created = client.post("/api/sessions").json()

    assert set(created["trip_profile"]["missing_required"]) == ALL_REQUIRED
    fetched = client.get(f"/api/sessions/{created['id']}").json()
    assert set(fetched["trip_profile"]["missing_required"]) == ALL_REQUIRED


def test_missing_required_after_a_turn_without_updates(client: TestClient) -> None:
    session_id = _create_session(client)
    _send(client, session_id, "Hello there")

    profile = client.get(f"/api/sessions/{session_id}").json()["trip_profile"]

    assert set(profile["missing_required"]) == ALL_REQUIRED
