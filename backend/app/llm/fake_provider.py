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
# A found vacation rental line (render_hotels marks it "vacation rental"): the ref and the name.
RENTAL_LINE = re.compile(r"^- (h\d+) · (.+?) · .*vacation rental", re.MULTILINE)
# A found hotel or rental with a price: the ref, the name and the price per night.
PRICED_HOTEL_LINE = re.compile(r"^- (h\d+) · (.+?) · \$([\d.]+)/night", re.MULTILINE)
# The current plan in the compose system text for an edit (agent/pipeline.py build_system): this
# heading, a line of text, then the plan as ItineraryDraft JSON.
CURRENT_PLAN_MARKER = "## Current plan (version"
# A chat that mentions one of these asks for a vacation rental: the fake compose then makes the
# lodging stop the first found rental instead of the demo hotel (the offline rental scenario).
# Not "rental" alone: "car rental" isn't lodging.
RENTAL_WORDS = ("airbnb", "apartment", "vacation rental")
# A found flight in the compose system text (agent/pipeline.py render_flights), e.g.
# "- f1 · United Airlines UA 1234 · $189 · …": the ref.
FLIGHT_LINE = re.compile(r"^- (f\d+) · (.+?) · ", re.MULTILINE)
# A change request with one of these words adds or replaces a stop, so the fake planner looks one
# up; any other change (move, remove…) needs no tools, as prompts/planner.md says.
ADD_WORDS = ("replace", "swap", "change", "add", "instead")
# A change that mentions one of these asks for a food place.
FOOD_WORDS = ("vegan", "vegetarian", "food", "eat", "restaurant", "brunch", "lunch", "dinner",
              "breakfast")
# A change with one of these words (or "vacation rental") is about the stay, so the fake planner
# looks up hotels instead of places, as prompts/planner.md says (step 52).
STAY_WORDS = ("hotel", "hotels", "stay", "airbnb", "apartment")
STAY_PHRASE = "vacation rental"
# An edit with this phrase makes the fake compose pick the cheapest other hotel.
CHEAPER_HOTEL_PHRASE = "cheaper hotel"


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
        or the v2 draft for an edit (its lodging set by `choose_edit_lodging`); their stops
        cite the found places in the compose system text that share their name. `summary_reply` / `edit_summary_reply` are streamed instead
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
                draft = choose_edit_lodging(draft, system, last_user_text(messages))
            else:
                draft = cite_found_places(
                    load_fake_data("draft_sanjose_v1"), system, asks_for_rental(messages)
                )
            return schema.model_validate(draft)
        raise NotImplementedError(f"FakeProvider.complete_json has no scripted reply for {schema.__name__}")

    async def tool_turn(
        self, system: str, messages: list[Message], rounds: list[ToolRound], tools: list[ToolSpec]
    ) -> list[ToolCall]:
        """The scripted planner: in round 1 of a generate, `search_places` for each city ×
        interest, then `search_hotels` per city when the exact dates are known. In round 1 of an
        edit: one `search_hotels` in the first city when the change is about the stay (see
        `is_stay_change`; needs the exact dates), else one `search_places` in the first city
        when the change adds or replaces a stop (see `edit_search`), else none. Only tools in
        `tools` are asked for. A later round asks for none."""
        if rounds:
            return []
        profile = planner_profile(system)
        tool_names = {tool.name for tool in tools}
        wanted: list[tuple[str, dict[str, Any]]] = []
        if PLANNER_EDIT_MARKER in system:
            change = change_request(system)
            if is_stay_change(change):
                name, search = "search_hotels", edit_hotel_search(profile)
            else:
                name, search = "search_places", edit_search(change, profile)
            if name in tool_names and search is not None:
                return [ToolCall(id="call_1", name=name, arguments=search)]
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
        if "search_flights" in tool_names and dates and profile.origin and profile.cities:
            dep_date, ret_date = dates
            wanted.append(("search_flights", {
                "origin": profile.origin,
                "destination": profile.cities[0],
                "departure_date": dep_date,
                "return_date": ret_date,
            }))
        return [
            ToolCall(id=f"call_{i}", name=name, arguments=arguments)
            for i, (name, arguments) in enumerate(wanted, start=1)
        ]


def load_fake_data(name: str) -> dict[str, Any]:
    """The JSON in `llm/fake_data/<name>.json`."""
    return json.loads((FAKE_DATA_DIR / f"{name}.json").read_text(encoding="utf-8"))


def cite_found_places(
    draft: dict[str, Any], system: str, want_rental: bool = False
) -> dict[str, Any]:
    """Set `place_ref` on each stop whose name matches a found place listed in `system` (equal
    names, or one starts with the other: "San Pedro Square" ↔ "San Pedro Square Market"), as a
    real model would cite them. A lodging stop cites the found hotel with its name (the demo
    drafts name "Pacific Inn San Jose", the mock's cheapest well-rated hotel); with
    `want_rental` and a found vacation rental, it becomes that rental (name and ref) instead.
    The first airport stop (kind "airport") that isn't the return leg cites the first flight
    ref found."""
    found = [(ref, simple_name(name)) for ref, name in PLACE_LINE.findall(system)]
    hotels = [(ref, simple_name(name)) for ref, name in HOTEL_LINE.findall(system)]
    rentals = RENTAL_LINE.findall(system) if want_rental else []
    flights = [ref for ref, _name in FLIGHT_LINE.findall(system)]
    flight_iter = iter(flights)
    for stop in draft["stops"]:
        name = simple_name(stop["name"])
        if stop["kind"] == "lodging" and rentals:
            stop["place_ref"], stop["name"] = rentals[0]
        elif stop["kind"] == "lodging":
            stop["place_ref"] = matching_ref(name, hotels)
        elif stop["kind"] == "airport":
            # Give the first airport the first flight ref (the departure); leave the rest null.
            stop["place_ref"] = next(flight_iter, None)
        else:
            stop["place_ref"] = matching_ref(name, found)
    return draft


