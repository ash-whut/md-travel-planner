"""Step 12: OpenAI-compatible provider (TAMU AI). A stub client stands in for AsyncOpenAI,
so no test here touches the network except the one marked live (skipped by default)."""

import asyncio
import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from app.agent import understand
from app.core.config import Settings
from app.llm.factory import get_provider
from app.llm.openai_compat_provider import OpenAICompatProvider
from app.schemas.profile import TripProfile
from app.schemas.turn import TurnAnalysis

MESSAGES = [{"role": "user", "content": "Plan a weekend in Austin"}]


class City(BaseModel):
    name: str
    days: int


# ---- stub client -------------------------------------------------------------------------


def _chunk(content: str | None) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content))])


def _no_choices_chunk() -> SimpleNamespace:
    return SimpleNamespace(choices=[])


def _reply(content: str | None) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


async def _aiter(items: list[Any]) -> AsyncIterator[Any]:
    for item in items:
        yield item


class StubCompletions:
    """Mimics `client.chat.completions.create`: records every call's kwargs."""

    def __init__(self, stream_chunks: list[Any] | None = None, replies: list[str | None] | None = None) -> None:
        self.stream_chunks = stream_chunks or []
        self.replies = list(replies or [])
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            return _aiter(self.stream_chunks)
        return _reply(self.replies.pop(0))


def _stub_client(completions: StubCompletions) -> SimpleNamespace:
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


def _provider(completions: StubCompletions) -> OpenAICompatProvider:
    return OpenAICompatProvider(model="m", client=_stub_client(completions))  # type: ignore[arg-type]


async def _collect(provider: OpenAICompatProvider, system: str = "sys") -> list[str]:
    return [chunk async for chunk in provider.stream_text(system, MESSAGES)]


# ---- stream_text -------------------------------------------------------------------------


def test_stream_chunks_are_yielded_and_join_to_full_text() -> None:
    completions = StubCompletions(stream_chunks=[_chunk("Austin "), _chunk("is "), _chunk("great.")])
    chunks = asyncio.run(_collect(_provider(completions)))
    assert chunks == ["Austin ", "is ", "great."]
    assert "".join(chunks) == "Austin is great."


def test_stream_skips_empty_deltas_and_chunks_without_choices() -> None:
    completions = StubCompletions(
        stream_chunks=[_no_choices_chunk(), _chunk("Hi"), _chunk(None), _chunk(""), _chunk(" there"), _no_choices_chunk()]
    )
    chunks = asyncio.run(_collect(_provider(completions)))
    assert chunks == ["Hi", " there"]


def test_stream_sends_model_stream_true_and_system_first() -> None:
    completions = StubCompletions(stream_chunks=[_chunk("ok")])
    asyncio.run(_collect(_provider(completions), system="You are a planner."))
    assert len(completions.calls) == 1
    call = completions.calls[0]
    assert call["model"] == "m"
    assert call["stream"] is True
    assert call["messages"][0] == {"role": "system", "content": "You are a planner."}
    assert call["messages"][1:] == MESSAGES


# ---- complete_json -----------------------------------------------------------------------


def test_complete_json_parses_into_model() -> None:
    completions = StubCompletions(replies=['{"name": "Austin", "days": 3}'])
    result = asyncio.run(_provider(completions).complete_json("sys", MESSAGES, City))
    assert isinstance(result, City)
    assert result == City(name="Austin", days=3)
    assert len(completions.calls) == 1


def test_complete_json_sends_stream_false_json_object_and_schema_in_system() -> None:
    completions = StubCompletions(replies=['{"name": "Austin", "days": 3}'])
    asyncio.run(_provider(completions).complete_json("sys", MESSAGES, City))
    call = completions.calls[0]
    assert call["model"] == "m"
    assert call["stream"] is False  # D16: must be explicit or TAMU AI streams anyway
    # D18: plain JSON mode; the schema travels in the system text instead of response_format.
    assert call["response_format"] == {"type": "json_object"}
    system = call["messages"][0]
    assert system["role"] == "system"
    assert system["content"].startswith("sys")
    assert json.dumps(City.model_json_schema()) in system["content"]
    assert call["messages"][1:] == MESSAGES


@pytest.mark.parametrize(
    "reply",
    [
        '```json\n{"name": "Austin", "days": 3}\n```',
        'Here you go: {"name": "Austin", "days": 3}',
        '{"name": "Austin", "days": 3}\nWant me to add more cities?',
    ],
)
def test_complete_json_ignores_code_fences_and_text_around_the_object(reply: str) -> None:
    completions = StubCompletions(replies=[reply])
    result = asyncio.run(_provider(completions).complete_json("sys", MESSAGES, City))
    assert result == City(name="Austin", days=3)
    assert len(completions.calls) == 1  # no retry needed


