"""Generate route (03-contracts §3, §4; 04 §4.0): POST /api/sessions/{id}/generate streams SSE."""

import datetime as dt
import json

import pytest
from helpers import FakeEndpoint, make_provider, parse_sse, sse_response, stream_of
from sqlmodel import Session

from app.agent import orchestrator
from app.agent.fixed_messages import GREETING, PLAN_READY
from app.core.config import Settings, get_settings
from app.db.tables import SessionRow
from app.llm import ChatMessage, LLMError
from app.llm.fake_provider import FIXTURES_DIR as LLM_FIXTURES
from app.main import app
from app.schemas import ItineraryDraft

DRAFT_JSON = (LLM_FIXTURES / "itinerary_draft.json").read_text(encoding="utf-8")
EVENTS = ["message_start", "status", "itinerary", "token", "done"]


def generate(client, session_id: str) -> list[tuple[str, dict]]:
    response = client.post(f"/api/sessions/{session_id}/generate", json={})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    return parse_sse(response.text)


def names(events: list[tuple[str, dict]]) -> list[str]:
    return [name for name, _ in events]


def detail(client, session_id: str) -> dict:
    return client.get(f"/api/sessions/{session_id}").json()


class DraftProvider:
    """Records `generate_json` calls; returns the fake fixture's draft, or raises `error`."""

    name = "fake"

    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls: list[dict] = []

    async def generate_json(self, *, system: str, messages: list[ChatMessage], schema):
        self.calls.append({"system": system, "messages": list(messages), "schema": schema})
        if self.error:
            raise self.error
        return schema.model_validate_json(DRAFT_JSON)


@pytest.fixture
def new_session(client) -> dict:
    return client.post("/api/sessions").json()


@pytest.fixture
def use_provider(monkeypatch):
    """Make generation use the given provider instead of the one LLM_PROVIDER picks."""

    def install(provider):
        monkeypatch.setattr(orchestrator, "get_provider", lambda _settings: provider)
        return provider

    return install


# --- happy path (LLM_PROVIDER=fake) ----------------------------------------------------------


def test_events_in_order_with_tagged_itinerary(client, new_session):
    events = generate(client, new_session["id"])

    assert names(events) == EVENTS
    data = dict(events)
    assert data["message_start"]["message_id"] == data["done"]["message_id"]
    assert data["status"] == {"label": "Drafting your itinerary…", "tool": None, "state": "start"}
    assert data["token"] == {"text": PLAN_READY}

    itinerary = data["itinerary"]
    assert itinerary["version"] == 1
    assert [p["tag"] for p in itinerary["places"]][:3] == ["A", "B", "C"]
    assert [h["tag"] for h in itinerary["lodging"]] == ["H1"]
    assert itinerary["lodging"][0]["price_source"] == "none"
    assert all(day["weather"] is None for day in itinerary["days"])


def test_itinerary_message_and_status_are_saved(client, engine, new_session):
    with Session(engine) as db:
        updated_before = db.get(SessionRow, new_session["id"]).updated_at

    events = generate(client, new_session["id"])

    saved = detail(client, new_session["id"])
    assert saved["status"] == "planned"
    assert saved["itinerary"] == dict(events)["itinerary"]
    assert [(m["role"], m["content"], m["itinerary_version"]) for m in saved["messages"]] == [
        ("assistant", GREETING, None),
        ("assistant", PLAN_READY, 1),
    ]
    assert saved["messages"][-1]["id"] == dict(events)["done"]["message_id"]
    with Session(engine) as db:
        assert db.get(SessionRow, new_session["id"]).updated_at > updated_before


def test_generating_again_saves_the_next_version(client, new_session):
    first = dict(generate(client, new_session["id"]))["itinerary"]
    second = dict(generate(client, new_session["id"]))["itinerary"]

    assert (first["version"], second["version"]) == (1, 2)
    assert second["id"] != first["id"]
    saved = detail(client, new_session["id"])
    assert saved["itinerary"]["version"] == 2
    assert [m["itinerary_version"] for m in saved["messages"]] == [None, 1, 2]


def test_body_is_optional(client, new_session):
    response = client.post(f"/api/sessions/{new_session['id']}/generate")

    assert names(parse_sse(response.text)) == EVENTS


def test_llm_gets_generate_prompt_history_and_todays_date(client, new_session, use_provider):
    client.post(f"/api/sessions/{new_session['id']}/messages", json={"content": "Austin for 3 days"})
    reply = detail(client, new_session["id"])["messages"][-1]["content"]  # the fake's chat reply
    provider = use_provider(DraftProvider())

    generate(client, new_session["id"])

    (call,) = provider.calls
    assert call["system"] == (orchestrator.PROMPTS_DIR / "generate.md").read_text(encoding="utf-8")
    assert call["schema"] is ItineraryDraft
    # Greeting dropped; the request with today's date makes the conversation end with the user.
    assert call["messages"] == [
        {"role": "user", "content": "Austin for 3 days"},
        {"role": "assistant", "content": reply},
        {"role": "user", "content": orchestrator.generation_request(dt.date.today())},
    ]


