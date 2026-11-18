"""Deterministic, offline LLM provider for tests and local dev (LLM_PROVIDER=fake)."""

import json
import re
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any

from app.llm.base import Message, T, ToolCall, ToolRound, ToolSpec
from app.schemas.itinerary import ItineraryDraft
from app.schemas.profile import TripProfile
from app.schemas.turn import TurnAnalysis

CANNED_REPLY = "Sounds fun! Tell me where you want to go, when, and who is coming along."
SUMMARY_REPLY = "Your plan is ready on the left! Ask me to change any stop by its letter."
# Matches the San Jose demo: v2 swaps Baconhouse [F] for Good Karma Kitchen [L].
EDIT_SUMMARY_REPLY = (
    "Done! I replaced [F] (Baconhouse) with [L] Good Karma Kitchen, a vegan brunch spot. "
    "Everything else stays the same."
)
FAKE_DATA_DIR = Path(__file__).parent / "fake_data"

# Keyword → interest label, for the scripted San Jose demo.
DEMO_INTERESTS = [("tech", "tech"), ("food", "food"), ("garden", "gardens")]
# Phrases that ask for the plan (action=generate).
GENERATE_PHRASES = ("generate", "make the plan", "make a plan", "make my plan")
# A message with a tag like [F] or one of these words asks for a change (action=edit). The turn
# turns an edit into chat when there is no plan yet (agent/turn.py), as architecture.md says.
EDIT_WORDS = ("replace", "change", "swap")
TAG_TOKEN = re.compile(r"\[[A-Z]{1,2}\]")
# The turn asks for a plan summary with these phrases (agent/turn.py SUMMARY_REQUEST and
# EDIT_SUMMARY_REQUEST).
SUMMARY_PHRASE = "just made the plan"
EDIT_SUMMARY_PHRASE = "just updated the plan"
# Compose asks for an edit with this phrase (agent/pipeline.py EDIT_REQUEST).
EDIT_PHRASE = "change only what was asked"
# Copies of agent/planner.py PLANNER_PROFILE_MARKER and PLANNER_EDIT_MARKER (llm/ doesn't import
# agent/): the planner's system text holds the profile JSON and the change request after them.
# The fake's tool_turn reads only `system`.
PLANNER_PROFILE_MARKER = "Trip profile (JSON):"
PLANNER_EDIT_MARKER = "Change request:"
# A found place in the compose system text (agent/pipeline.py render_places), e.g.
# "- p1 · The Tech Interactive · entertainment.museum · …": the ref and the name.
PLACE_LINE = re.compile(r"^- (p\d+) · (.+?) · ", re.MULTILINE)
# A found hotel in the compose system text (agent/pipeline.py render_hotels), e.g.
# "- h1 · Pacific Inn San Jose · $79/night · …": the ref and the name.
HOTEL_LINE = re.compile(r"^- (h\d+) · (.+?) · ", re.MULTILINE)
# A change request with one of these words adds or replaces a stop, so the fake planner looks one
# up; any other change (move, remove…) needs no tools, as prompts/planner.md says.
ADD_WORDS = ("replace", "swap", "change", "add", "instead")
# A change that mentions one of these asks for a food place.
FOOD_WORDS = ("vegan", "vegetarian", "food", "eat", "restaurant", "brunch", "lunch", "dinner",
              "breakfast")


