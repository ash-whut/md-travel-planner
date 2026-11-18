"""App settings, read from backend/.env (see backend/.env.example)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# Absolute path so the file is found no matter where uvicorn or pytest is started.
BACKEND_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BACKEND_DIR / ".env"


class Settings(BaseSettings):
    # extra="ignore": old or unknown keys in a local .env must not break startup.
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    llm_provider: Literal["fake", "openai_compat"] = "fake"
    llm_model: str = ""  # the planner model (planner + compose), D26
    llm_chat_model: str = ""  # the chat model (understand + replies); empty = llm_model
    llm_api_key: str = ""
    llm_base_url: str = ""

    tool_provider_mode: Literal["mock", "live"] = "mock"
    geoapify_key: str = ""
    serpapi_key: str = ""

    # None means the default database file; resolved by the db layer.
    database_url: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