def test_generation_request_names_the_date():
    text = orchestrator.generation_request(dt.date(2026, 11, 2))

    assert text.startswith("Today is Monday, 2026-11-02.")


def test_generate_prompt_states_the_lodging_date_rules():
    prompt = (orchestrator.PROMPTS_DIR / "generate.md").read_text(encoding="utf-8")

    for rule in ("on or after `start_date`", "on or before `end_date`", "must not overlap", "lodging_ref"):
        assert rule in prompt


# --- errors: friendly text, nothing saved, previous version kept ------------------------------


def test_unconfigured_provider_sends_error_event_not_500(client, new_session):
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, llm_provider="openai_compat")

    events = generate(client, new_session["id"])

    assert names(events) == ["message_start", "error"]
    assert events[1][1] == {"message": orchestrator.SETUP_MESSAGE, "retryable": False}  # not the LLMError text
    saved = detail(client, new_session["id"])
    assert (saved["status"], saved["itinerary"], len(saved["messages"])) == ("intake", None, 1)


def test_llm_error_keeps_the_previous_version(client, new_session, use_provider):
    generate(client, new_session["id"])  # version 1 with the real fake provider
    use_provider(DraftProvider(error=LLMError("Model reply was not a valid ItineraryDraft", retryable=True)))

    events = generate(client, new_session["id"])

    assert names(events) == ["message_start", "status", "error"]
    assert events[-1][1] == {"message": orchestrator.RETRY_MESSAGE, "retryable": True}
    saved = detail(client, new_session["id"])
    assert saved["itinerary"]["version"] == 1
    assert [m["itinerary_version"] for m in saved["messages"]] == [None, 1]


def test_unexpected_exception_hides_details_and_saves_nothing(client, new_session, monkeypatch):
    def broken_postprocess(*_args, **_kwargs):
        raise RuntimeError("secret internals")

    monkeypatch.setattr(orchestrator, "draft_to_itinerary", broken_postprocess)

    events = generate(client, new_session["id"])

    assert names(events) == ["message_start", "status", "error"]
    assert events[-1][1] == {"message": orchestrator.RETRY_MESSAGE, "retryable": True}
    assert "secret" not in json.dumps(events)
    saved = detail(client, new_session["id"])
    assert (saved["status"], saved["itinerary"], len(saved["messages"])) == ("intake", None, 1)


def test_unknown_session_is_404(client):
    response = client.post("/api/sessions/no-such-session/generate", json={})

    assert response.status_code == 404
    assert response.json() == {"detail": "Session not found"}


# --- truncated replies through the real openai_compat adapter (mock HTTP, no network) ---------

TRUNCATED = DRAFT_JSON[: len(DRAFT_JSON) * 2 // 3]  # cut mid-plan, like a reply that hit a length cap


def test_truncated_reply_is_retried_once_then_succeeds(client, new_session, use_provider):
    endpoint = FakeEndpoint(sse_response(stream_of(TRUNCATED)), sse_response(stream_of(DRAFT_JSON)))
    use_provider(make_provider(endpoint))

    events = generate(client, new_session["id"])

    assert names(events) == EVENTS
    assert len(endpoint.requests) == 2  # the provider's single retry; the orchestrator adds none
    assert endpoint.requests[1]["messages"][-2] == {"role": "assistant", "content": TRUNCATED}


def test_truncated_reply_twice_sends_retryable_error(client, new_session, use_provider):
    endpoint = FakeEndpoint(sse_response(stream_of(TRUNCATED)), sse_response(stream_of(TRUNCATED)))
    use_provider(make_provider(endpoint))

    events = generate(client, new_session["id"])

    assert names(events) == ["message_start", "status", "error"]
    assert events[-1][1] == {"message": orchestrator.RETRY_MESSAGE, "retryable": True}
    assert len(endpoint.requests) == 2  # 2 LLM calls at most, never 4
    # No output cap is sent, so a full draft isn't cut off by our own request.
    assert not {"max_tokens", "max_completion_tokens"} & set(endpoint.requests[0])
    saved = detail(client, new_session["id"])
    assert (saved["status"], saved["itinerary"]) == ("intake", None)


def test_blank_reply_sends_retryable_error_after_one_call(client, new_session, use_provider):
    endpoint = FakeEndpoint(sse_response(stream_of(" ", "\n")))
    use_provider(make_provider(endpoint))

    events = generate(client, new_session["id"])

    assert names(events) == ["message_start", "status", "error"]
    assert events[-1][1] == {"message": orchestrator.RETRY_MESSAGE, "retryable": True}
    assert len(endpoint.requests) == 1
