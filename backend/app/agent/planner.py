"""The planner agent (D24, D25, architecture §4.1 step 2): the planner LLM picks its own tool
calls over a few rounds, and code runs each round's calls in parallel.

Code owns everything around the LLM: the round and call caps, the status lines, and the refs
(`p1`, `h1`…) that number every result item so compose can cite them.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.agent import context, sse
from app.agent.postprocess import CityWeather, short_city_name
from app.agent.sse import SseEvent
from app.llm.base import LLMProvider, Message, ToolCall, ToolRound, ToolSpec
from app.schemas.itinerary import Itinerary
from app.schemas.profile import TripProfile
from app.tools import registry
from app.tools.common import ToolResult, tool_error

MAX_ROUNDS = 3
MAX_CALLS_PER_ROUND = 6  # also keeps Geoapify under its 5 requests/second (D25)
CHOOSING_LABEL = "Choosing what to look up…"
SKIPPED_REPLY = "skipped: limit"
# The last user message of the planner's chat (the caller adds it, see run_planner).
PLANNER_REQUEST = "Look up what this plan needs now."
# Ref prefix per tool: places are p1, p2…, hotels h1, h2…; any other tool r1, r2….
REF_PREFIXES = {"search_places": "p", "search_hotels": "h"}
DEFAULT_REF_PREFIX = "r"
# The system text puts the profile JSON after this marker and the change request after the
# edit marker. The fake provider keeps copies (fake_provider.PLANNER_*_MARKER) to find them.
PLANNER_PROFILE_MARKER = "Trip profile (JSON):"
PLANNER_EDIT_MARKER = "Change request:"

# One parallel call: its status label, the tool function and its arguments.
ParallelCall = tuple[str, Callable[..., ToolResult], tuple[Any, ...]]


@dataclass
class Finding:
    """One result item a planner tool found, numbered by code.

    `ref` ("p1", "h1"…) is unique within one planner run; compose cites it and postprocess
    looks it up. `data` is the item exactly as the tool gave it (for `search_places`: id, name,
    address, lat, lng, category, rating).
    """

    ref: str
    tool: str
    data: dict[str, Any]


async def run_planner(
    llm: LLMProvider,
    profile: TripProfile,
    messages: list[Message],
    weather: list[CityWeather] | None = None,
    today: date | None = None,
    current_plan: Itinerary | None = None,
    change_request: str | None = None,
) -> AsyncIterator[SseEvent | list[Finding]]:
    """Run the planner's tool rounds. Yields status events, then the list of Findings (every
    numbered result item, in order) as the last item.

    `messages` is the chat ending with a user message (the pipeline adds PLANNER_REQUEST). With
    a `current_plan` and a `change_request` it is an edit. At most MAX_ROUNDS `tool_turn` calls;
    in each, only the first MAX_CALLS_PER_ROUND calls run (in parallel) and the rest get
    SKIPPED_REPLY. The loop stops early when the model asks for no tools. A tool that fails or
    raises gets an error reply and planning goes on. One `registry.PlanLimits` covers the whole
    run, so a second hotel search for a city gets "skipped: limit". If the `tool_turn` call
    itself fails, the loop stops and compose works with what was found so far.

    Status lines: CHOOSING_LABEL runs from the first round to the end of the loop, and every
    call that runs gets its own start → end/error line with a unique label.
    """
    system = build_system(profile, today, weather, current_plan, change_request)
    tools = tool_specs()
    rounds: list[ToolRound] = []
    findings: list[Finding] = []
    counts: dict[str, int] = {}  # ref prefix → how many refs it has given out
    used_labels = {CHOOSING_LABEL}
    limits = registry.PlanLimits()  # one hotel search per city in this plan (D29)

    yield sse.status(CHOOSING_LABEL, "start")
    choosing_state = "end"
    for _ in range(MAX_ROUNDS):
        try:
            calls = await llm.tool_turn(system, messages, rounds, tools)
        except Exception:  # the plan can still be made without (more) tool data
            choosing_state = "error"
            break
        if not calls:
            break

        to_run = calls[:MAX_CALLS_PER_ROUND]
        parallel_calls: list[ParallelCall] = [
            (unique_label(call_label(call), used_labels), registry.run_tool,
             (call.name, call.arguments, limits))
            for call in to_run
        ]
        results: list[ToolResult] = []
        async for item in run_parallel(parallel_calls):
            if isinstance(item, list):
                results = item
            else:
                yield item

        replies: list[str] = []
        for call, result in zip(to_run, results):
            numbered = number_items(call.name, result, counts)
            findings.extend(numbered)
            replies.append(tool_reply(result, numbered))
        replies += [SKIPPED_REPLY] * (len(calls) - len(to_run))
        rounds.append(ToolRound(calls=calls, results=replies))

    yield sse.status(CHOOSING_LABEL, choosing_state)
    yield findings


def build_system(
    profile: TripProfile,
    today: date | None = None,
    weather: list[CityWeather] | None = None,
    current_plan: Itinerary | None = None,
    change_request: str | None = None,
) -> str:
    """System text for the planner: its prompt plus today's date, the profile (as JSON), the
    weather and, for an edit, the current plan and the change request."""
    today = today or date.today()
    parts = [
        context.load_prompt("planner").strip(),
        "# Context",
        f"Today is {context.format_date(today)} ({today.isoformat()}).",
        f"## Trip profile\n{PLANNER_PROFILE_MARKER} {profile.model_dump_json()}",
    ]
    if weather:
        parts.append(context.render_weather(weather))
    if current_plan is not None and change_request:
        parts.append(context.compact_itinerary(current_plan))
        parts.append(f"## The traveler's change\n{PLANNER_EDIT_MARKER} {change_request}")
    return "\n\n".join(parts)


def tool_specs() -> list[ToolSpec]:
    """The registry tools as LLM ToolSpecs."""
    return [
        ToolSpec(name=tool.name, description=tool.description, parameters=tool.parameters)
        for tool in registry.TOOLS.values()
    ]


def call_label(call: ToolCall) -> str:
    """The status label for one tool call, e.g. "Finding food spots in San Jose"."""
    city = short_city_name(str(call.arguments.get("city", "")))
    if call.name == "search_places":
        return f"Finding {call.arguments.get('interest', 'places')} spots in {city}"
    if call.name == "search_hotels":
        return f"Finding hotels in {city}"
    return f"Looking up {call.name}"


def unique_label(label: str, used: set[str]) -> str:
    """`label`, or "label (2)", "label (3)"… if it was used already in this run. Adds the result
    to `used`. Status lines are keyed by label, so two calls must never share one."""
    candidate = label
    number = 2
    while candidate in used:
        candidate = f"{label} ({number})"
        number += 1
    used.add(candidate)
    return candidate


def number_items(tool: str, result: ToolResult, counts: dict[str, int]) -> list[Finding]:
    """Give every item of an ok result the next ref for its tool's prefix (counted in `counts`,
    so refs stay unique across rounds). A failed result has no items."""
    if not result.ok:
        return []
    items = result.data if isinstance(result.data, list) else [result.data]
    prefix = REF_PREFIXES.get(tool, DEFAULT_REF_PREFIX)
    findings: list[Finding] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        counts[prefix] = counts.get(prefix, 0) + 1
        findings.append(Finding(ref=f"{prefix}{counts[prefix]}", tool=tool, data=item))
    return findings


def tool_reply(result: ToolResult, numbered: list[Finding]) -> str:
    """The tool reply the model sees: the numbered items as JSON, or the error."""
    if not result.ok:
        return json.dumps({"error": result.error or "The tool failed."})
    return json.dumps([{"ref": finding.ref, **finding.data} for finding in numbered])


async def status(
    label: str, tool: Callable[..., ToolResult], *args: Any
) -> AsyncIterator[SseEvent | ToolResult]:
    """Run one tool call between `status` lines: start, then end (ok) or error (failed).

    Yields the two status events, then the ToolResult as the last item. The tool runs in a
    worker thread (tools are synchronous). A tool that raises counts as failed, so the pipeline
    can always carry on without that data. Use it like this:

        async for item in status("Checking weather…", weather.get_weather, lat, lng, start, end):
            if isinstance(item, ToolResult):
                result = item
            else:
                yield item
    """
    yield sse.status(label, "start")
    try:
        result = await asyncio.to_thread(tool, *args)
    except Exception as error:  # tools shouldn't raise, but one bad tool mustn't stop the plan
        result = tool_error(str(error) or type(error).__name__)
    yield sse.status(label, "end" if result.ok else "error")
    yield result


async def run_parallel(calls: list[ParallelCall]) -> AsyncIterator[SseEvent | list[ToolResult]]:
    """Run several tool calls at the same time (D25), each through `status()`.

    Yields every call's status events as they happen (starts first, then ends/errors in the
    order the calls finish), then the list of ToolResults in call order as the last item.
    """
    events: asyncio.Queue[SseEvent | None] = asyncio.Queue()
    results: list[ToolResult] = [tool_error("The tool did not run.")] * len(calls)

    async def run_one(
        index: int, label: str, tool: Callable[..., ToolResult], args: tuple[Any, ...]
    ) -> None:
        try:
            async for item in status(label, tool, *args):
                if isinstance(item, ToolResult):
                    results[index] = item
                else:
                    events.put_nowait(item)
        finally:
            events.put_nowait(None)  # this call is finished

    gathered = asyncio.gather(
        *(run_one(index, label, tool, args) for index, (label, tool, args) in enumerate(calls))
    )
    try:
        finished = 0
        while finished < len(calls):
            event = await events.get()
            if event is None:
                finished += 1
            else:
                yield event
        await gathered
    finally:
        gathered.cancel()  # only matters when the caller stops early (e.g. Stop)
    yield results
