"""Step 32a: models per role (D26, plan step 32a).

Specified: LLM_CHAT_MODEL picks the chat model and falls back to LLM_MODEL when empty; the
planner always uses LLM_MODEL. `get_provider(settings, role)` builds the provider for a role.
The turn gets two providers: the chat one runs understand, chat replies and the post-plan
summary; the planner one runs compose. Two fakes record their calls. No network.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.agent import turn
from app.agent.turn import TurnLlms
from app.api.chat import get_llm
from app.core.config import Settings
from app.db import repo
from app.llm.base import Message, T
from app.llm.factory import get_provider, model_for
from app.llm.fake_provider import FakeProvider
from app.llm.openai_compat_provider import OpenAICompatProvider

ENV_EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"
SETUP_MESSAGE = "San Jose from College Station, first weekend of March, just me, tech and food"
EDIT_MESSAGE = "Replace [F] with something vegan"


class RecordingFake(FakeProvider):
    """A FakeProvider that records each call as ("stream_text", None) or
    ("complete_json", schema name)."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, str | None]] = []

    async def stream_text(self, system: str, messages: list[Message]) -> AsyncIterator[str]:
        self.calls.append(("stream_text", None))
        async for chunk in super().stream_text(system, messages):
            yield chunk

    async def complete_json(self, system: str, messages: list[Message], schema: type[T]) -> T:
        self.calls.append(("complete_json", schema.__name__))
        return await super().complete_json(system, messages, schema)


def _compat(settings: Settings, **overrides: str) -> Settings:
    values = {
        "llm_provider": "openai_compat",
        "llm_model": "planner-model",
        "llm_chat_model": "chat-model",
        "llm_api_key": "test-key",
        "llm_base_url": "http://llm.invalid/v1",
    }
    values.update(overrides)
    return settings.model_copy(update=values)


def _parse_sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in text.replace("\r\n", "\n").replace("\r", "\n").split("\n\n"):
        name = "message"
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:"):].lstrip(" "))
        if data_lines:
            events.append((name, json.loads("\n".join(data_lines))))
    return events


def _two_fakes(client: TestClient) -> tuple[RecordingFake, RecordingFake]:
    chat, planner = RecordingFake(), RecordingFake()
    client.app.dependency_overrides[get_llm] = lambda: TurnLlms(chat=chat, planner=planner)  # type: ignore[attr-defined]
    return chat, planner


def _send(client: TestClient, session_id: str, content: str) -> list[tuple[str, dict[str, Any]]]:
    response = client.post(f"/api/sessions/{session_id}/messages", json={"content": content})
    assert response.status_code == 200
    return _parse_sse(response.text)


def _names(events: list[tuple[str, dict[str, Any]]]) -> list[str]:
    return [name for name, _ in events]


# --- settings + factory ---------------------------------------------------------------------


def test_settings_chat_model_defaults_to_empty(settings: Settings) -> None:
    assert settings.llm_chat_model == ""


def test_settings_reads_llm_chat_model_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_CHAT_MODEL", "env-chat-model")
    monkeypatch.setenv("LLM_MODEL", "env-planner-model")
    loaded = Settings(_env_file=None)
    assert loaded.llm_chat_model == "env-chat-model"
    assert loaded.llm_model == "env-planner-model"


def test_model_for_chat_uses_llm_chat_model(settings: Settings) -> None:
    assert model_for(_compat(settings), "chat") == "chat-model"


def test_model_for_chat_falls_back_to_llm_model_when_empty(settings: Settings) -> None:
    assert model_for(_compat(settings, llm_chat_model=""), "chat") == "planner-model"


def test_model_for_planner_always_uses_llm_model(settings: Settings) -> None:
    assert model_for(_compat(settings), "planner") == "planner-model"
    assert model_for(_compat(settings, llm_chat_model=""), "planner") == "planner-model"


def test_get_provider_builds_each_role_with_its_model(settings: Settings) -> None:
    chat = get_provider(_compat(settings), "chat")
    planner = get_provider(_compat(settings), "planner")
    assert isinstance(chat, OpenAICompatProvider)
    assert isinstance(planner, OpenAICompatProvider)
    assert chat.model == "chat-model"
    assert planner.model == "planner-model"


def test_get_provider_chat_falls_back_to_llm_model(settings: Settings) -> None:
    chat = get_provider(_compat(settings, llm_chat_model=""), "chat")
    assert isinstance(chat, OpenAICompatProvider)
    assert chat.model == "planner-model"


