"""LLM provider layer (04-backend-design §3). The only place that talks to a model."""

from app.llm.base import ChatMessage, LLMError, LLMProvider
from app.llm.factory import get_llm, get_provider
