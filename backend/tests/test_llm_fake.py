"""Step 5: LLM layer + fake provider. Async code is driven with asyncio.run (no pytest-asyncio)."""

import asyncio
import re
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.core.config import Settings
from app.llm.factory import get_provider
from app.llm.fake_provider import CANNED_REPLY, FakeProvider

APP_DIR = Path(__file__).resolve().parents[1] / "app"
MESSAGES = [{"role": "user", "content": "Plan a weekend in Austin"}]


async def _collect(provider: FakeProvider, system: str = "sys") -> list[str]:
    return [chunk async for chunk in provider.stream_text(system, MESSAGES)]


def test_fake_streams_several_chunks_that_join_to_canned_text() -> None:
    chunks = asyncio.run(_collect(FakeProvider()))
    assert len(chunks) > 1
    assert all(isinstance(c, str) and c for c in chunks)
    assert "".join(chunks) == CANNED_REPLY


def test_fake_stream_uses_custom_reply() -> None:
    reply = "Austin it is, three days of tacos."
    chunks = asyncio.run(_collect(FakeProvider(reply=reply)))
    assert len(chunks) > 1
    assert "".join(chunks) == reply


def test_fake_stream_is_deterministic() -> None:
    assert asyncio.run(_collect(FakeProvider())) == asyncio.run(_collect(FakeProvider()))


def test_fake_complete_json_raises_clear_error_naming_schema() -> None:
    class UnknownSchema(BaseModel):
        x: int

    with pytest.raises(NotImplementedError, match="UnknownSchema"):
        asyncio.run(FakeProvider().complete_json("sys", MESSAGES, UnknownSchema))


def test_factory_returns_fake_provider(settings: Settings) -> None:
    provider = get_provider(settings, "chat")
    assert isinstance(provider, FakeProvider)
    assert provider.name == "fake"


def test_factory_errors_clearly_on_unknown_name(settings: Settings) -> None:
    bad = settings.model_copy(update={"llm_provider": "nope"})
    with pytest.raises(ValueError) as exc:
        get_provider(bad, "chat")
    message = str(exc.value)
    assert "nope" in message
    assert "fake" in message  # lists what is supported


def test_no_provider_sdk_imported_outside_llm_package() -> None:
    sdk_import = re.compile(r"^\s*(import|from)\s+(openai|anthropic)\b", re.MULTILINE)
    offenders = [
        str(path.relative_to(APP_DIR))
        for path in APP_DIR.rglob("*.py")
        if "llm" not in path.relative_to(APP_DIR).parts[:1] and sdk_import.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
