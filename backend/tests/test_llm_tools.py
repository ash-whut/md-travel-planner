"""Step 32b: tool calling in the LLM layer. A stub client stands in for AsyncOpenAI, so no test
here touches the network except the one marked live (skipped by default)."""

import asyncio
import json
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.config import Settings
from app.llm.base import ToolCall, ToolRound, ToolSpec
from app.llm.factory import get_provider
from app.llm.fake_provider import PLANNER_EDIT_MARKER, PLANNER_PROFILE_MARKER, FakeProvider
from app.llm.openai_compat_provider import OpenAICompatProvider
from app.schemas.profile import TripProfile

MESSAGES = [{"role": "user", "content": "Plan a weekend in Austin"}]

PLACES_TOOL = ToolSpec(
    name="search_places",
    description="Find places in a city for one interest.",
    parameters={
        "type": "object",
        "properties": {"city": {"type": "string"}, "interest": {"type": "string"}},
        "required": ["city", "interest"],
    },
)
HOTELS_TOOL = ToolSpec(
    name="search_hotels",
    description="Find hotels in a city for the given dates.",
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string"},
            "check_in": {"type": "string"},
            "check_out": {"type": "string"},
        },
        "required": ["city", "check_in", "check_out"],
    },
)
TOOLS = [PLACES_TOOL, HOTELS_TOOL]


# ---- stub client -------------------------------------------------------------------------


def _tool_call(call_id: str, name: str, arguments: str | None) -> SimpleNamespace:
    return SimpleNamespace(id=call_id, type="function", function=SimpleNamespace(name=name, arguments=arguments))


def _reply(tool_calls: list[SimpleNamespace] | None, content: str | None = None) -> SimpleNamespace:
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class StubCompletions:
    """Mimics `client.chat.completions.create`: records every call's kwargs, returns replies in order."""

    def __init__(self, replies: list[SimpleNamespace]) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.replies.pop(0)


def _provider(completions: StubCompletions) -> OpenAICompatProvider:
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return OpenAICompatProvider(model="m", client=client)  # type: ignore[arg-type]


def _turn(
    provider: Any, system: str = "sys", rounds: list[ToolRound] | None = None, tools: list[ToolSpec] | None = None
) -> list[ToolCall]:
    return asyncio.run(provider.tool_turn(system, MESSAGES, rounds or [], TOOLS if tools is None else tools))


# ---- OpenAI adapter: request ---------------------------------------------------------------


def test_adapter_sends_tools_in_openai_format_with_stream_false() -> None:
    completions = StubCompletions([_reply(None)])
    _turn(_provider(completions), system="You are the planner.")
    assert len(completions.calls) == 1
    call = completions.calls[0]
    assert call["model"] == "m"
    assert call["stream"] is False  # D16: must be explicit or TAMU AI streams anyway
    assert call["tools"] == [
        {
            "type": "function",
            "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
        }
        for t in TOOLS
    ]
    # No earlier rounds: just the system text, then the messages.
    assert call["messages"] == [{"role": "system", "content": "You are the planner."}, *MESSAGES]


def test_adapter_sends_earlier_rounds_with_results_in_call_order() -> None:
    round_1 = ToolRound(
        calls=[
            ToolCall(id="a1", name="search_places", arguments={"city": "Austin", "interest": "food"}),
            ToolCall(id="a2", name="search_places", arguments={"city": "Austin", "interest": "music"}),
            ToolCall(id="a3", name="search_hotels", arguments={"city": "Austin", "check_in": "2027-03-05", "check_out": "2027-03-07"}),
        ],
        results=['{"ok": true, "n": 1}', '{"ok": true, "n": 2}', '{"ok": false}'],
    )
    round_2 = ToolRound(
        calls=[ToolCall(id="b1", name="search_places", arguments={"city": "Austin", "interest": "parks"})],
        results=['{"ok": true, "n": 3}'],
    )
    completions = StubCompletions([_reply(None)])
    _turn(_provider(completions), rounds=[round_1, round_2])

    messages = completions.calls[0]["messages"]
    assert messages[0] == {"role": "system", "content": "sys"}
    assert messages[1:2] == MESSAGES
    after = messages[2:]
    # Round 1: one assistant message with all three calls, then one tool message per result.
    assistant_1 = after[0]
    assert assistant_1["role"] == "assistant"
    # TAMU AI needs a string here: null or a missing content gives 422 (found by the live test).
    assert assistant_1["content"] == ""
    assert [tc["id"] for tc in assistant_1["tool_calls"]] == ["a1", "a2", "a3"]
    for tc, call in zip(assistant_1["tool_calls"], round_1.calls):
        assert tc["type"] == "function"
        assert tc["function"]["name"] == call.name
        # Arguments go back as a JSON string, as the OpenAI format wants.
        assert isinstance(tc["function"]["arguments"], str)
        assert json.loads(tc["function"]["arguments"]) == call.arguments
    assert after[1:4] == [
        {"role": "tool", "tool_call_id": "a1", "content": '{"ok": true, "n": 1}'},
        {"role": "tool", "tool_call_id": "a2", "content": '{"ok": true, "n": 2}'},
        {"role": "tool", "tool_call_id": "a3", "content": '{"ok": false}'},
    ]
    # Round 2 follows round 1.
    assert after[4]["role"] == "assistant"
    assert [tc["id"] for tc in after[4]["tool_calls"]] == ["b1"]
    assert after[5] == {"role": "tool", "tool_call_id": "b1", "content": '{"ok": true, "n": 3}'}
    assert len(after) == 6


