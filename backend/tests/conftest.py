import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import Settings, get_settings
from app.db.engine import get_engine, get_session, init_db, make_engine
from app.main import app

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    """A fresh copy of a JSON fixture, safe to mutate in a test."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def austin() -> dict:
    """Valid 3-day Austin itinerary in the Stage 1 shape (coords, prices, weather null)."""
    return load_fixture("itinerary_austin.json")


@pytest.fixture
def austin_bad() -> dict:
    """The Austin itinerary with four cross-field errors (day count, order, tag, booking)."""
    return load_fixture("itinerary_austin_bad.json")


@pytest.fixture
def engine(tmp_path):
    """Engine on a throwaway SQLite file with all tables; never touches backend/travel.db."""
    engine = make_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    init_db(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def client(engine):
    """TestClient on the tmp-file DB with LLM_PROVIDER=fake; ignores backend/.env.

    Not used as a context manager, so the app lifespan (which would create backend/travel.db)
    never runs. Don't write `with TestClient(app)` in tests.
    """

    def tmp_session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_session] = tmp_session
    app.dependency_overrides[get_engine] = lambda: engine  # used by the SSE routes
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, llm_provider="fake")
    yield TestClient(app)
    app.dependency_overrides.clear()