def test_complete_json_bad_then_good_succeeds_after_one_retry() -> None:
    completions = StubCompletions(replies=["not json at all", '{"name": "Austin", "days": 2}'])
    result = asyncio.run(_provider(completions).complete_json("sys", MESSAGES, City))
    assert result == City(name="Austin", days=2)
    assert len(completions.calls) == 2
    retry = completions.calls[1]
    assert retry["stream"] is False
    # The retry shows the model its bad reply, then asks again.
    assert {"role": "assistant", "content": "not json at all"} in retry["messages"]
    assert retry["messages"][-1]["role"] == "user"


def test_complete_json_wrong_shape_then_good_succeeds() -> None:
    completions = StubCompletions(replies=['{"name": "Austin"}', '{"name": "Austin", "days": 4}'])
    result = asyncio.run(_provider(completions).complete_json("sys", MESSAGES, City))
    assert result.days == 4
    assert len(completions.calls) == 2


def test_complete_json_two_bad_replies_raise_validation_error() -> None:
    completions = StubCompletions(replies=["{bad", None])
    with pytest.raises(ValidationError):
        asyncio.run(_provider(completions).complete_json("sys", MESSAGES, City))
    assert len(completions.calls) == 2  # retried exactly once, no more


# ---- factory -----------------------------------------------------------------------------


def _compat_settings(settings: Settings, **overrides: str) -> Settings:
    values = {
        "llm_provider": "openai_compat",
        "llm_model": "some-model",
        "llm_api_key": "sk-test",
        "llm_base_url": "https://example.invalid/api",
    }
    values.update(overrides)
    return settings.model_copy(update=values)


def test_factory_returns_openai_compat_provider(settings: Settings) -> None:
    provider = get_provider(_compat_settings(settings))
    assert isinstance(provider, OpenAICompatProvider)
    assert provider.name == "openai_compat"
    assert provider.model == "some-model"


@pytest.mark.parametrize(
    ("field", "env_name"),
    [("llm_model", "LLM_MODEL"), ("llm_api_key", "LLM_API_KEY"), ("llm_base_url", "LLM_BASE_URL")],
)
def test_factory_errors_clearly_when_a_setting_is_missing(settings: Settings, field: str, env_name: str) -> None:
    with pytest.raises(ValueError, match=env_name):
        get_provider(_compat_settings(settings, **{field: ""}))


def test_factory_lists_all_missing_settings(settings: Settings) -> None:
    bad = settings.model_copy(update={"llm_provider": "openai_compat"})
    with pytest.raises(ValueError) as exc:
        get_provider(bad)
    message = str(exc.value)
    for env_name in ("LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL"):
        assert env_name in message


# ---- live (skipped by default; run with `pytest -m live`) ----------------------------------


@pytest.mark.live
def test_live_tamu_ai_streams_and_returns_json() -> None:
    # conftest forces LLM_PROVIDER=fake in the environment, so override it; the rest comes
    # from backend/.env.
    live = Settings().model_copy(update={"llm_provider": "openai_compat"})
    if not (live.llm_model and live.llm_api_key and live.llm_base_url):
        pytest.skip("LLM_MODEL / LLM_API_KEY / LLM_BASE_URL not set in backend/.env")
    provider = get_provider(live)

    async def run() -> tuple[list[str], City, TurnAnalysis]:
        chunks = [c async for c in provider.stream_text("Reply in one short sentence.", MESSAGES)]
        city = await provider.complete_json(
            "Reply with JSON only.",
            [{"role": "user", "content": "A 3-day trip to Austin: give the city name and the number of days."}],
            City,
        )
        # The real understand call: a schema with limits (maxItems, minimum…) that TAMU AI's
        # json_schema mode rejected (D18).
        analysis = await provider.complete_json(
            understand.build_system(TripProfile()),
            [
                {"role": "assistant", "content": "Hi! Where would you like to go?"},
                {"role": "user", "content": "San Jose, just me, from College Station"},
            ],
            TurnAnalysis,
        )
        return chunks, city, analysis

    chunks, city, analysis = asyncio.run(run())
    assert "".join(chunks).strip()
    assert isinstance(city, City)
    assert city.days == 3
    assert analysis.profile_updates.travelers == 1
    assert analysis.profile_updates.cities and "San Jose" in analysis.profile_updates.cities[0]
