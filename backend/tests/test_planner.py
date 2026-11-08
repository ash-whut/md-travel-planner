"""Step 33a: the planner agent's tool rounds, run in parallel.

Specified by plan step 33a (D24, D25): at most 3 rounds of one `tool_turn` each; only the first
6 calls of a round run and the rest get a "skipped: limit" reply; a round's calls run at the
same time; the loop stops when the model asks for none; each call gets its own status start →
end/error with a unique label ("Finding food spots in San Jose"), inside one "Choosing what to
look up…" line; code numbers result items with refs (p1…, h1…) that stay unique across rounds;
a tool that fails or raises gives an error reply and planning goes on; an edit that only moves a
stop makes no tool calls; weather for several cities runs in parallel too. With the fake LLM a
generated plan shows the places status lines.

No network: FakeProvider or a scripted provider, TOOL_PROVIDER_MODE=mock, fake registry tools
(monkeypatched `registry.TOOLS`), a temp DB.
"""

import asyncio
import json
import threading
import time
from collections.abc import AsyncIterator, Callable
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.agent import pipeline, planner
from app.agent.planner import CHOOSING_LABEL, SKIPPED_REPLY, Finding, run_planner
from app.agent.postprocess import CityWeather, build_itinerary
from app.agent.turn import TurnLlms
from app.api.chat import get_llm
from app.db import repo
from app.llm import fake_provider
from app.llm.base import Message, ToolCall, ToolRound, ToolSpec
from app.llm.fake_provider import FakeProvider, load_fake_data
from app.schemas.itinerary import DayWeather, Itinerary, ItineraryDraft
from app.schemas.profile import TripProfile
from app.tools import registry
from app.tools.common import ToolResult, tool_error, tool_ok
from app.tools.registry import Tool

TODAY = date(2027, 2, 1)
START, END = date(2027, 3, 5), date(2027, 3, 7)
BARRIER_TIMEOUT = 5.0  # seconds; a broken barrier fails the test instead of hanging it
REQUEST: list[Message] = [{"role": "user", "content": planner.PLANNER_REQUEST}]
# The fake sets city + Mar 5–7 dates + three interests from this message.
TRIP_MESSAGE = "San Jose, first weekend of March, just me. I like tech, food and gardens."
PLACES_LABELS = [
    "Finding tech spots in San Jose",
    "Finding food spots in San Jose",
    "Finding gardens spots in San Jose",
]

Event = tuple[str, dict[str, Any]]


# --- helpers --------------------------------------------------------------------------------


def _profile(**updates: Any) -> TripProfile:
    fields: dict[str, Any] = dict(
        budget_level="budget", cities=["San Jose, CA"], travelers=1,
        start_date=START, end_date=END, interests=["tech", "food"],
    )
    fields.update(updates)
    return TripProfile(**fields)


def _call(name: str, n: int = 1, **arguments: Any) -> ToolCall:
    return ToolCall(id=f"call_{name}_{n}", name=name, arguments=arguments)


class ScriptedPlanner(FakeProvider):
    """A provider whose `tool_turn` gives the scripted calls, one list per round (then none).

    A script entry that is an Exception is raised instead. `repeat` makes the last entry come
    back forever (to test the round cap). Records what every `tool_turn` call received.
    """

    def __init__(self, script: list[list[ToolCall] | Exception], repeat: bool = False) -> None:
        super().__init__()
        self.script = list(script)
        self.repeat = repeat
        self.seen_rounds: list[list[ToolRound]] = []
        self.seen_tools: list[list[str]] = []
        self.systems: list[str] = []

    async def tool_turn(
        self, system: str, messages: list[Message], rounds: list[ToolRound], tools: list[ToolSpec]
    ) -> list[ToolCall]:
        self.systems.append(system)
        self.seen_rounds.append(list(rounds))
        self.seen_tools.append([tool.name for tool in tools])
        index = len(self.seen_rounds) - 1
        if index < len(self.script):
            entry = self.script[index]
        elif self.repeat and self.script:
            entry = self.script[-1]
        else:
            return []
        if isinstance(entry, Exception):
            raise entry
        return list(entry)


