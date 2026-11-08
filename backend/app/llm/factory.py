"""Pick the LLM provider named by LLM_PROVIDER, with the model for a role (D26)."""

from typing import Literal

from openai import AsyncOpenAI

from app.core.config import Settings
from app.llm.base import LLMProvider
from app.llm.fake_provider import FakeProvider
from app.llm.openai_compat_provider import OpenAICompatProvider

SUPPORTED_PROVIDERS = ["fake", "openai_compat"]

# "chat": understand, chat replies and the post-plan summary. "planner": planner and compose.
Role = Literal["chat", "planner"]


def model_for(settings: Settings, role: Role) -> str:
    """The model id for a role: LLM_CHAT_MODEL for chat (falling back to LLM_MODEL when empty),
    LLM_MODEL for the planner."""
    if role == "chat":
        return settings.llm_chat_model or settings.llm_model
    return settings.llm_model


def get_provider(settings: Settings, role: Role) -> LLMProvider:
    if settings.llm_provider == "fake":
        return FakeProvider()
    if settings.llm_provider == "openai_compat":
        model = model_for(settings, role)
        missing = [
            name
            for name, value in [
                ("LLM_MODEL", model),
                ("LLM_API_KEY", settings.llm_api_key),
                ("LLM_BASE_URL", settings.llm_base_url),
            ]
            if not value
        ]
        if missing:
            raise ValueError(f"LLM_PROVIDER=openai_compat needs {', '.join(missing)} in backend/.env")
        client = AsyncOpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
        return OpenAICompatProvider(model=model, client=client)
    raise ValueError(
        f"Unsupported LLM_PROVIDER {settings.llm_provider!r}; supported: {', '.join(SUPPORTED_PROVIDERS)}"
    )
