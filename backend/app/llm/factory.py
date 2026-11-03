"""Pick the LLM provider named by `LLM_PROVIDER` (04-backend-design §3.0)."""

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.llm.base import LLMError, LLMProvider
from app.llm.fake_provider import FakeProvider

# Providers whose adapter isn't written yet, and the plan item that adds it.
NOT_IMPLEMENTED = {"openai_compat": "S1.6", "anthropic": "S1.7"}


def get_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "fake":
        return FakeProvider()
    item = NOT_IMPLEMENTED.get(settings.llm_provider, "?")
    raise LLMError(
        f"LLM_PROVIDER={settings.llm_provider!r} is not implemented yet ({item}); "
        "use LLM_PROVIDER=fake for now.",
        retryable=False,
    )


def get_llm(settings: Settings = Depends(get_settings)) -> LLMProvider:
    """FastAPI dependency for routes; tests override `get_settings` to choose the provider."""
    return get_provider(settings)