class FakeProvider:
    name = "fake"

    def __init__(
        self,
        reply: str = CANNED_REPLY,
        drafts: list[dict[str, Any]] | None = None,
        summary_reply: str = SUMMARY_REPLY,
        edit_summary_reply: str = EDIT_SUMMARY_REPLY,
    ) -> None:
        """`drafts`: raw ItineraryDraft JSON replies to give, one per compose call, in order
        (tests use it for bad-then-good drafts). Once used up, the San Jose v1 draft is given,
        or the v2 draft for an edit; their stops cite the found places in the compose system
        text that share their name. `summary_reply` / `edit_summary_reply` are streamed instead
        of `reply` when the turn asks for a plan / edit summary."""
        self.reply = reply
        self.drafts = list(drafts or [])
        self.summary_reply = summary_reply
        self.edit_summary_reply = edit_summary_reply

    async def stream_text(self, system: str, messages: list[Message]) -> AsyncIterator[str]:
        last_text = last_user_text(messages).lower()
        if EDIT_SUMMARY_PHRASE in last_text:
            text = self.edit_summary_reply
        elif SUMMARY_PHRASE in last_text:
            text = self.summary_reply
        else:
            text = self.reply
        # One chunk per word (keeping the space) so callers see a real multi-chunk stream.
        words = text.split(" ")
        for i, word in enumerate(words):
            yield word if i == len(words) - 1 else word + " "

    async def complete_json(self, system: str, messages: list[Message], schema: type[T]) -> T:
        if schema is TurnAnalysis:
            return schema.model_validate(scripted_turn_analysis(last_user_text(messages)))
        if schema is ItineraryDraft:
            # Validated like a real reply, so a bad draft raises ValidationError.
            if self.drafts:
                draft = self.drafts.pop(0)
            elif EDIT_PHRASE in last_user_text(messages).lower():
                draft = cite_found_places(load_fake_data("draft_sanjose_v2"), system)
            else:
                draft = cite_found_places(load_fake_data("draft_sanjose_v1"), system)
            return schema.model_validate(draft)
        raise NotImplementedError(f"FakeProvider.complete_json has no scripted reply for {schema.__name__}")

    async def tool_turn(
        self, system: str, messages: list[Message], rounds: list[ToolRound], tools: list[ToolSpec]
    ) -> list[ToolCall]:
        """The scripted planner: in round 1 of a generate, `search_places` for each city ×
        interest, then `search_hotels` per city when the exact dates are known. In round 1 of an
        edit, one `search_places` in the first city when the change adds or replaces a stop (see
        `edit_search`), else none. Only tools in `tools` are asked for. A later round asks for
        none."""
        if rounds:
            return []
        profile = planner_profile(system)
        tool_names = {tool.name for tool in tools}
        wanted: list[tuple[str, dict[str, Any]]] = []
        if PLANNER_EDIT_MARKER in system:
            search = edit_search(change_request(system), profile)
            if "search_places" in tool_names and search is not None:
                return [ToolCall(id="call_1", name="search_places", arguments=search)]
            return []
        if "search_places" in tool_names:
            for city in profile.cities:
                for interest in profile.interests:
                    wanted.append(("search_places", {"city": city, "interest": interest}))
        dates = exact_dates(profile)
        if "search_hotels" in tool_names and dates:
            check_in, check_out = dates
            for city in profile.cities:
                wanted.append(("search_hotels", {"city": city, "check_in": check_in, "check_out": check_out}))
        return [
            ToolCall(id=f"call_{i}", name=name, arguments=arguments)
            for i, (name, arguments) in enumerate(wanted, start=1)
        ]


def load_fake_data(name: str) -> dict[str, Any]:
    """The JSON in `llm/fake_data/<name>.json`."""
    return json.loads((FAKE_DATA_DIR / f"{name}.json").read_text(encoding="utf-8"))


def cite_found_places(draft: dict[str, Any], system: str) -> dict[str, Any]:
    """Set `place_ref` on each stop whose name matches a found place listed in `system` (equal
    names, or one starts with the other: "San Pedro Square" ↔ "San Pedro Square Market"), as a
    real model would cite them. A lodging stop cites the found hotel with its name (the demo
    drafts name "Pacific Inn San Jose", the mock's cheapest well-rated hotel)."""
    found = [(ref, simple_name(name)) for ref, name in PLACE_LINE.findall(system)]
    hotels = [(ref, simple_name(name)) for ref, name in HOTEL_LINE.findall(system)]
    for stop in draft["stops"]:
        name = simple_name(stop["name"])
        if stop["kind"] == "lodging":
            stop["place_ref"] = matching_ref(name, hotels)
        else:
            stop["place_ref"] = matching_ref(name, found)
    return draft


def matching_ref(name: str, found: list[tuple[str, str]]) -> str | None:
    """The ref of the first found name equal to `name` or starting with it (or the reverse)."""
    return next(
        (
            ref
            for ref, found_name in found
            if found_name.startswith(name) or name.startswith(found_name)
        ),
        None,
    )


