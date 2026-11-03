"""SQLModel tables (03-contracts §1): defaults, JSON columns, foreign keys and cascade delete."""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.config import get_settings
from app.db.engine import get_engine
from app.db.tables import ItineraryRow, MessageRow, SessionRow
from app.main import app
from app.schemas import Itinerary, Message, SessionSummary


@pytest.fixture
def fresh_settings(monkeypatch):
    """Lets a test set env vars before Settings/engine are built; restores the caches after."""
    get_settings.cache_clear()
    get_engine.cache_clear()
    yield monkeypatch
    if get_engine.cache_info().currsize:  # only dispose an engine the test actually built
        get_engine().dispose()
    get_settings.cache_clear()
    get_engine.cache_clear()


def test_session_defaults(engine, fresh_settings):
    fresh_settings.setenv("LLM_PROVIDER", "anthropic")

    with Session(engine) as db:
        row = SessionRow()
        db.add(row)
        db.commit()
        session_id = row.id

    with Session(engine) as db:
        row = db.get(SessionRow, session_id)
        assert UUID(row.id).version == 4
        assert row.title == "New trip"
        assert row.title_is_custom is False
        assert row.status == "intake"
        assert row.trip_profile == {}
        assert row.agent_transcript == []
        assert row.llm_provider == "anthropic"  # taken from the configured LLM_PROVIDER
        assert row.created_at is not None and row.updated_at is not None


def test_rows_round_trip_with_json_columns(engine, austin):
    itinerary_json = Itinerary.model_validate(austin).model_dump(mode="json")
    transcript = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]

    with Session(engine) as db:
        session_row = SessionRow(llm_provider="fake", trip_profile={"cities": ["Austin"]}, agent_transcript=transcript)
        db.add(session_row)
        db.commit()
        session_id = session_row.id
        db.add(MessageRow(session_id=session_id, role="user", content="Plan **Austin** for 3 days"))
        db.add(MessageRow(session_id=session_id, role="assistant", content="Done!", itinerary_version=1))
        db.add(ItineraryRow(session_id=session_id, version=1, data=itinerary_json))
        db.commit()

    with Session(engine) as db:
        session_row = db.get(SessionRow, session_id)
        messages = db.exec(select(MessageRow).where(MessageRow.session_id == session_id)).all()
        itinerary_row = db.exec(select(ItineraryRow).where(ItineraryRow.session_id == session_id)).one()

        assert session_row.trip_profile == {"cities": ["Austin"]}
        assert session_row.agent_transcript == transcript
        assert itinerary_row.data == austin
        assert Itinerary.model_validate(itinerary_row.data).places[0].name == "Franklin Barbecue"
        assert {m.role for m in messages} == {"user", "assistant"}

        # DTOs build straight from rows; naive SQLite datetimes serialize as UTC "...Z".
        dto = Message.model_validate(messages[0]).model_dump(mode="json")
        assert dto["created_at"].endswith("Z")
        assert SessionSummary.model_validate(session_row).status == "intake"


def test_deleting_a_session_cascades(engine, austin):
    with Session(engine) as db:
        doomed, kept = SessionRow(llm_provider="fake"), SessionRow(llm_provider="fake")
        db.add_all([doomed, kept])
        db.commit()
        for row in (doomed, kept):
            db.add(MessageRow(session_id=row.id, role="user", content="hi"))
            db.add(ItineraryRow(session_id=row.id, version=1, data=austin))
        db.commit()
        doomed_id, kept_id = doomed.id, kept.id

    with Session(engine) as db:
        db.delete(db.get(SessionRow, doomed_id))
        db.commit()

    with Session(engine) as db:
        assert db.exec(select(MessageRow).where(MessageRow.session_id == doomed_id)).all() == []
        assert db.exec(select(ItineraryRow).where(ItineraryRow.session_id == doomed_id)).all() == []
        assert len(db.exec(select(MessageRow).where(MessageRow.session_id == kept_id)).all()) == 1
        assert len(db.exec(select(ItineraryRow).where(ItineraryRow.session_id == kept_id)).all()) == 1


def test_foreign_keys_are_enforced(engine):
    with Session(engine) as db:
        db.add(MessageRow(session_id="no-such-session", role="user", content="hi"))
        with pytest.raises(IntegrityError):
            db.commit()


def test_itinerary_version_is_unique_per_session(engine, austin):
    with Session(engine) as db:
        row = SessionRow(llm_provider="fake")
        db.add(row)
        db.commit()
        db.add(ItineraryRow(session_id=row.id, version=1, data=austin))
        db.add(ItineraryRow(session_id=row.id, version=1, data=austin))
        with pytest.raises(IntegrityError):
            db.commit()


def test_app_startup_creates_tables(tmp_path, fresh_settings):
    db_file = tmp_path / "startup.db"
    fresh_settings.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")

    with TestClient(app):  # entering the client runs the FastAPI lifespan
        pass

    assert {"session", "message", "itinerary"} <= set(inspect(get_engine()).get_table_names())