def _tool(name: str, function: Callable[..., ToolResult]) -> Tool:
    return Tool(
        name=name, description=f"Fake {name}.",
        parameters={"type": "object", "properties": {}}, function=function,
    )


def _use_tools(monkeypatch: pytest.MonkeyPatch, *tools: Tool) -> None:
    monkeypatch.setattr(registry, "TOOLS", {tool.name: tool for tool in tools})


def _items(prefix: str, count: int) -> list[dict[str, Any]]:
    return [{"id": f"{prefix}-{i}", "name": f"{prefix} {i}"} for i in range(1, count + 1)]


def _run(
    llm: Any, profile: TripProfile | None = None, **kwargs: Any
) -> tuple[list[dict[str, str]], list[Finding]]:
    """Run the planner; return the status data and the findings (the last item)."""

    async def collect() -> tuple[list[dict[str, str]], list[Finding]]:
        statuses: list[dict[str, str]] = []
        findings: list[Finding] | None = None
        async for item in run_planner(llm, profile or _profile(), REQUEST, today=TODAY, **kwargs):
            assert findings is None, "the findings list must be the last item"
            if isinstance(item, list):
                findings = item
            else:
                assert item["event"] == "status"
                statuses.append(json.loads(item["data"]))
        assert findings is not None
        return statuses, findings

    return asyncio.run(asyncio.wait_for(collect(), timeout=30))


def _assert_status_pairs(statuses: list[dict[str, str]]) -> None:
    """Every start gets exactly one later end/error; no label starts twice."""
    open_labels: set[str] = set()
    started: list[str] = []
    for status in statuses:
        label, state = status["label"], status["state"]
        if state == "start":
            assert label not in started, f"label used twice: {label}"
            started.append(label)
            open_labels.add(label)
        else:
            assert state in ("end", "error"), status
            assert label in open_labels, f"{state} without an open start: {label}"
            open_labels.remove(label)
    assert open_labels == set(), f"never ended: {open_labels}"


def _call_labels(statuses: list[dict[str, str]]) -> list[str]:
    return [s["label"] for s in statuses if s["state"] == "start" and s["label"] != CHOOSING_LABEL]


def _plan() -> Itinerary:
    draft = ItineraryDraft.model_validate(load_fake_data("draft_sanjose_v1"))
    plan = build_itinerary(draft, [], _profile(), None)
    assert isinstance(plan, Itinerary), plan
    return plan


def _parse_sse(text: str) -> list[Event]:
    events: list[Event] = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        name, data = "message", []
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data.append(line[len("data:"):].lstrip(" "))
        if data:
            events.append((name, json.loads("\n".join(data))))
    return events


def _statuses(events: list[Event]) -> list[dict[str, Any]]:
    return [data for name, data in events if name == "status"]


# --- parallel calls -------------------------------------------------------------------------


def test_calls_in_one_round_run_at_the_same_time(monkeypatch: pytest.MonkeyPatch) -> None:
    # Each tool waits until the other one is running too; run one after the other, the
    # barrier times out and both fail.
    barrier = threading.Barrier(2, timeout=BARRIER_TIMEOUT)

    def waiting(name: str) -> Callable[..., ToolResult]:
        def run() -> ToolResult:
            barrier.wait()
            return tool_ok([{"id": name, "name": name}])
        return run

    _use_tools(monkeypatch, _tool("tool_a", waiting("a")), _tool("tool_b", waiting("b")))
    llm = ScriptedPlanner([[_call("tool_a"), _call("tool_b")]])

    statuses, findings = _run(llm)

    assert [f.data["id"] for f in findings] == ["a", "b"]
    assert all(s["state"] != "error" for s in statuses)


