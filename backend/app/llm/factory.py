"""Pick the LLM provider named by LLM_PROVIDER."""

from app.core.config import Settings
from app.llm.base import LLMProvider
from app.llm.fake_provider import FakeProvider

SUPPORTED_PROVIDERS = ["fake"]


def get_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "fake":
        return FakeProvider()
    # "openai_compat" is valid in Settings but its adapter isn't built yet (plan step 12).
    raise ValueError(
        f"Unsupported LLM_PROVIDER {settings.llm_provider!r}; supported: {', '.join(SUPPORTED_PROVIDERS)}"
    )
