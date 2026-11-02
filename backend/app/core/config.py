"""App settings, read from environment variables and `backend/.env`.

Variables are documented in docs/setup-guide.md §5. Keys use `SecretStr` so they are
masked if a Settings object is ever printed or logged; read them with
`settings.llm_api_key.get_secret_value()`.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ folder, so `.env` and the SQLite file are found no matter where the server starts.
BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    llm_provider: Literal["fake", "openai_compat", "anthropic"] = "fake"
    llm_model: str = ""
    llm_fast_model: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_base_url: str = ""

    # External tools (Stage 2+)
    tool_provider_mode: Literal["mock", "live"] = "mock"
    google_maps_server_key: SecretStr = SecretStr("")
    serpapi_key: SecretStr = SecretStr("")

    # Database: default is backend/travel.db
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'travel.db').as_posix()}"


@lru_cache
def get_settings() -> Settings:
    """Settings are read once per process; restart the server after editing `.env`."""
    return Settings()