# ---- OpenAI adapter: response --------------------------------------------------------------


def test_adapter_parses_several_parallel_calls_in_order() -> None:
    completions = StubCompletions([
        _reply([
            _tool_call("c1", "search_places", '{"city": "Austin", "interest": "food"}'),
            _tool_call("c2", "search_places", '{"city": "Austin", "interest": "music"}'),
            _tool_call("c3", "search_hotels", '{"city": "Austin", "check_in": "2027-03-05", "check_out": "2027-03-07"}'),
        ])
    ])
    calls = _turn(_provider(completions))
    assert calls == [
        ToolCall(id="c1", name="search_places", arguments={"city": "Austin", "interest": "food"}),
        ToolCall(id="c2", name="search_places", arguments={"city": "Austin", "interest": "music"}),
        ToolCall(id="c3", name="search_hotels", arguments={"city": "Austin", "check_in": "2027-03-05", "check_out": "2027-03-07"}),
    ]


@pytest.mark.parametrize("tool_calls", [None, []])
def test_adapter_no_tool_calls_means_done(tool_calls: list[Any] | None) -> None:
    completions = StubCompletions([_reply(tool_calls, content="I have what I need.")])
    assert _turn(_provider(completions)) == []


@pytest.mark.parametrize("bad_arguments", ["{not json", '["a list"]', '"a string"', "42", "null"])
def test_adapter_skips_a_call_with_bad_arguments_json(bad_arguments: str, caplog: pytest.LogCaptureFixture) -> None:
    completions = StubCompletions([
        _reply([
            _tool_call("c1", "search_places", '{"city": "Austin", "interest": "food"}'),
            _tool_call("c2", "search_places", bad_arguments),
            _tool_call("c3", "search_places", '{"city": "Austin", "interest": "parks"}'),
        ])
    ])
    with caplog.at_level("WARNING"):
        calls = _turn(_provider(completions))
    # Only the bad call is dropped; the good ones keep their order.
    assert [c.id for c in calls] == ["c1", "c3"]
    assert any("search_places" in record.getMessage() for record in caplog.records)


def test_adapter_empty_arguments_mean_no_arguments() -> None:
    completions = StubCompletions([_reply([_tool_call("c1", "search_places", ""), _tool_call("c2", "search_places", None)])])
    calls = _turn(_provider(completions))
    assert [(c.id, c.arguments) for c in calls] == [("c1", {}), ("c2", {})]


# ---- fake planner script ---------------------------------------------------------------------


def _planner_system(profile: TripProfile, edit: str | None = None) -> str:
    """A planner-style system text: the profile JSON after the marker, text before and after."""
    text = f"You plan trips.\n\n{PLANNER_PROFILE_MARKER}\n{profile.model_dump_json()}\n\nWeather: sunny."
    if edit is not None:
        text += f"\n\n{PLANNER_EDIT_MARKER} {edit}"
    return text


SAN_JOSE = TripProfile(
    cities=["San Jose, CA"],
    start_date=date(2027, 3, 5),
    end_date=date(2027, 3, 7),
    interests=["tech", "food", "gardens"],
)


def test_fake_generate_round_1_searches_places_per_interest_then_hotels() -> None:
    calls = _turn(FakeProvider(), system=_planner_system(SAN_JOSE))
    assert calls == [
        ToolCall(id="call_1", name="search_places", arguments={"city": "San Jose, CA", "interest": "tech"}),
        ToolCall(id="call_2", name="search_places", arguments={"city": "San Jose, CA", "interest": "food"}),
        ToolCall(id="call_3", name="search_places", arguments={"city": "San Jose, CA", "interest": "gardens"}),
        ToolCall(
            id="call_4",
            name="search_hotels",
            arguments={"city": "San Jose, CA", "check_in": "2027-03-05", "check_out": "2027-03-07"},
        ),
    ]


