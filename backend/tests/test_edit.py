"""Step 25: the edit path with stable letters (plan step 25, contracts §3, §5).

Specified: v2 keeps every letter except the replaced stop; the new stop gets the next letter;
`updated_in_version = 2` only on changed items; the assistant message has
`itinerary_version = 2`; the compact listing format
(`Day 1 (Fri Mar 5): 06:00 [A] Home · 09:15 [B] IAH …`), added to every turn's context.
`action=edit` runs the generation with the previous plan + the change request, and compose is
told to change only what was asked; the reply is a 1–3 line change summary with tags.
A failed edit leaves the plan unchanged. No network: FakeProvider + recorded JSON + a temp DB.
"""

import asyncio
import copy
import json
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session

from app.agent import context, pipeline, turn
from app.agent.pipeline import compose
from app.agent.postprocess import build_itinerary
from app.agent.turn import TurnLlms
from app.api.chat import get_llm
from app.db import repo
from app.db.tables import MessageRow
from app.llm.base import Message, T
from app.llm.fake_provider import (
    EDIT_PHRASE,
    EDIT_SUMMARY_PHRASE,
    EDIT_SUMMARY_REPLY,
    FakeProvider,
    load_fake_data,
    scripted_turn_analysis,
)
from app.schemas.itinerary import Itinerary, ItineraryDraft, itinerary_errors
from app.schemas.profile import TripProfile
from app.schemas.turn import TurnAnalysis

TODAY = date(2027, 2, 1)
EDIT_MESSAGE = "Replace [F] with something vegan"
# v1 of the San Jose demo: stop name per tag (fake_data/draft_sanjose_v1.json).
V1_TAGS = {
    "A": "Home",
    "B": "IAH",
    "C": "San Jose Airport",
    "D": "Pacific Inn San Jose",
    "E": "San Pedro Square",
    "F": "Baconhouse",
    "G": "The Tech Interactive",
    "H": "Winchester Mystery House",
    "I": "Santana Row",
    "J": "Japantown",
    "K": "Guadalupe River Park",
}

Event = tuple[str, dict[str, Any]]


# --- helpers --------------------------------------------------------------------------------


def _parse_sse(text: str) -> list[Event]:
    events: list[Event] = []
    for block in text.replace("\r\n", "\n").replace("\r", "\n").split("\n\n"):
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
    return client.post("/api/sessions").json()["id"]


def _generate(client: TestClient, session_id: str) -> list[Event]:
    response = client.post(f"/api/sessions/{session_id}/generate", json={})
    assert response.status_code == 200
    return _parse_sse(response.text)


def _send(client: TestClient, session_id: str, content: str) -> list[Event]:
    response = client.post(f"/api/sessions/{session_id}/messages", json={"content": content})
    assert response.status_code == 200
    return _parse_sse(response.text)


def _use_provider(client: TestClient, provider: Any) -> None:
    client.app.dependency_overrides[get_llm] = lambda: TurnLlms(provider, provider)  # type: ignore[attr-defined]


def _versions(engine: Engine, session_id: str) -> list[Itinerary]:
    with Session(engine) as db:
        return repo.list_itineraries(db, session_id)


def _messages(engine: Engine, session_id: str) -> list[MessageRow]:
    with Session(engine) as db:
        return repo.list_messages(db, session_id)


def _streamed_plan(events: list[Event]) -> Itinerary:
    return Itinerary.model_validate(next(d for n, d in events if n == "itinerary"))


def _tag_names(plan: Itinerary) -> dict[str, str]:
    return {stop.tag: stop.name for stop in plan.stops}


def _items(plan: Itinerary) -> list[Any]:
    return [item for day in plan.days for item in day.items]


def _v1_then_edit(client: TestClient) -> tuple[str, list[Event]]:
    """A session with v1 (Generate button), then the edit message."""
    session_id = _create_session(client)
    _generate(client, session_id)
    return session_id, _send(client, session_id, EDIT_MESSAGE)


