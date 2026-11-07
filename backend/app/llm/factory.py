"""Pick the LLM provider named by LLM_PROVIDER."""

from openai import AsyncOpenAI

from app.core.config import Settings
from app.llm.base import LLMProvider
from app.llm.fake_provider import FakeProvider
from app.llm.openai_compat_provider import OpenAICompatProvider

SUPPORTED_PROVIDERS = ["fake", "openai_compat"]


def get_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "fake":
        return FakeProvider()
    if settings.llm_provider == "openai_compat":
        missing = [
            name
            for name, value in [
                ("LLM_MODEL", settings.llm_model),
                ("LLM_API_KEY", settings.llm_api_key),
                ("LLM_BASE_URL", settings.llm_base_url),
            ]
            if not value
        ]
        if missing:
            raise ValueError(f"LLM_PROVIDER=openai_compat needs {', '.join(missing)} in backend/.env")
        client = AsyncOpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
        return OpenAICompatProvider(model=settings.llm_model, client=client)
    raise ValueError(
        f"Unsupported LLM_PROVIDER {settings.llm_provider!r}; supported: {', '.join(SUPPORTED_PROVIDERS)}"
    )