def simple_name(name: str) -> str:
    """Lowercase, no punctuation, single spaces (like agent/tags.normalize_name; the LLM layer
    doesn't import the agent)."""
    return " ".join(re.sub(r"[^\w\s]", "", name.lower()).split())


def planner_profile(system: str) -> TripProfile:
    """The profile JSON that follows PLANNER_PROFILE_MARKER in the planner's system text (an
    empty profile if there is none)."""
    start = system.find(PLANNER_PROFILE_MARKER)
    if start < 0:
        return TripProfile()
    data, _ = json.JSONDecoder().raw_decode(system[start + len(PLANNER_PROFILE_MARKER):].lstrip())
    return TripProfile.model_validate(data)


def change_request(system: str) -> str:
    """The change request: the rest of the line after PLANNER_EDIT_MARKER in the planner's
    system text ("" if there is none)."""
    start = system.find(PLANNER_EDIT_MARKER)
    if start < 0:
        return ""
    return system[start + len(PLANNER_EDIT_MARKER):].split("\n", 1)[0].strip()


def edit_search(change: str, profile: TripProfile) -> dict[str, Any] | None:
    """The `search_places` arguments for a change that adds or replaces a stop (an ADD_WORDS
    word), in the profile's first city; None for any other change or without a city.

    The interest is food (with the profile's dietary need, e.g. "vegan food") when the change
    mentions a FOOD_WORDS word, else the profile's first interest, else "sights"."""
    words = set(re.findall(r"[a-z]+", change.lower()))
    if not words & set(ADD_WORDS) or not profile.cities:
        return None
    if words & set(FOOD_WORDS):
        interest = f"{profile.dietary} food" if profile.dietary else "food"
    else:
        interest = profile.interests[0] if profile.interests else "sights"
    return {"city": profile.cities[0], "interest": interest}


def exact_dates(profile: TripProfile) -> tuple[str, str] | None:
    """The trip's first and last day as ISO strings, or None if they aren't known exactly."""
    if profile.start_date is None:
        return None
    if profile.end_date is not None:
        end = profile.end_date
    elif profile.duration_days is not None:
        end = profile.start_date + timedelta(days=profile.duration_days - 1)
    else:
        return None
    return profile.start_date.isoformat(), end.isoformat()


def last_user_text(messages: list[Message]) -> str:
    for message in reversed(messages):
        if message["role"] == "user":
            return message["content"]
    return ""


def scripted_turn_analysis(text: str) -> dict[str, Any]:
    """A TurnAnalysis for the San Jose demo (frontend/src/fixtures/sanjose-*.json), by keywords.

    Messages without demo keywords give no profile updates. Asking for the plan ("make the plan",
    "generate") gives action=generate; a tag or an edit word ("change [F] to something vegan",
    "replace H with something outdoors") gives action=edit with the message as the change
    request; everything else is chat. Without a plan the turn runs an edit as chat.
    """
    original_text = text
    text = text.lower()
    is_edit = TAG_TOKEN.search(original_text) is not None or any(
        re.search(rf"\b{word}\b", text) for word in EDIT_WORDS
    )
    updates: dict[str, Any] = {}
    if "san jose" in text:
        updates["cities"] = ["San Jose, CA"]
    if "college station" in text:
        updates["origin"] = "College Station, TX"
    if "first weekend of march" in text:
        updates.update(
            rough_timing="first weekend of March",
            start_date="2027-03-05",
            end_date="2027-03-07",
            duration_days=3,
        )
    if "just me" in text or "solo" in text:
        updates["travelers"] = 1
    interests = [label for keyword, label in DEMO_INTERESTS if keyword in text]
    if interests:
        updates["interests"] = interests
    if "vegan" in text:
        updates["dietary"] = "vegan"
    if is_edit:
        return {"profile_updates": updates, "action": "edit", "change_request": original_text}
    action = "generate" if any(phrase in text for phrase in GENERATE_PHRASES) else "chat"
    return {"profile_updates": updates, "action": action, "change_request": None}