def test_get_provider_chat_works_with_only_chat_model_set(settings: Settings) -> None:
    # The chat role needs a model id, and LLM_CHAT_MODEL alone is one.
    chat = get_provider(_compat(settings, llm_model=""), "chat")
    assert isinstance(chat, OpenAICompatProvider)
    assert chat.model == "chat-model"


def test_get_provider_planner_still_needs_llm_model(settings: Settings) -> None:
    with pytest.raises(ValueError, match="LLM_MODEL"):
        get_provider(_compat(settings, llm_model=""), "planner")


def test_get_provider_errors_when_no_model_for_chat(settings: Settings) -> None:
    with pytest.raises(ValueError, match="LLM_MODEL"):
        get_provider(_compat(settings, llm_model="", llm_chat_model=""), "chat")


@pytest.mark.parametrize("role", ["chat", "planner"])
def test_get_provider_fake_for_both_roles(settings: Settings, role: str) -> None:
    assert isinstance(get_provider(settings, role), FakeProvider)  # type: ignore[arg-type]


def test_get_llm_gives_the_turn_a_chat_and_a_planner_provider(settings: Settings) -> None:
    llms = get_llm(_compat(settings))
    assert isinstance(llms, TurnLlms)
    assert isinstance(llms.chat, OpenAICompatProvider)
    assert isinstance(llms.planner, OpenAICompatProvider)
    assert llms.chat.model == "chat-model"
    assert llms.planner.model == "planner-model"


def test_env_example_sets_the_chat_model_with_a_comment() -> None:
    lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    index = lines.index("LLM_CHAT_MODEL=protected.Claude-Sonnet-5")
    assert lines[index - 1].startswith("#")


# --- which provider runs what in a turn -----------------------------------------------------


def test_chat_turn_uses_only_the_chat_provider(client: TestClient) -> None:
    chat, planner = _two_fakes(client)
    session_id = client.post("/api/sessions").json()["id"]

    events = _send(client, session_id, SETUP_MESSAGE)

    assert _names(events)[-1] == "done"
    assert chat.calls == [("complete_json", "TurnAnalysis"), ("stream_text", None)]
    assert planner.calls == []


def test_generate_turn_understands_and_summarises_with_chat_and_composes_with_planner(
    client: TestClient,
) -> None:
    chat, planner = _two_fakes(client)
    session_id = client.post("/api/sessions").json()["id"]
    _send(client, session_id, SETUP_MESSAGE)
    chat.calls.clear()

    events = _send(client, session_id, "Great, make the plan")

    assert "itinerary" in _names(events)
    assert _names(events)[-1] == "done"
    assert chat.calls == [("complete_json", "TurnAnalysis"), ("stream_text", None)]
    assert planner.calls == [("complete_json", "ItineraryDraft")]


def test_generate_button_composes_with_planner_and_summarises_with_chat(client: TestClient) -> None:
    chat, planner = _two_fakes(client)
    session_id = client.post("/api/sessions").json()["id"]
    _send(client, session_id, SETUP_MESSAGE)
    chat.calls.clear()

    response = client.post(f"/api/sessions/{session_id}/generate", json={})
    events = _parse_sse(response.text)

    assert "itinerary" in _names(events)
    # No user message: understand is skipped; the summary is still the chat model's.
    assert chat.calls == [("stream_text", None)]
    assert planner.calls == [("complete_json", "ItineraryDraft")]


def test_edit_turn_understands_and_summarises_with_chat_and_composes_with_planner(
    client: TestClient,
) -> None:
    chat, planner = _two_fakes(client)
    session_id = client.post("/api/sessions").json()["id"]
    _send(client, session_id, SETUP_MESSAGE)
    client.post(f"/api/sessions/{session_id}/generate", json={})
    chat.calls.clear()
    planner.calls.clear()

    events = _send(client, session_id, EDIT_MESSAGE)

    assert "itinerary" in _names(events)
    assert _names(events)[-1] == "done"
    assert chat.calls == [("complete_json", "TurnAnalysis"), ("stream_text", None)]
    assert planner.calls == [("complete_json", "ItineraryDraft")]


def test_run_turn_composes_with_chat_provider_when_no_planner_given(db: Session) -> None:
    session_id = repo.create_session(db).id
    chat = RecordingFake()

    async def collect() -> list[str]:
        return [event["event"] async for event in turn.run_turn(db, session_id, None, chat)]

    names = asyncio.run(collect())

    assert "itinerary" in names
    assert names[-1] == "done"
    assert chat.calls == [("complete_json", "ItineraryDraft"), ("stream_text", None)]
