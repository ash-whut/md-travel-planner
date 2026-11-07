"""Step 3: SQLite tables + repository functions, always on a temp DB (see conftest.py)."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.db import engine as engine_module
from app.db import repo
from app.db.tables import MessageRow, SessionRow
from app.main import create_app


def _naive_utc(value: datetime) -> datetime:
    # SQLite may hand datetimes back without tzinfo; all stored values are UTC.
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


# --- create / get ---------------------------------------------------------------


def test_create_session_has_contract_defaults(db: Session) -> None:
    created = repo.create_session(db)

    assert created.id
    assert created.title == "New trip"
    assert created.title_is_custom is False
    assert created.status == "intake"
    assert created.trip_profile == {}
    assert created.created_at is not None
    assert created.updated_at is not None


def test_get_session_returns_saved_row(db_engine: Engine, db: Session) -> None:
    created = repo.create_session(db)

    # A separate DB session proves the row was committed, not just cached.
    with Session(db_engine) as other:
        fetched = repo.get_session(other, created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.title == "New trip"


def test_each_session_gets_a_unique_id(db: Session) -> None:
    ids = {repo.create_session(db).id for _ in range(3)}
    assert len(ids) == 3


def test_get_session_unknown_id_returns_none(db: Session) -> None:
    assert repo.get_session(db, "does-not-exist") is None


# --- messages -------------------------------------------------------------------


def test_add_message_saves_fields(db: Session) -> None:
    session_row = repo.create_session(db)

    message = repo.add_message(db, session_row.id, "assistant", "Here is **[A]**", itinerary_version=2)

    assert message.id
    assert message.session_id == session_row.id
    assert message.role == "assistant"
    assert message.content == "Here is **[A]**"
    assert message.itinerary_version == 2
    assert message.created_at is not None


def test_add_message_itinerary_version_defaults_to_none(db: Session) -> None:
    session_row = repo.create_session(db)
    message = repo.add_message(db, session_row.id, "user", "hi")
    assert message.itinerary_version is None


def test_messages_come_back_in_insertion_order(db_engine: Engine, db: Session) -> None:
    session_row = repo.create_session(db)
    contents = [f"message {i}" for i in range(8)]
    roles = ["user", "assistant"] * 4
    for role, content in zip(roles, contents):
        repo.add_message(db, session_row.id, role, content)  # type: ignore[arg-type]

    with Session(db_engine) as other:
        listed = repo.list_messages(other, session_row.id)

    assert [m.content for m in listed] == contents
    assert [m.role for m in listed] == roles


def test_list_messages_only_returns_that_sessions_messages(db: Session) -> None:
    first = repo.create_session(db)
    second = repo.create_session(db)
    repo.add_message(db, first.id, "user", "for first")
    repo.add_message(db, second.id, "user", "for second")

    assert [m.content for m in repo.list_messages(db, first.id)] == ["for first"]
    assert [m.content for m in repo.list_messages(db, second.id)] == ["for second"]


def test_list_messages_empty_for_new_session(db: Session) -> None:
    session_row = repo.create_session(db)
    assert repo.list_messages(db, session_row.id) == []


def test_add_message_unknown_session_raises(db: Session) -> None:
    with pytest.raises(ValueError):
        repo.add_message(db, "does-not-exist", "user", "hi")


# --- updated_at -----------------------------------------------------------------


def test_updated_at_bumps_on_new_message(db_engine: Engine, db: Session) -> None:
    session_row = repo.create_session(db)
    # Push updated_at into the past so the bump is visible even if the clock is coarse.
    old = datetime.now(timezone.utc) - timedelta(days=1)
    session_row.updated_at = old
    db.add(session_row)
    db.commit()

    repo.add_message(db, session_row.id, "user", "hello")

    with Session(db_engine) as other:
        fetched = repo.get_session(other, session_row.id)
        assert fetched is not None
        assert _naive_utc(fetched.updated_at) > _naive_utc(old)
        assert _naive_utc(fetched.updated_at) >= _naive_utc(fetched.created_at)


def test_updated_at_orders_sessions_by_latest_message(db: Session) -> None:
    older = repo.create_session(db)
    newer = repo.create_session(db)
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    for row in (older, newer):
        row.updated_at = yesterday
        db.add(row)
    db.commit()

    repo.add_message(db, older.id, "user", "most recent activity")

    refreshed_older = repo.get_session(db, older.id)
    refreshed_newer = repo.get_session(db, newer.id)
    assert refreshed_older is not None and refreshed_newer is not None
    assert _naive_utc(refreshed_older.updated_at) > _naive_utc(refreshed_newer.updated_at)


# --- profile --------------------------------------------------------------------


def test_update_profile_is_saved(db_engine: Engine, db: Session) -> None:
    session_row = repo.create_session(db)
    profile = {
        "cities": ["San Jose, CA"],
        "duration_days": 3,
        "travelers": 1,
        "budget_level": "budget",
        "interests": ["tech", "food"],
    }

    repo.update_profile(db, session_row.id, profile)

    with Session(db_engine) as other:
        fetched = repo.get_session(other, session_row.id)
        assert fetched is not None
        assert fetched.trip_profile == profile


def test_update_profile_twice_keeps_latest(db_engine: Engine, db: Session) -> None:
    session_row = repo.create_session(db)
    repo.update_profile(db, session_row.id, {"cities": ["Austin, TX"]})
    repo.update_profile(db, session_row.id, {"cities": ["Austin, TX"], "duration_days": 2})

    with Session(db_engine) as other:
        fetched = repo.get_session(other, session_row.id)
        assert fetched is not None
        assert fetched.trip_profile == {"cities": ["Austin, TX"], "duration_days": 2}


def test_update_profile_unknown_session_raises(db: Session) -> None:
    with pytest.raises(ValueError):
        repo.update_profile(db, "does-not-exist", {"cities": []})


# --- foreign key + cascade (contracts §1) ----------------------------------------


def test_message_requires_existing_session(db: Session) -> None:
    db.add(MessageRow(session_id="does-not-exist", role="user", content="orphan"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_deleting_session_cascades_to_messages(db_engine: Engine, db: Session) -> None:
    session_row = repo.create_session(db)
    repo.add_message(db, session_row.id, "user", "one")
    repo.add_message(db, session_row.id, "assistant", "two")
    session_id = session_row.id

    with Session(db_engine) as other:
        row = other.get(SessionRow, session_id)
        assert row is not None
        other.delete(row)
        other.commit()

    with Session(db_engine) as other:
        assert repo.list_messages(other, session_id) == []


# --- engine + startup -----------------------------------------------------------


def test_default_database_file_is_backend_travel_db() -> None:
    assert engine_module.DEFAULT_DATABASE_URL.startswith("sqlite:///")
    assert engine_module.DEFAULT_DATABASE_URL.endswith("backend/travel.db")


def test_app_startup_creates_db_file_and_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_file = tmp_path / "startup.db"
    fresh_engine = engine_module.make_engine(f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setattr(engine_module, "_engine", fresh_engine)
    assert not db_file.exists()

    with TestClient(create_app()):  # entering the client runs the lifespan startup
        pass

    try:
        assert db_file.exists()
        table_names = set(inspect(fresh_engine).get_table_names())
        assert {"session", "message"} <= table_names
    finally:
        fresh_engine.dispose()