def test_fake_generate_two_cities_covers_every_city_and_interest() -> None:
    profile = TripProfile(
        cities=["San Francisco, CA", "Oakland, CA"],
        start_date=date(2027, 4, 1),
        end_date=date(2027, 4, 3),
        interests=["food", "art"],
    )
    calls = _turn(FakeProvider(), system=_planner_system(profile))
    places = [c.arguments for c in calls if c.name == "search_places"]
    hotels = [c.arguments for c in calls if c.name == "search_hotels"]
    assert sorted((p["city"], p["interest"]) for p in places) == sorted(
        (city, interest) for city in profile.cities for interest in profile.interests
    )
    assert [h["city"] for h in hotels] == profile.cities
    assert all(h["check_in"] == "2027-04-01" and h["check_out"] == "2027-04-03" for h in hotels)
    # Ids are unique and numbered call_1, call_2, ...
    assert [c.id for c in calls] == [f"call_{i}" for i in range(1, len(calls) + 1)]


def test_fake_hotel_dates_from_start_plus_duration() -> None:
    profile = TripProfile(cities=["Austin, TX"], start_date=date(2027, 3, 5), duration_days=3, interests=["food"])
    hotels = [c for c in _turn(FakeProvider(), system=_planner_system(profile)) if c.name == "search_hotels"]
    assert [h.arguments for h in hotels] == [{"city": "Austin, TX", "check_in": "2027-03-05", "check_out": "2027-03-07"}]


@pytest.mark.parametrize(
    "profile",
    [
        # Only rough timing, no exact dates.
        TripProfile(cities=["Austin, TX"], rough_timing="a weekend in March", duration_days=3, interests=["food"]),
        # A start date but no end and no length.
        TripProfile(cities=["Austin, TX"], start_date=date(2027, 3, 5), interests=["food"]),
    ],
)
def test_fake_no_hotels_without_exact_dates(profile: TripProfile) -> None:
    calls = _turn(FakeProvider(), system=_planner_system(profile))
    assert [c.name for c in calls] == ["search_places"]
    assert calls[0].arguments == {"city": "Austin, TX", "interest": "food"}


def test_fake_asks_only_for_tools_it_was_given() -> None:
    only_places = _turn(FakeProvider(), system=_planner_system(SAN_JOSE), tools=[PLACES_TOOL])
    assert {c.name for c in only_places} == {"search_places"}
    assert len(only_places) == 3

    only_hotels = _turn(FakeProvider(), system=_planner_system(SAN_JOSE), tools=[HOTELS_TOOL])
    assert [c.name for c in only_hotels] == ["search_hotels"]

    assert _turn(FakeProvider(), system=_planner_system(SAN_JOSE), tools=[]) == []


def test_fake_edit_asks_for_no_tools() -> None:
    system = _planner_system(SAN_JOSE, edit="replace [F] with something vegan")
    assert _turn(FakeProvider(), system=system) == []


def test_fake_later_round_asks_for_no_tools() -> None:
    earlier = ToolRound(
        calls=[ToolCall(id="call_1", name="search_places", arguments={"city": "San Jose, CA", "interest": "tech"})],
        results=['{"ok": true}'],
    )
    assert _turn(FakeProvider(), system=_planner_system(SAN_JOSE), rounds=[earlier]) == []


def test_fake_without_a_profile_asks_for_no_tools() -> None:
    assert _turn(FakeProvider(), system="You plan trips.") == []


# ---- live (skipped by default; run with `pytest -m live`) ----------------------------------


@pytest.mark.live
def test_live_tool_round_trip_with_two_parallel_calls() -> None:
    # conftest forces LLM_PROVIDER=fake in the environment, so override it; the rest comes
    # from backend/.env.
    live = Settings().model_copy(update={"llm_provider": "openai_compat"})
    if not (live.llm_model and live.llm_api_key and live.llm_base_url):
        pytest.skip("LLM_MODEL / LLM_API_KEY / LLM_BASE_URL not set in backend/.env")
    provider = get_provider(live, "planner")
    system = (
        "You plan trips. Use the search_places tool to gather places. Call all the searches you "
        "need at once, in parallel. When you have the results, call no more tools."
    )
    messages = [{"role": "user", "content": "Find food places and park places in Austin, TX. Search both at once."}]

    async def run() -> tuple[list[ToolCall], list[ToolCall]]:
        first = await provider.tool_turn(system, messages, [], [PLACES_TOOL])
        results = [json.dumps({"ok": True, "data": [{"name": f"Place for {c.arguments.get('interest')}"}]}) for c in first]
        second = await provider.tool_turn(system, messages, [ToolRound(calls=first, results=results)], [PLACES_TOOL])
        return first, second

    first, second = asyncio.run(run())
    assert len(first) >= 2
    assert all(c.name == "search_places" and c.id for c in first)
    assert len({c.id for c in first}) == len(first)
    # The results round trip is accepted by the endpoint; the model should be done by now.
    assert isinstance(second, list)
