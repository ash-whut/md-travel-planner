"""The tools the planner agent may call (D24): the only list of planner tools.

Each entry has a name, a one-line description, a JSON schema for its arguments and the
function. The agent turns an entry into an LLM `ToolSpec(name, description, parameters)`;
this module stays free of LLM code. The shape matches an MCP server's tool list, so wrapping
it later (stretch step 50) is a thin layer.
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.tools import flights, hotels, places
from app.tools.common import ToolResult, tool_error


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema of the arguments
    function: Callable[..., ToolResult]


def search_places(city: str, interest: str) -> ToolResult:
    """Places for one interest in a city: geocode the city, then search around it."""
    located = places.geocode(city)
    if not located.ok:
        return located
    return places.search(located.data["lat"], located.data["lng"], interest)


SEARCH_PLACES = Tool(
    name="search_places",
    description="Find real places in a city for one interest (food, museums, gardens…).",
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": 'City with region, e.g. "San Jose, CA".'},
            "interest": {"type": "string", "description": 'One interest, e.g. "food" or "tech".'},
        },
        "required": ["city", "interest"],
        "additionalProperties": False,
    },
    function=search_places,
)


def search_hotels(city: str, check_in: str, check_out: str) -> ToolResult:
    """Hotels in a city for the whole stay, cheapest well-rated first, with prices when SerpApi
    is available."""
    return hotels.search(city, check_in, check_out)


SEARCH_HOTELS = Tool(
    name="search_hotels",
    description=(
        "Find hotels with prices in a city for the whole stay. Call it once per city; "
        "a second call for the same city is skipped."
    ),
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": 'City with region, e.g. "San Jose, CA".'},
            "check_in": {"type": "string", "description": "First night, YYYY-MM-DD."},
            "check_out": {"type": "string", "description": "Departure day, YYYY-MM-DD."},
        },
        "required": ["city", "check_in", "check_out"],
        "additionalProperties": False,
    },
    function=search_hotels,
)

def search_flights(
    origin: str, destination: str, departure_date: str, return_date: str
) -> ToolResult:
    """Flights between two cities with real fares."""
    return flights.search(origin, destination, departure_date, return_date)


SEARCH_FLIGHTS = Tool(
    name="search_flights",
    description="Find flights with real fares between two cities. Call once per route.",
    parameters={
        "type": "object",
        "properties": {
            "origin": {
                "type": "string",
                "description": '3-letter IATA airport code for origin (e.g. "SJC", "IAH", "AUS"). Never pass a city name.',
            },
            "destination": {
                "type": "string",
                "description": '3-letter IATA airport code for destination (e.g. "AUS", "SFO", "JFK"). Never pass a city name.',
            },
            "departure_date": {
                "type": "string",
                "description": "Departure date, YYYY-MM-DD.",
            },
            "return_date": {
                "type": "string",
                "description": "Return date, YYYY-MM-DD.",
            },
        },
        "required": ["origin", "destination", "departure_date", "return_date"],
        "additionalProperties": False,
    },
    function=search_flights,
)

TOOLS: dict[str, Tool] = {
    tool.name: tool for tool in [SEARCH_PLACES, SEARCH_HOTELS, SEARCH_FLIGHTS]
}

# Quota-limited tools that may run at most once per city in one plan (SerpApi's free plan is
# about 250 searches a month). The prompt asks for this too, but code enforces it.
ONCE_PER_CITY_TOOLS = {"search_hotels"}
# Quota-limited tools that may run at most once per route in one plan.
ONCE_PER_ROUTE_TOOLS = {"search_flights"}
LIMIT_REPLY = "skipped: limit"


class PlanLimits:
    """Per-plan call limits for quota-limited tools. Make one per plan (planner run) and pass it
    to every `run_tool` call of that plan. Thread-safe, since a round's calls run in parallel.
    """

    def __init__(self) -> None:
        self._used: set[tuple[str, str]] = set()
        self._lock = threading.Lock()

    def allow(self, name: str, arguments: dict[str, Any]) -> bool:
        """True if this call may run, and counts it; False once its tool has already run for
        this city (or route) in this plan. Tools without a limit are always allowed."""
        if name in ONCE_PER_CITY_TOOLS:
            key = (name, city_key(str(arguments.get("city", ""))))
        elif name in ONCE_PER_ROUTE_TOOLS:
            key = (name, route_key(arguments))
        else:
            return True
        with self._lock:
            if key in self._used:
                return False
            self._used.add(key)
            return True


def city_key(city: str) -> str:
    """The city part of a city argument, for the per-plan limit: "San Jose, CA" → "san jose"."""
    return " ".join(city.split(",")[0].lower().split())


def route_key(arguments: dict[str, Any]) -> str:
    """The route part of a flights argument, for the per-plan limit:
    "College Station, TX" → "San Jose, CA" → "college station>san jose"."""
    origin = city_key(str(arguments.get("origin", "")))
    destination = city_key(str(arguments.get("destination", "")))
    return f"{origin}>{destination}"


def run_tool(
    name: str, arguments: dict[str, Any], limits: PlanLimits | None = None
) -> ToolResult:
    """Call a registry tool with the model's arguments. An unknown tool or bad arguments give
    an error result instead of raising. With `limits`, a call over its plan limit is not run
    and gets an error result with LIMIT_REPLY."""
    tool = TOOLS.get(name)
    if tool is None:
        return tool_error(f"Unknown tool: {name}")
    if limits is not None and not limits.allow(name, arguments):
        return tool_error(LIMIT_REPLY)
    try:
        return tool.function(**arguments)
    except TypeError as error:  # missing or unexpected arguments
        return tool_error(f"Bad arguments for {name}: {error}")
