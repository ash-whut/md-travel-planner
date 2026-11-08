"""The tools the planner agent may call (D24): the only list of planner tools.

Each entry has a name, a one-line description, a JSON schema for its arguments and the
function. The agent turns an entry into an LLM `ToolSpec(name, description, parameters)`;
this module stays free of LLM code. The shape matches an MCP server's tool list, so wrapping
it later (stretch step 50) is a thin layer.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.tools import places
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

TOOLS: dict[str, Tool] = {tool.name: tool for tool in [SEARCH_PLACES]}


def run_tool(name: str, arguments: dict[str, Any]) -> ToolResult:
    """Call a registry tool with the model's arguments. An unknown tool or bad arguments give
    an error result instead of raising."""
    tool = TOOLS.get(name)
    if tool is None:
        return tool_error(f"Unknown tool: {name}")
    try:
        return tool.function(**arguments)
    except TypeError as error:  # missing or unexpected arguments
        return tool_error(f"Bad arguments for {name}: {error}")
