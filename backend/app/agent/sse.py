"""Tiny helpers that build SSE events (contracts §5).

Each helper returns a dict that sse-starlette's EventSourceResponse sends as
`event: <name>` + `data: <json>`.
"""

import json
from typing import Any

SseEvent = dict[str, str]


def sse_event(name: str, data: dict[str, Any]) -> SseEvent:
    return {"event": name, "data": json.dumps(data)}


def message_start(message_id: str) -> SseEvent:
    return sse_event("message_start", {"message_id": message_id})


def token(text: str) -> SseEvent:
    return sse_event("token", {"text": text})


def profile(trip_profile: dict[str, Any]) -> SseEvent:
    """The full TripProfile (JSON-ready dict) after it changed."""
    return sse_event("profile", trip_profile)


def status(label: str, state: str) -> SseEvent:
    """A pipeline activity line; `state` is "start", "end" or "error"."""
    return sse_event("status", {"label": label, "state": state})


def itinerary(plan: dict[str, Any]) -> SseEvent:
    """The full Itinerary (JSON-ready dict) after a new version was saved."""
    return sse_event("itinerary", plan)


def done(message_id: str) -> SseEvent:
    return sse_event("done", {"message_id": message_id})


def error(message: str, retryable: bool = True) -> SseEvent:
    return sse_event("error", {"message": message, "retryable": retryable})