def test_results_come_back_in_call_order_not_finish_order(monkeypatch: pytest.MonkeyPatch) -> None:
    barrier = threading.Barrier(2, timeout=BARRIER_TIMEOUT)

    def slow() -> ToolResult:
        barrier.wait()
        time.sleep(0.2)  # finishes last
        return tool_ok([{"id": "slow"}])

    def fast() -> ToolResult:
        barrier.wait()
        return tool_ok([{"id": "fast"}])

    _use_tools(monkeypatch, _tool("slow", slow), _tool("fast", fast))
    llm = ScriptedPlanner([[_call("slow"), _call("fast")], []])

    statuses, findings = _run(llm)

    assert [f.data["id"] for f in findings] == ["slow", "fast"]
    replies = llm.seen_rounds[1][0].results
    assert [json.loads(r)[0]["id"] for r in replies] == ["slow", "fast"]
    # Status lines come as they happen: both starts first, the fast one ends first.
    call_events = [s for s in statuses if s["label"] != CHOOSING_LABEL]
    assert [s["state"] for s in call_events] == ["start", "start", "end", "end"]
    assert call_events[2]["label"] == "Looking up fast"


def test_weather_for_several_cities_runs_in_parallel(monkeypatch: pytest.MonkeyPatch) -> None:
    barrier = threading.Barrier(2, timeout=BARRIER_TIMEOUT)
    passed: list[str] = []

    def waiting_weather(city: str, start: date, end: date, today: date | None = None) -> ToolResult:
        barrier.wait()
        passed.append(city)
        return tool_ok({"place": {"lat": 1.0, "lng": 2.0}, "days": []})

    monkeypatch.setattr(pipeline, "city_weather", waiting_weather)
    profile = _profile(cities=["San Jose, CA", "San Francisco, CA"])

    async def collect() -> list[CityWeather]:
        return [
            item async for item in pipeline.gather_weather(profile, TODAY)
            if isinstance(item, CityWeather)
        ]

    cities = asyncio.run(asyncio.wait_for(collect(), timeout=30))

    assert sorted(passed) == ["San Francisco, CA", "San Jose, CA"]
    assert [c.name for c in cities] == ["San Jose, CA", "San Francisco, CA"]  # profile order
    assert all(c.error is None for c in cities)


# --- caps and stopping ----------------------------------------------------------------------


