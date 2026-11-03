"""Pick the LLM provider named by `LLM_PROVIDER` (04-backend-design §3.0)."""

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.llm.base import LLMError, LLMProvider
from app.llm.fake_provider import FakeProvider
from app.llm.openai_compat_provider import OpenAICompatProvider

# Providers whose adapter isn't written yet, and the plan item that adds it.
NOT_IMPLEMENTED = {"anthropic": "S1.7"}


def get_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "fake":
        return FakeProvider()
    if settings.llm_provider == "openai_compat":
        return make_openai_compat(settings)
    item = NOT_IMPLEMENTED.get(settings.llm_provider, "?")
    raise LLMError(
        f"LLM_PROVIDER={settings.llm_provider!r} is not implemented yet ({item}); "
        "use LLM_PROVIDER=fake for now.",
        retryable=False,
    )


def make_openai_compat(settings: Settings) -> OpenAICompatProvider:
    api_key = settings.llm_api_key.get_secret_value()
    missing = [
        name
        for name, value in [
            ("LLM_BASE_URL", settings.llm_base_url),
            ("LLM_MODEL", settings.llm_model),
            ("LLM_API_KEY", api_key),
        ]
        if not value.strip()
    ]
    if missing:
        raise LLMError(
            f"LLM_PROVIDER=openai_compat needs {', '.join(missing)} in backend/.env "
            "(see docs/setup-guide.md section 6.2).",
            retryable=False,
        )
    return OpenAICompatProvider(base_url=settings.llm_base_url, api_key=api_key, model=settings.llm_model)


def get_llm(settings: Settings = Depends(get_settings)) -> LLMProvider:
    """FastAPI dependency for routes; tests override `get_settings` to choose the provider."""
    return get_provider(settings)
