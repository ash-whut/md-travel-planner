"""Step 22: compose call (+ one repair try).

Specified by plan step 22: the fake path gives a valid itinerary; a fake that returns a bad then
a good draft -> success after 1 repair; bad twice -> a clear failure. Drafts that don't even fit
the ItineraryDraft schema count as bad too. No network: FakeProvider + recorded JSON only.
"""

import asyncio
import copy
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from app.agent import pipeline
from app.agent.pipeline import ComposeError, compose
from app.llm.base import Message, T
from app.llm.fake_provider import FakeProvider, load_fake_data
from app.schemas.itinerary import Itinerary, ItineraryDraft, itinerary_errors
from app.schemas.profile import TripProfile

FIXTURES = Path(__file__).resolve().parent / "fixtures"
TODAY = date(2027, 2, 1)
CHAT: list[Message] = [
    {"role": "user", "content": "San Jose, first weekend of March, just me. Tech and food."},
    {"role": "assistant", "content": "Nice! Anything else?"},
    {"role": "user", "content": "Just make the plan."},
]


# ---- Helpers ----

def load_raw(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def good_draft() -> dict[str, Any]:
    return load_fake_data("draft_sanjose_v1")


def bad_draft() -> dict[str, Any]:
    # Parses as a draft, but postprocess rejects it (unsorted items, day 2 numbered 3).
    return load_raw("draft_bad.json")


def unparseable_draft() -> dict[str, Any]:
    # Fails ItineraryDraft itself: an item points at a stop key that doesn't exist.
    raw = good_draft()
    raw["days"][0]["items"][0]["stop_key"] = "s999"
    return raw


def profile() -> TripProfile:
    return TripProfile(budget_level="budget", cities=["San Jose, CA"], travelers=1)


class RecordingFake(FakeProvider):
    """FakeProvider that records every compose call (system + messages)."""

    def __init__(self, drafts: list[dict[str, Any]] | None = None) -> None:
        super().__init__(drafts=drafts)
        self.calls: list[tuple[str, list[Message]]] = []

    async def complete_json(self, system: str, messages: list[Message], schema: type[T]) -> T:
        if schema is ItineraryDraft:
            self.calls.append((system, copy.deepcopy(messages)))
        return await super().complete_json(system, messages, schema)


def run_compose(
    llm: FakeProvider,
    messages: list[Message] | None = None,
    previous: list[Itinerary] | None = None,
) -> Itinerary:
    return asyncio.run(
        compose(llm, profile(), CHAT if messages is None else messages, previous, today=TODAY)
    )


def tags_by_day(itinerary: Itinerary) -> list[list[str | None]]:
    return [[item.stop_tag for item in day.items] for day in itinerary.days]


# ---- Fake path -> valid itinerary ----

def test_default_fake_gives_valid_v1_itinerary() -> None:
    llm = RecordingFake()
    itinerary = run_compose(llm)
    assert isinstance(itinerary, Itinerary)
    assert itinerary.version == 1
    assert itinerary_errors(itinerary) == []
    assert [stop.tag for stop in itinerary.stops] == list("ABCDEFGHIJK")
    assert tags_by_day(itinerary)[0] == ["A", "B", "C", "D", "E"]
    assert len(llm.calls) == 1  # no repair needed


def test_fake_data_draft_is_a_valid_draft() -> None:
    # The fake provider's canned reply must parse as an ItineraryDraft.
    ItineraryDraft.model_validate(load_fake_data("draft_sanjose_v1"))


def test_fake_with_good_draft_needs_one_call() -> None:
    llm = RecordingFake(drafts=[good_draft()])
    itinerary = run_compose(llm)
    assert itinerary_errors(itinerary) == []
    assert len(llm.calls) == 1


def test_compose_with_previous_version_gives_v2_and_keeps_id() -> None:
    v1 = run_compose(RecordingFake())
    v2 = run_compose(RecordingFake(drafts=[load_raw("draft_sanjose_v2.json")]), previous=[v1])
    assert v2.version == 2
    assert v2.id == v1.id
    assert itinerary_errors(v2) == []


# ---- The compose request ----

def test_system_has_compose_prompt_today_and_profile() -> None:
    llm = RecordingFake()
    run_compose(llm)
    system, _ = llm.calls[0]
    assert "ItineraryDraft" in system  # from prompts/compose.md
    assert "2027-02-01" in system
    assert "San Jose" in system


def test_request_is_added_to_last_user_message() -> None:
    llm = RecordingFake()
    run_compose(llm)
    _, messages = llm.calls[0]
    assert len(messages) == len(CHAT)
    assert messages[:-1] == CHAT[:-1]
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"].startswith(CHAT[-1]["content"])
    assert pipeline.COMPOSE_REQUEST in messages[-1]["content"]


def test_request_is_a_new_user_message_after_an_assistant_turn() -> None:
    chat: list[Message] = CHAT[:2]
    llm = RecordingFake()
    run_compose(llm, messages=chat)
    _, messages = llm.calls[0]
    assert messages[:2] == chat
    assert messages[-1] == {"role": "user", "content": pipeline.COMPOSE_REQUEST}


def test_request_with_empty_chat() -> None:
    llm = RecordingFake()
    itinerary = run_compose(llm, messages=[])
    assert itinerary_errors(itinerary) == []
    _, messages = llm.calls[0]
    assert messages == [{"role": "user", "content": pipeline.COMPOSE_REQUEST}]


def test_compose_does_not_modify_the_chat() -> None:
    chat = copy.deepcopy(CHAT)
    run_compose(RecordingFake(drafts=[bad_draft(), good_draft()]), messages=chat)
    assert chat == CHAT


# ---- Bad then good -> success after 1 repair ----

def test_bad_then_good_succeeds_after_one_repair() -> None:
    llm = RecordingFake(drafts=[bad_draft(), good_draft()])
    itinerary = run_compose(llm)
    assert itinerary_errors(itinerary) == []
    assert itinerary.version == 1
    assert [stop.tag for stop in itinerary.stops] == list("ABCDEFGHIJK")
    assert len(llm.calls) == 2


def test_repair_request_includes_the_errors() -> None:
    llm = RecordingFake(drafts=[bad_draft(), good_draft()])
    run_compose(llm)
    _, first = llm.calls[0]
    _, second = llm.calls[1]
    repair = second[-1]["content"].lower()
    assert "sorted" in repair  # day 1 items out of order
    assert "day_number" in repair  # day 2 numbered 3
    assert "sorted" not in first[-1]["content"].lower()
    # Same chat before the request; roles still alternate.
    assert second[:-1] == CHAT[:-1]
    assert second[-1]["role"] == "user"


def test_unparseable_then_good_succeeds_after_one_repair() -> None:
    llm = RecordingFake(drafts=[unparseable_draft(), good_draft()])
    itinerary = run_compose(llm)
    assert itinerary_errors(itinerary) == []
    assert len(llm.calls) == 2
    _, second = llm.calls[1]
    assert "s999" in second[-1]["content"]


def test_bad_then_default_fake_succeeds() -> None:
    # Once the scripted drafts run out, the fake gives the San Jose v1 draft.
    llm = RecordingFake(drafts=[bad_draft()])
    itinerary = run_compose(llm)
    assert itinerary_errors(itinerary) == []
    assert len(llm.calls) == 2


# ---- Bad twice -> a clear failure ----

def test_bad_twice_raises_compose_error() -> None:
    llm = RecordingFake(drafts=[bad_draft(), bad_draft(), good_draft()])
    with pytest.raises(ComposeError) as info:
        run_compose(llm)
    assert str(info.value).startswith("The plan could not be made")
    assert info.value.errors
    assert all(isinstance(line, str) and line for line in info.value.errors)
    assert len(llm.calls) == 2  # only one repair try, never a third call


def test_compose_error_says_what_went_wrong() -> None:
    llm = RecordingFake(drafts=[bad_draft(), bad_draft()])
    with pytest.raises(ComposeError) as info:
        run_compose(llm)
    text = " | ".join(info.value.errors).lower()
    assert "sorted" in text or "day_number" in text
    for line in info.value.errors:
        assert line in str(info.value)


def test_unparseable_twice_raises_compose_error() -> None:
    llm = RecordingFake(drafts=[unparseable_draft(), unparseable_draft()])
    with pytest.raises(ComposeError) as info:
        run_compose(llm)
    assert info.value.errors
    assert "s999" in str(info.value)
    assert len(llm.calls) == 2


def test_bad_then_unparseable_raises_compose_error() -> None:
    llm = RecordingFake(drafts=[bad_draft(), unparseable_draft()])
    with pytest.raises(ComposeError):
        run_compose(llm)
    assert len(llm.calls) == 2


def test_failed_compose_does_not_touch_previous_versions() -> None:
    v1 = run_compose(RecordingFake())
    before = v1.model_dump(mode="json")
    with pytest.raises(ComposeError):
        run_compose(RecordingFake(drafts=[bad_draft(), bad_draft()]), previous=[v1])
    assert v1.model_dump(mode="json") == before