def choose_edit_lodging(draft: dict[str, Any], system: str, request: str) -> dict[str, Any]:
    """The lodging stop of an edit draft, by the edit `request` (step 52):
    - it asks for a rental (a RENTAL_WORDS word) and a rental was found → the first rental;
    - it says "cheaper hotel" → the cheapest priced hotel (not a rental) that costs less per
      night than the current lodging, when there is one;
    - otherwise the current plan's lodging name, citing it only if it was found again (with no
      ref, the pipeline keeps the earlier version's place and tool price, D30).
    The fake v2 draft always names the demo hotel, so without this an edit of a rental plan
    would rename the stay."""
    text = request.lower()
    current, current_price = current_lodging(system)
    rentals = RENTAL_LINE.findall(system)
    hotels = [(ref, simple_name(name)) for ref, name in HOTEL_LINE.findall(system)]
    cheaper = cheaper_hotel(system, current, current_price)
    for stop in draft["stops"]:
        if stop["kind"] != "lodging":
            continue
        if rentals and any(word in text for word in RENTAL_WORDS):
            stop["place_ref"], stop["name"] = rentals[0]
        elif CHEAPER_HOTEL_PHRASE in text and cheaper is not None:
            stop["place_ref"], stop["name"] = cheaper
        elif current is not None:
            stop["name"] = current
            stop["place_ref"] = matching_ref(simple_name(current), hotels)
    return draft


def current_lodging(system: str) -> tuple[str | None, float | None]:
    """The name and per-night price of the first lodging stop in the current plan of an edit's
    compose system text (after CURRENT_PLAN_MARKER); None for what isn't there."""
    start = system.find(CURRENT_PLAN_MARKER)
    brace = system.find("{", start) if start >= 0 else -1
    if brace < 0:
        return None, None
    plan, _ = json.JSONDecoder().raw_decode(system[brace:])
    stop = next((s for s in plan.get("stops", []) if s.get("kind") == "lodging"), None)
    if stop is None:
        return None, None
    stay = next((s for s in plan.get("lodging", []) if s.get("stop_key") == stop["key"]), {})
    price = (stay.get("price_per_night") or {}).get("amount")
    return stop["name"], float(price) if price is not None else None


def cheaper_hotel(
    system: str, current: str | None, current_price: float | None
) -> tuple[str, str] | None:
    """(ref, name) of the cheapest priced hotel found (rentals left out) that costs strictly
    less per night than `current_price`; None when none does or the current price is unknown."""
    if current_price is None:
        return None
    rental_refs = {ref for ref, _name in RENTAL_LINE.findall(system)}
    current_name = simple_name(current) if current else None
    priced = [
        (float(price), ref, name)
        for ref, name, price in PRICED_HOTEL_LINE.findall(system)
        if ref not in rental_refs
        and simple_name(name) != current_name
        and float(price) < current_price
    ]
    if not priced:
        return None
    _price, ref, name = min(priced)
    return ref, name


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


def is_stay_change(change: str) -> bool:
    """True when a change request is about the stay: a STAY_WORDS word or "vacation rental"
    ("swap the hotel for an Airbnb", "find a cheaper hotel")."""
    text = change.lower()
    return bool(set(re.findall(r"[a-z]+", text)) & set(STAY_WORDS)) or STAY_PHRASE in text


def edit_hotel_search(profile: TripProfile) -> dict[str, Any] | None:
    """The `search_hotels` arguments for a stay change: the profile's first city over the
    trip's dates; None without a city or exact dates."""
    dates = exact_dates(profile)
    if not profile.cities or dates is None:
        return None
    check_in, check_out = dates
    return {"city": profile.cities[0], "check_in": check_in, "check_out": check_out}


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


def asks_for_rental(messages: list[Message]) -> bool:
    """True when a user message mentions a RENTAL_WORDS word ("we'd like an Airbnb")."""
    return any(
        word in message["content"].lower()
        for message in messages
        if message["role"] == "user"
        for word in RENTAL_WORDS
    )


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
    request; so does "cheaper" with a stay word ("find a cheaper hotel", "a cheaper place to
    stay"). Everything else is chat. Without a plan the turn runs an edit as chat.
    """
    original_text = text
    text = text.lower()
    words = set(re.findall(r"[a-z]+", text))
    is_edit = (
        TAG_TOKEN.search(original_text) is not None
        or any(re.search(rf"\b{word}\b", text) for word in EDIT_WORDS)
        or ("cheaper" in words and bool(words & set(STAY_WORDS)))
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