def test_only_the_first_six_calls_of_a_round_run(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[int] = []
    lock = threading.Lock()

    def counting(number: int) -> ToolResult:
        with lock:
            ran.append(number)
        return tool_ok([{"id": f"item-{number}"}])

    _use_tools(monkeypatch, _tool("count", counting))
    calls = [_call("count", n, number=n) for n in range(1, 9)]  # 8 calls
    llm = ScriptedPlanner([calls, []])

    statuses, findings = _run(llm)

    assert sorted(ran) == [1, 2, 3, 4, 5, 6]
    assert len(findings) == 6
    assert len(_call_labels(statuses)) == 6
    # The model sees all 8 calls back, the last 2 with the skipped reply, in order.
    (round_1,) = llm.seen_rounds[1]
    assert [c.id for c in round_1.calls] == [c.id for c in calls]
    assert len(round_1.results) == 8
    assert round_1.results[6:] == [SKIPPED_REPLY, SKIPPED_REPLY]
    assert SKIPPED_REPLY == "skipped: limit"
    assert all(r != SKIPPED_REPLY for r in round_1.results[:6])


def test_at_most_three_rounds(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[str] = []
    _use_tools(monkeypatch, _tool("again", lambda: ran.append("x") or tool_ok([{"id": "x"}])))
    llm = ScriptedPlanner([[_call("again")]], repeat=True)  # would ask forever

    statuses, findings = _run(llm)

    assert len(llm.seen_rounds) == 3
    assert len(ran) == 3
    assert len(findings) == 3
    assert statuses[-1] == {"label": CHOOSING_LABEL, "state": "end"}


def test_loop_stops_when_the_model_asks_for_no_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_tools(monkeypatch, _tool("once", lambda: tool_ok([{"id": "x"}])))
    llm = ScriptedPlanner([[_call("once")], []])

    _run(llm)

    assert len(llm.seen_rounds) == 2
    assert len(llm.seen_rounds[1]) == 1  # round 2 saw round 1's result


def test_no_tools_asked_gives_only_the_choosing_line_and_no_findings() -> None:
    llm = ScriptedPlanner([[]])

    statuses, findings = _run(llm)

    assert statuses == [
        {"label": CHOOSING_LABEL, "state": "start"},
        {"label": CHOOSING_LABEL, "state": "end"},
    ]
    assert findings == []


def test_tools_come_from_the_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_tools(monkeypatch, _tool("one", lambda: tool_ok([])), _tool("two", lambda: tool_ok([])))
    llm = ScriptedPlanner([[]])

    _run(llm)

    assert llm.seen_tools == [["one", "two"]]


# --- failures -------------------------------------------------------------------------------


def test_a_failed_tool_does_not_stop_the_planning(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> ToolResult:
        raise RuntimeError("boom")

    _use_tools(
        monkeypatch,
        _tool("good", lambda: tool_ok([{"id": "good"}])),
        _tool("bad", lambda: tool_error("Service down")),
        _tool("boom", boom),
    )
    llm = ScriptedPlanner([
        [_call("good"), _call("bad"), _call("boom"), _call("not_a_tool")],
        [_call("good", 2)],
        [],
    ])

    statuses, findings = _run(llm)

    # Planning went on to round 2 and 3; only ok results give findings.
    assert len(llm.seen_rounds) == 3
    assert [f.data["id"] for f in findings] == ["good", "good"]
    replies = llm.seen_rounds[1][0].results
    assert json.loads(replies[0])[0]["id"] == "good"
    for reply in replies[1:]:
        assert "error" in json.loads(reply)
    assert "Service down" in json.loads(replies[1])["error"]
    states = {s["label"]: s["state"] for s in statuses if s["state"] != "start"}
    assert states["Looking up bad"] == "error"
    assert states["Looking up boom"] == "error"
    assert states["Looking up good"] == "end"
    assert states[CHOOSING_LABEL] == "end"
    _assert_status_pairs(statuses)


def test_a_failing_tool_turn_ends_the_loop_but_keeps_what_was_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_tools(monkeypatch, _tool("good", lambda: tool_ok([{"id": "good"}])))
    llm = ScriptedPlanner([[_call("good")], RuntimeError("LLM down")])

    statuses, findings = _run(llm)

    assert [f.data["id"] for f in findings] == ["good"]
    assert statuses[-1] == {"label": CHOOSING_LABEL, "state": "error"}
    _assert_status_pairs(statuses)


def test_generation_still_saves_a_plan_when_every_planner_tool_fails(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(**arguments: Any) -> ToolResult:
        raise RuntimeError("boom")

    _use_tools(monkeypatch, _tool("search_places", boom))
    session_id = repo.create_session(db).id

    async def collect() -> list[dict[str, str]]:
        return [
            event
            async for event in pipeline.run_generation(
                db, session_id, FakeProvider(), _profile(), [], on_saved=lambda _: None,
                today=TODAY,
            )
        ]

    events = asyncio.run(collect())

    statuses = [json.loads(e["data"]) for e in events if e["event"] == "status"]
    assert {"label": "Finding food spots in San Jose", "state": "error"} in statuses
    assert events[-1]["event"] == "itinerary"
    assert repo.get_latest_itinerary(db, session_id) is not None


# --- edits ----------------------------------------------------------------------------------


def test_a_move_edit_makes_no_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[dict[str, Any]] = []
    _use_tools(
        monkeypatch,
        _tool("search_places", lambda **arguments: ran.append(arguments) or tool_ok([])),
    )

    statuses, findings = _run(
        FakeProvider(), current_plan=_plan(), change_request="move [E] to day 2"
    )

    assert ran == []
    assert findings == []
    assert statuses == [
        {"label": CHOOSING_LABEL, "state": "start"},
        {"label": CHOOSING_LABEL, "state": "end"},
    ]


def test_the_same_profile_without_an_edit_does_search(monkeypatch: pytest.MonkeyPatch) -> None:
    # Guards the edit test above: the fake planner does ask for tools on a generate.
    ran: list[dict[str, Any]] = []
    _use_tools(
        monkeypatch,
        _tool("search_places", lambda **arguments: ran.append(arguments) or tool_ok([])),
    )

    _run(FakeProvider())

    assert sorted(a["interest"] for a in ran) == ["food", "tech"]


def test_planner_system_has_profile_weather_plan_and_change_request() -> None:
    weather = CityWeather(
        name="San Jose, CA", lat=37.3, lng=-121.9,
        days={START: DayWeather(high_f=66, low_f=48, condition="sunny", icon="?", source="forecast")},
    )
    llm = ScriptedPlanner([[]])

    _run(llm, weather=[weather], current_plan=_plan(), change_request="move [E] to day 2")

    (system,) = llm.systems
    assert "San Jose, CA" in system
    assert '"interests":["tech","food"]' in system.replace(" ", "")
    assert "sunny" in system
    assert "San Pedro Square" in system  # the current plan's [E]
    assert "move [E] to day 2" in system


def test_planner_system_for_a_generate_has_no_plan_or_change_request() -> None:
    llm = ScriptedPlanner([[]])

    _run(llm, current_plan=_plan())  # a plan without a change request is not an edit

    (system,) = llm.systems
    assert "San Pedro Square" not in system
    assert "Change request:" not in system


def test_fake_planner_markers_match_the_planner_markers() -> None:
    # The fake keeps copies (llm/ doesn't import agent/); they must stay equal.
    assert fake_provider.PLANNER_PROFILE_MARKER == planner.PLANNER_PROFILE_MARKER
    assert fake_provider.PLANNER_EDIT_MARKER == planner.PLANNER_EDIT_MARKER


def test_a_move_edit_through_the_api_shows_no_places_lines(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    ran: list[dict[str, Any]] = []
    original = registry.TOOLS["search_places"]

    def spy(**arguments: Any) -> ToolResult:
        ran.append(arguments)
        return original.function(**arguments)

    _use_tools(monkeypatch, _tool("search_places", spy))
    provider = FakeProvider()
    client.app.dependency_overrides[get_llm] = lambda: TurnLlms(provider, provider)  # type: ignore[attr-defined]
    session_id = client.post("/api/sessions").json()["id"]
    client.post(f"/api/sessions/{session_id}/messages", json={"content": TRIP_MESSAGE})
    client.post(f"/api/sessions/{session_id}/generate", json={})
    searches_for_generate = len(ran)

    response = client.post(
        f"/api/sessions/{session_id}/messages", json={"content": "move [E] to day 2"}
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert any(name == "itinerary" for name, _ in events)  # it really was an edit
    assert searches_for_generate == 3
    assert len(ran) == 3  # no more searches
    labels = {s["label"] for s in _statuses(events)}
    assert not any(label.startswith("Finding") for label in labels)


# --- refs -----------------------------------------------------------------------------------


def test_refs_are_unique_across_rounds_with_one_counter_per_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_tools(
        monkeypatch,
        _tool("search_places", lambda **a: tool_ok(_items(a["interest"], 2))),
        _tool("search_hotels", lambda **a: tool_ok(_items("hotel", 2))),
        _tool("other", lambda: tool_ok({"id": "single"})),
    )
    city = "San Jose, CA"
    llm = ScriptedPlanner([
        [
            _call("search_places", 1, city=city, interest="food"),
            _call("search_hotels", 1, city=city),
            _call("other"),
        ],
        [_call("search_places", 2, city=city, interest="tech")],
        [],
    ])

    _, findings = _run(llm)

    refs = [f.ref for f in findings]
    assert refs == ["p1", "p2", "h1", "h2", "r1", "p3", "p4"]
    assert len(set(refs)) == len(refs)
    assert [f.tool for f in findings] == [
        "search_places", "search_places", "search_hotels", "search_hotels", "other",
        "search_places", "search_places",
    ]
    # Data is the item exactly as the tool gave it.
    assert findings[0].data == {"id": "food-1", "name": "food 1"}
    assert findings[5].data == {"id": "tech-1", "name": "tech 1"}


def test_the_model_sees_the_refs_in_the_tool_replies(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_tools(
        monkeypatch,
        _tool("search_places", lambda **a: tool_ok(_items(a["interest"], 2))),
        _tool("bad", lambda: tool_error("nope")),
    )
    llm = ScriptedPlanner([
        [_call("search_places", 1, city="San Jose, CA", interest="food"), _call("bad")],
        [_call("search_places", 2, city="San Jose, CA", interest="tech")],
        [],
    ])

    _, findings = _run(llm)

    first = llm.seen_rounds[1][0].results
    assert json.loads(first[0]) == [
        {"ref": "p1", "id": "food-1", "name": "food 1"},
        {"ref": "p2", "id": "food-2", "name": "food 2"},
    ]
    assert json.loads(first[1]) == {"error": "nope"}  # a failed result gets no ref
    second = llm.seen_rounds[2][1].results
    assert [item["ref"] for item in json.loads(second[0])] == ["p3", "p4"]
    assert [f.ref for f in findings] == ["p1", "p2", "p3", "p4"]


# --- status lines ---------------------------------------------------------------------------


def test_status_lines_pair_up_with_unique_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(**arguments: Any) -> ToolResult:
        raise RuntimeError("boom")

    _use_tools(
        monkeypatch,
        _tool("search_places", lambda **a: tool_ok(_items("place", 1))),
        _tool("search_hotels", boom),
    )
    city = "San Jose, CA"
    food = {"city": city, "interest": "food"}
    llm = ScriptedPlanner([
        # The same search twice in one round, and again in the next round.
        [_call("search_places", 1, **food), _call("search_places", 2, **food),
         _call("search_hotels", 1, city=city)],
        [_call("search_places", 3, **food), _call("search_hotels", 2, city=city)],
        [],
    ])

    statuses, _ = _run(llm)

    _assert_status_pairs(statuses)
    labels = _call_labels(statuses)
    assert len(labels) == 5
    assert len(set(labels)) == 5
    assert sum(label.startswith("Finding food spots in San Jose") for label in labels) == 3
    assert sum(label.startswith("Finding hotels in San Jose") for label in labels) == 2
    # One Choosing line spans the whole loop.
    assert statuses[0] == {"label": CHOOSING_LABEL, "state": "start"}
    assert statuses[-1] == {"label": CHOOSING_LABEL, "state": "end"}
    assert [s["label"] for s in statuses].count(CHOOSING_LABEL) == 2


def test_places_label_names_the_interest_and_short_city(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_tools(monkeypatch, _tool("search_places", lambda **a: tool_ok([])))
    llm = ScriptedPlanner([[_call("search_places", city="San Jose, CA", interest="food")]])

    statuses, _ = _run(llm)

    assert {"label": "Finding food spots in San Jose", "state": "start"} in statuses
    assert {"label": "Finding food spots in San Jose", "state": "end"} in statuses


# --- with the fake LLM through the API ------------------------------------------------------


def test_generate_through_the_api_shows_the_places_status_lines(client: TestClient) -> None:
    provider = FakeProvider()
    client.app.dependency_overrides[get_llm] = lambda: TurnLlms(provider, provider)  # type: ignore[attr-defined]
    session_id = client.post("/api/sessions").json()["id"]
    client.post(f"/api/sessions/{session_id}/messages", json={"content": TRIP_MESSAGE})

    response = client.post(f"/api/sessions/{session_id}/generate", json={})

    assert response.status_code == 200
    events = _parse_sse(response.text)
    statuses = _statuses(events)
    _assert_status_pairs(statuses)
    for label in PLACES_LABELS:
        assert {"label": label, "state": "start"} in statuses
        assert {"label": label, "state": "end"} in statuses  # mock places search is ok
    labels = [s["label"] for s in statuses]
    # The planner runs after weather and before the draft.
    assert labels.index(CHOOSING_LABEL) < labels.index(pipeline.DRAFTING_LABEL)
    assert all(labels.index(label) < labels.index(pipeline.DRAFTING_LABEL) for label in PLACES_LABELS)
    weather_labels = [label for label in labels if label.startswith("Checking weather")]
    assert weather_labels and labels.index(weather_labels[0]) < labels.index(CHOOSING_LABEL)
    assert any(name == "itinerary" for name, _ in events)


def test_run_planner_with_the_fake_and_mock_places_numbers_real_results() -> None:
    statuses, findings = _run(FakeProvider(), _profile(interests=["food"]))

    assert findings, "the mock places search should give results"
    assert [f.ref for f in findings] == [f"p{i}" for i in range(1, len(findings) + 1)]
    assert all(f.tool == "search_places" for f in findings)
    assert all({"id", "name", "lat", "lng"} <= set(f.data) for f in findings)
    assert _call_labels(statuses) == ["Finding food spots in San Jose"]
