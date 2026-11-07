"""Shared test fixtures. Tests always run offline: fake LLM, mock tools, no backend/.env,
and a fresh temp SQLite file per test (never backend/travel.db)."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session

# Environment variables win over backend/.env, so anything that calls get_settings()
# directly also sees the offline modes.
os.environ["LLM_PROVIDER"] = "fake"
os.environ["TOOL_PROVIDER_MODE"] = "mock"

from app.core.config import Settings, get_settings  # noqa: E402
from app.db import engine as engine_module  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture(autouse=True)
def db_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    # Autouse: every test, including app startup in route tests, gets its own temp DB file.
    engine = engine_module.make_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    engine_module.create_tables(engine)
    monkeypatch.setattr(engine_module, "_engine", engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db(db_engine: Engine) -> Iterator[Session]:
    with Session(db_engine) as session:
        yield session


@pytest.fixture
def settings() -> Settings:
    # _env_file=None: ignore the developer's local backend/.env entirely.
    return Settings(_env_file=None, llm_provider="fake", tool_provider_mode="mock")


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)
