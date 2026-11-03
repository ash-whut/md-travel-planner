import json
from pathlib import Path

import pytest

from app.db.engine import init_db, make_engine

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
