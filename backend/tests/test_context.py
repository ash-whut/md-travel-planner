"""Step 13: the system prompt file and the per-turn context (today's date + trip profile)."""

import asyncio
from collections.abc import AsyncIterator
from datetime import date

from sqlmodel import Session

from app.agent import context, turn
from app.db import repo
from app.llm.base import Message
from app.llm.fake_provider import FakeProvider
from app.schemas.profile import TripProfile

TODAY = date(2026, 11, 7)  # a Saturday


# --- the prompt file -------------------------------------------------------------------


def test_system_prompt_file_loads() -> None:
    prompt = context.load_prompt("system")
    assert prompt.strip()


def test_system_prompt_has_key_rules() -> None:
    prompt = context.load_prompt("system").lower()
    # never claim to book
    assert "never say you booked" in prompt or "cannot book" in prompt
    # letter tags like [C]
    assert "[c]" in prompt
    # at most 2 questions per turn
    assert "2 questions" in prompt
    # short replies
    assert "short" in prompt


def test_build_system_starts_with_the_prompt() -> None:
    system = context.build_system(TripProfile(), today=TODAY)
    assert system.startswith(context.load_prompt("system").strip())


# --- today's date ----------------------------------------------------------------------


def test_context_contains_injected_date() -> None:
    system = context.build_system(TripProfile(), today=TODAY)
    assert "2026-11-07" in system
    assert "Sat, Nov 7, 2026" in system


def test_context_date_has_no_zero_padding() -> None:
    system = context.build_system(TripProfile(), today=date(2027, 3, 5))
    assert "Fri, Mar 5, 2027" in system
    assert "Mar 05" not in system


def test_context_defaults_to_real_today() -> None:
    system = context.build_system(TripProfile())
    assert date.today().isoformat() in system


# --- the profile -----------------------------------------------------------------------


def test_context_contains_known_profile_fields() -> None:
    profile = TripProfile(
        cities=["Austin", "San Antonio"],
        start_date=date(2027, 3, 5),
        end_date=date(2027, 3, 7),
        origin="College Station",
        travelers=2,
        budget_level="budget",
        interests=["food", "music"],
        dietary="vegan",
    )
    system = context.build_system(profile, today=TODAY)
    profile_part = system.split("# Context", 1)[1]
    for value in (
        "Austin",
        "San Antonio",
        "2027-03-05",
        "2027-03-07",
        "College Station",
        "2",
        "budget",
        "food",
        "music",
        "vegan",
    ):
        assert value in profile_part, value


def test_unknown_profile_fields_are_omitted() -> None:
    profile = TripProfile(cities=["Austin"], origin="Houston")
    profile_part = context.build_system(profile, today=TODAY).split("# Context", 1)[1]
    assert "Austin" in profile_part
    assert "Houston" in profile_part
    # No placeholder text for fields the user hasn't given.
    assert "None" not in profile_part
    assert "[]" not in profile_part
    for label in ("Vibe", "Start date", "End date", "Travelers", "Interests", "Dietary", "Pace"):
        assert f"- {label}" not in profile_part, label
    assert "Nothing known yet" not in profile_part


def test_empty_profile_says_nothing_known() -> None:
    profile_part = context.build_system(TripProfile(), today=TODAY).split("# Context", 1)[1]
    assert "Nothing known yet" in profile_part
    assert "None" not in profile_part
    assert "Still needed" not in profile_part


def test_missing_required_is_listed() -> None:
    profile = TripProfile(cities=["Austin"], missing_required=["dates", "origin"])
    profile_part = context.build_system(profile, today=TODAY).split("# Context", 1)[1]
    still_needed = [line for line in profile_part.splitlines() if "Still needed" in line]
    assert len(still_needed) == 1
    assert "dates" in still_needed[0] and "origin" in still_needed[0]


# --- the turn uses the saved profile ---------------------------------------------------


class RecordingLLM(FakeProvider):
    """Fake LLM that remembers the system text it was given."""

    def __init__(self) -> None:
        super().__init__()
        self.systems: list[str] = []

    async def stream_text(self, system: str, messages: list[Message]) -> AsyncIterator[str]:
        self.systems.append(system)
        async for chunk in super().stream_text(system, messages):
            yield chunk


def test_session_profile_reads_saved_profile(db: Session) -> None:
    session_row = repo.create_session(db)
    repo.update_profile(db, session_row.id, {"cities": ["Austin"], "travelers": 3})
    profile = turn.session_profile(db, session_row.id)
    assert profile.cities == ["Austin"]
    assert profile.travelers == 3


def test_session_profile_empty_for_new_session(db: Session) -> None:
    session_row = repo.create_session(db)
    # Contracts §2.1: the server computes missing_required, so a new session's profile has
    # no known fields and all five required fields still missing (in spec F2 order).
    expected = TripProfile(
        missing_required=["destination", "dates", "origin", "travelers", "interests"]
    )
    assert turn.session_profile(db, session_row.id) == expected


def test_turn_passes_profile_and_date_to_llm(db: Session) -> None:
    session_row = repo.create_session(db)
    repo.update_profile(db, session_row.id, {"cities": ["Austin"], "origin": "Waco"})
    llm = RecordingLLM()

    async def drain() -> None:
        async for _ in turn.run_turn(db, session_row.id, "hi", llm):
            pass

    asyncio.run(drain())

    assert len(llm.systems) == 1
    system = llm.systems[0]
    assert system.startswith(context.load_prompt("system").strip())
    assert date.today().isoformat() in system
    assert "Austin" in system
    assert "Waco" in system