def _profile() -> TripProfile:
    return TripProfile(budget_level="budget", cities=["San Jose, CA"], travelers=1)


def _v1_plan() -> Itinerary:
    plan = asyncio.run(compose(FakeProvider(), _profile(), [], [], today=TODAY))
    assert itinerary_errors(plan) == []
    return plan


def _bad_draft() -> dict[str, Any]:
    raw = load_fake_data("draft_sanjose_v1")
    raw["days"][0]["items"].reverse()  # unsorted items: postprocess rejects it
    return raw


class RecordingFake(FakeProvider):
    """FakeProvider that records every compose call and every streamed reply's system text."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.compose_calls: list[tuple[str, list[Message]]] = []
        self.systems: list[str] = []

    async def complete_json(self, system: str, messages: list[Message], schema: type[T]) -> T:
        if schema is ItineraryDraft:
            self.compose_calls.append((system, copy.deepcopy(messages)))
        return await super().complete_json(system, messages, schema)

    async def stream_text(self, system: str, messages: list[Message]) -> AsyncIterator[str]:
        self.systems.append(system)
        async for chunk in super().stream_text(system, messages):
            yield chunk


# --- the fake's trigger phrases match the real requests -------------------------------------


def test_fake_edit_phrases_match_the_real_requests() -> None:
    assert EDIT_PHRASE in pipeline.EDIT_REQUEST.lower()
    assert EDIT_SUMMARY_PHRASE in turn.EDIT_SUMMARY_REQUEST.lower()


def test_fake_v2_draft_is_a_valid_draft() -> None:
    ItineraryDraft.model_validate(load_fake_data("draft_sanjose_v2"))


# --- compact listing ------------------------------------------------------------------------


def test_compact_itinerary_lists_one_line_per_day_with_tags() -> None:
    text = context.compact_itinerary(_v1_plan())

    lines = text.splitlines()
    assert lines[0] == "## Current plan (version 1)"
    assert (
        "Day 1 (Fri Mar 5): 06:00 [A] Home · 09:15 [B] IAH · 13:30 [C] San Jose Airport · "
        "14:15 [D] Pacific Inn San Jose · 18:30 [E] San Pedro Square"
    ) in lines
    assert (
        "Day 2 (Sat Mar 6): 11:00 [F] Baconhouse · 13:00 [G] The Tech Interactive · "
        "16:00 [H] Winchester Mystery House · 18:30 [I] Santana Row"
    ) in lines
    # The return flight reuses [C] (same stop = same tag).
    assert (
        "Day 3 (Sun Mar 7): 09:30 [J] Japantown · 11:15 [K] Guadalupe River Park · "
        "14:40 [C] San Jose Airport"
    ) in lines
    assert sum(line.startswith("Day ") for line in lines) == 3


def test_compact_itinerary_shows_the_version() -> None:
    v1 = _v1_plan()
    v2 = build_itinerary(
        ItineraryDraft.model_validate(load_fake_data("draft_sanjose_v2")), [v1], _profile()
    )
    assert isinstance(v2, Itinerary)

    text = context.compact_itinerary(v2)

    assert text.splitlines()[0] == "## Current plan (version 2)"
    assert "11:00 [L] Good Karma Kitchen" in text
    assert "[F]" not in text


def test_compact_itinerary_untagged_item_shows_its_description() -> None:
    raw = load_fake_data("draft_sanjose_v1")
    raw["days"][2]["items"].insert(
        2, {"kind": "free_time", "stop_key": None, "description": "Free time downtown",
            "start_time": "13:00"}
    )
    plan = build_itinerary(ItineraryDraft.model_validate(raw), [], _profile())
    assert isinstance(plan, Itinerary)

    text = context.compact_itinerary(plan)

    day3 = next(line for line in text.splitlines() if line.startswith("Day 3 "))
    assert "11:15 [K] Guadalupe River Park · 13:00 Free time downtown · 14:40 [C]" in day3


def test_every_turn_context_has_the_compact_listing(client: TestClient) -> None:
    provider = RecordingFake()
    _use_provider(client, provider)
    session_id = _create_session(client)
    _generate(client, session_id)

    _send(client, session_id, "What's on day 1?")

    assert all(
        "Day 1 (Fri Mar 5): 06:00 [A] Home · 09:15 [B] IAH" in system
        for system in provider.systems
    )


def test_context_after_an_edit_shows_v2(client: TestClient) -> None:
    provider = RecordingFake()
    _use_provider(client, provider)
    session_id = _create_session(client)
    _generate(client, session_id)
    _send(client, session_id, EDIT_MESSAGE)

    _send(client, session_id, "Thanks!")

    system = provider.systems[-1]
    assert "## Current plan (version 2)" in system
    assert "11:00 [L] Good Karma Kitchen" in system
    assert "[F] Baconhouse" not in system
    # The edit summary itself was written with v2 in context.
    assert "## Current plan (version 2)" in provider.systems[-2]


# --- edit from chat: SSE and persistence ----------------------------------------------------


def test_edit_event_order(client: TestClient) -> None:
    _, events = _v1_then_edit(client)
    names = _names(events)

    # message_start → [profile] → status… → itinerary → token… → done
    assert names[0] == "message_start" and names[-1] == "done"
    rest = [n for n in names[1:-1] if n != "profile"]
    i = rest.index("itinerary")
    assert i >= 1 and set(rest[:i]) == {"status"}
    assert rest[i + 1:] and set(rest[i + 1:]) == {"token"}
    assert names.count("itinerary") == 1 and "error" not in names
    statuses = [d["state"] for n, d in events if n == "status"]
    assert statuses[0] == "start" and statuses[-1] == "end"


def test_edit_saves_v2(client: TestClient, db_engine: Engine) -> None:
    session_id, events = _v1_then_edit(client)

    versions = _versions(db_engine, session_id)
    assert [v.version for v in versions] == [1, 2]
    assert versions[1].model_dump(mode="json") == next(d for n, d in events if n == "itinerary")
    assert versions[1].id == versions[0].id  # same plan, new version
    assert client.get(f"/api/sessions/{session_id}").json()["itinerary"]["version"] == 2


def test_v2_keeps_every_letter_except_the_replaced_stop(client: TestClient) -> None:
    _, events = _v1_then_edit(client)

    tags = _tag_names(_streamed_plan(events))

    kept = {tag: name for tag, name in V1_TAGS.items() if tag != "F"}
    assert {tag: tags[tag] for tag in kept} == kept
    assert "F" not in tags
    assert "Baconhouse" not in tags.values()


def test_the_new_stop_gets_the_next_letter(client: TestClient) -> None:
    _, events = _v1_then_edit(client)
    plan = _streamed_plan(events)

    assert _tag_names(plan)["L"] == "Good Karma Kitchen"
    assert set(_tag_names(plan)) == set(V1_TAGS) - {"F"} | {"L"}
    brunch = plan.days[1].items[0]
    assert brunch.stop_tag == "L"


def test_updated_in_version_2_only_on_the_changed_item(
    client: TestClient, db_engine: Engine
) -> None:
    session_id, _ = _v1_then_edit(client)
    v1, v2 = _versions(db_engine, session_id)

    changed = [item.id for item in _items(v2) if item.updated_in_version == 2]
    assert changed == [v2.days[1].items[0].id]
    # Every other item keeps its v1 value.
    v1_values = {item.id: item.updated_in_version for item in _items(v1)}
    for item in _items(v2):
        if item.id not in changed:
            assert item.updated_in_version == v1_values[item.id]


def test_edit_assistant_message_has_itinerary_version_2(
    client: TestClient, db_engine: Engine
) -> None:
    session_id, events = _v1_then_edit(client)

    stored = _messages(db_engine, session_id)
    assert [(m.role, m.itinerary_version) for m in stored] == [
        ("assistant", None),
        ("assistant", 1),
        ("user", None),
        ("assistant", 2),
    ]
    assert stored[2].content == EDIT_MESSAGE
    assert stored[-1].id == events[-1][1]["message_id"]
    body = client.get(f"/api/sessions/{session_id}").json()
    assert body["messages"][-1]["itinerary_version"] == 2


def test_edit_reply_is_a_short_summary_with_tags(client: TestClient, db_engine: Engine) -> None:
    session_id, events = _v1_then_edit(client)

    streamed = "".join(d["text"] for n, d in events if n == "token")
    summary = _messages(db_engine, session_id)[-1].content
    assert summary == streamed == EDIT_SUMMARY_REPLY
    assert 1 <= len(summary.strip().splitlines()) <= 3
    assert "[F]" in summary and "[L]" in summary


def test_edit_summary_request_asks_for_tags_and_short_reply() -> None:
    request = turn.EDIT_SUMMARY_REQUEST.lower()
    assert "[tags]" in request
    assert "1–3" in request or "1-3" in request


# --- what compose is given for an edit ------------------------------------------------------


def test_edit_compose_gets_the_previous_plan_and_change_request(client: TestClient) -> None:
    provider = RecordingFake()
    _use_provider(client, provider)
    session_id = _create_session(client)
    _generate(client, session_id)

    _send(client, session_id, EDIT_MESSAGE)

    v1_system, v1_messages = provider.compose_calls[0]
    edit_system, edit_messages = provider.compose_calls[-1]
    assert "Baconhouse" not in v1_system  # no plan to edit for v1
    assert "Current plan (version 1)" in edit_system
    assert "Baconhouse" in edit_system and "Guadalupe River Park" in edit_system
    request = edit_messages[-1]["content"]
    assert edit_messages[-1]["role"] == "user"
    assert EDIT_MESSAGE in request
    assert "change only what was asked" in request.lower()


def test_edit_uses_the_understood_change_request(client: TestClient) -> None:
    rephrased = "replace [F] with a vegan brunch spot"

    class RephrasingFake(RecordingFake):
        async def complete_json(
            self, system: str, messages: list[Message], schema: type[T]
        ) -> T:
            if schema is TurnAnalysis and "[F]" in str(messages[-1]["content"]):
                return schema.model_validate(  # type: ignore[return-value]
                    {"profile_updates": {}, "action": "edit", "change_request": rephrased}
                )
            return await super().complete_json(system, messages, schema)

    provider = RephrasingFake()
    _use_provider(client, provider)
    session_id = _create_session(client)
    _generate(client, session_id)

    events = _send(client, session_id, "hmm can we do [F] differently")

    assert _streamed_plan(events).version == 2
    assert rephrased in provider.compose_calls[-1][1][-1]["content"]


def test_compose_with_change_request_gives_v2_with_stable_letters() -> None:
    v1 = _v1_plan()

    v2 = asyncio.run(
        compose(FakeProvider(), _profile(), [{"role": "user", "content": EDIT_MESSAGE}], [v1],
                today=TODAY, change_request=EDIT_MESSAGE)
    )

    assert v2.version == 2 and itinerary_errors(v2) == []
    assert set(_tag_names(v2)) == set(V1_TAGS) - {"F"} | {"L"}


# --- failures and edge cases ----------------------------------------------------------------


def test_failed_edit_keeps_the_plan_unchanged(client: TestClient, db_engine: Engine) -> None:
    session_id = _create_session(client)
    _generate(client, session_id)
    before = _versions(db_engine, session_id)[0].model_dump(mode="json")

    _use_provider(client, FakeProvider(drafts=[_bad_draft(), _bad_draft()]))
    events = _send(client, session_id, EDIT_MESSAGE)
    names = _names(events)

    assert names[-1] == "error" and "itinerary" not in names and "done" not in names
    assert events[-2][0] == "status" and events[-2][1]["state"] == "error"
    assert events[-1][1] == {"message": turn.PLAN_ERROR_MESSAGE, "retryable": True}
    assert "unchanged" in events[-1][1]["message"].lower()
    versions = _versions(db_engine, session_id)
    assert [v.version for v in versions] == [1]
    assert versions[0].model_dump(mode="json") == before
    assert [m.itinerary_version for m in _messages(db_engine, session_id)] == [None, 1, None]


def test_edit_succeeds_after_one_repair(client: TestClient, db_engine: Engine) -> None:
    session_id = _create_session(client)
    _generate(client, session_id)

    _use_provider(
        client, FakeProvider(drafts=[_bad_draft(), load_fake_data("draft_sanjose_v2")])
    )
    events = _send(client, session_id, EDIT_MESSAGE)

    assert _names(events)[-1] == "done"
    assert set(_tag_names(_streamed_plan(events))) == set(V1_TAGS) - {"F"} | {"L"}
    assert [v.version for v in _versions(db_engine, session_id)] == [1, 2]


def test_edit_without_a_plan_saves_nothing(client: TestClient, db_engine: Engine) -> None:
    session_id = _create_session(client)

    events = _send(client, session_id, EDIT_MESSAGE)
    names = _names(events)

    assert names[-1] == "done" and "itinerary" not in names and "error" not in names
    assert _versions(db_engine, session_id) == []
    assert _messages(db_engine, session_id)[-1].itinerary_version is None


def test_removed_letter_is_not_reused_by_a_later_edit(
    client: TestClient, db_engine: Engine
) -> None:
    session_id, _ = _v1_then_edit(client)
    v3_draft = load_fake_data("draft_sanjose_v2")
    for stop in v3_draft["stops"]:
        if stop["key"] == "s12":
            stop["name"] = "Vegan Taco Stand"

    _use_provider(client, FakeProvider(drafts=[v3_draft]))
    events = _send(client, session_id, "Swap [L] for something cheaper")

    tags = _tag_names(_streamed_plan(events))
    assert tags["M"] == "Vegan Taco Stand"
    assert "F" not in tags and "L" not in tags
    assert [v.version for v in _versions(db_engine, session_id)] == [1, 2, 3]


def test_a_stop_from_an_earlier_version_gets_its_old_letter_back(client: TestClient) -> None:
    session_id, _ = _v1_then_edit(client)

    _use_provider(client, FakeProvider(drafts=[load_fake_data("draft_sanjose_v1")]))
    events = _send(client, session_id, "Change [L] back to the original brunch")

    plan = _streamed_plan(events)
    assert plan.version == 3
    assert _tag_names(plan) == V1_TAGS


def test_unchanged_edit_keeps_earlier_updated_in_version(
    client: TestClient, db_engine: Engine
) -> None:
    session_id, _ = _v1_then_edit(client)

    _use_provider(client, FakeProvider(drafts=[load_fake_data("draft_sanjose_v2")]))
    _send(client, session_id, "Change [L] only if needed")

    v3 = _versions(db_engine, session_id)[-1]
    assert v3.version == 3
    assert all(item.updated_in_version != 3 for item in _items(v3))
    assert v3.days[1].items[0].updated_in_version == 2


# --- fake understand rule: a tag OR an edit word (replace/change/swap) -> edit ---------------


def test_fake_treats_a_tag_or_an_edit_word_as_an_edit() -> None:
    for text in ("replace H with something outdoors", "what about [F]?", "Swap the museum"):
        assert scripted_turn_analysis(text)["action"] == "edit", text
    for text in ("hi there", "make the plan", "exchange rates?"):
        assert scripted_turn_analysis(text)["action"] != "edit", text


def test_fake_edit_without_a_plan_runs_as_chat(client: TestClient) -> None:
    names = _names(_send(client, _create_session(client), "replace H with a park"))
    assert names[-1] == "done" and "itinerary" not in names and "error" not in names
