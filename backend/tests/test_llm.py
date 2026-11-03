"""LLM layer v0 (04-backend-design §3.0): fake provider and factory. No network, no keys."""

import json

import pytest
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.llm import ChatMessage, LLMError, LLMProvider, get_llm, get_provider
from app.llm.fake_provider import FakeProvider, canned_reply, fixture_name


class TinyPlan(BaseModel):
    """Test-only schema; the fake looks for `tiny_plan.json`."""

    city: str
    days: int


@pytest.fixture
def fake(tmp_path) -> FakeProvider:
    """Fake with no delay, reading fixtures from a throwaway directory."""
    return FakeProvider(delay=0, fixtures_dir=tmp_path)


async def collect(provider: LLMProvider, messages: list[ChatMessage]) -> list[str]:
    return [chunk async for chunk in provider.stream_text(system="You are a planner.", messages=messages)]


CHAT: list[ChatMessage] = [
    {"role": "assistant", "content": "Hi! Where would you like to go?"},
    {"role": "user", "content": "Austin for 3 days"},
]


# --- stream_text ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_text_chunks_join_to_the_full_reply(fake):
    chunks = await collect(fake, CHAT)

    assert len(chunks) > 1
    assert all(0 < len(chunk) <= 30 for chunk in chunks)
    assert "".join(chunks) == canned_reply(CHAT)


@pytest.mark.asyncio
async def test_stream_text_quotes_the_last_user_message(fake):
    reply = "".join(await collect(fake, CHAT))

    assert '"Austin for 3 days"' in reply


@pytest.mark.asyncio
async def test_stream_text_is_deterministic(fake):
    first = await collect(fake, CHAT)
    second = await collect(FakeProvider(delay=0), CHAT)

    assert first == second


def test_stream_text_moves_the_conversation_forward():
    one_turn = canned_reply(CHAT)
    two_turns = canned_reply([*CHAT, {"role": "assistant", "content": "..."}, {"role": "user", "content": "Me"}])

    assert one_turn != two_turns
    assert "Generate plan" in canned_reply([{"role": "user", "content": "x"}] * 5)  # last follow-up repeats


@pytest.mark.asyncio
async def test_stream_text_handles_no_user_message_and_long_input(fake):
    assert "".join(await collect(fake, [])) == canned_reply([])

    long_text = "word\n" * 100
    reply = canned_reply([{"role": "user", "content": long_text}])
    assert "\n" not in reply
    assert "..." in reply and len(reply) < 250


# --- generate_json -------------------------------------------------------------------------


def test_fixture_name_is_snake_case():
    assert fixture_name("ItineraryDraft") == "itinerary_draft.json"
    assert fixture_name("TinyPlan") == "tiny_plan.json"


@pytest.mark.asyncio
async def test_generate_json_returns_validated_model_from_fixture(fake, tmp_path):
    (tmp_path / "tiny_plan.json").write_text(json.dumps({"city": "Austin", "days": 3}), encoding="utf-8")

    plan = await fake.generate_json(system="Draft a plan.", messages=CHAT, schema=TinyPlan)

    assert plan == TinyPlan(city="Austin", days=3)


@pytest.mark.asyncio
async def test_generate_json_missing_fixture_raises_llm_error(fake):
    with pytest.raises(LLMError, match="tiny_plan.json") as exc_info:
        await fake.generate_json(system="", messages=CHAT, schema=TinyPlan)

    assert exc_info.value.retryable is False


@pytest.mark.parametrize(
    "content",
    [json.dumps({"city": "Austin", "days": "three"}), "{not json"],
    ids=["wrong-type", "broken-json"],
)
@pytest.mark.asyncio
async def test_generate_json_invalid_fixture_raises_llm_error(fake, tmp_path, content):
    (tmp_path / "tiny_plan.json").write_text(content, encoding="utf-8")

    with pytest.raises(LLMError, match="not a valid TinyPlan") as exc_info:
        await fake.generate_json(system="", messages=CHAT, schema=TinyPlan)

    assert isinstance(exc_info.value.__cause__, ValidationError)  # details kept for debugging
    assert exc_info.value.retryable is False


# --- factory ------------------------------------------------------------------------------


def test_factory_returns_fake_by_default():
    provider = get_provider(Settings(_env_file=None))

    assert isinstance(provider, FakeProvider)
    assert provider.name == "fake"


def test_get_llm_dependency_uses_settings():
    assert get_llm(Settings(_env_file=None, llm_provider="fake")).name == "fake"


@pytest.mark.parametrize(("provider", "item"), [("openai_compat", "S1.6"), ("anthropic", "S1.7")])
def test_factory_errors_clearly_for_providers_not_built_yet(provider, item):
    with pytest.raises(LLMError, match=f"not implemented yet \\({item}\\)") as exc_info:
        get_provider(Settings(_env_file=None, llm_provider=provider))

    assert exc_info.value.retryable is False
