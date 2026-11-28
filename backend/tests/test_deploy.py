"""Step 53: Vercel deploy. Postgres URL handling, SQLite-only engine bits, tables on first
get_engine(), the rowid tie-breaker only on SQLite, and the repo-root vercel.json.
All offline: Postgres engines are built but never connected."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine as sa_create_engine
from sqlalchemy import event, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Engine
from sqlmodel import Session

from app.core.config import get_settings
from app.db import engine as engine_module
from app.db import repo
from app.db.tables import MessageRow, SessionRow

REPO_ROOT = Path(__file__).resolve().parents[2]
FAKE_PG = "postgres://user:secret@db.example.invalid:5432/travel?sslmode=require"


# --- normalize_database_url --------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgres://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
        ("postgresql://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
        (
            "postgres://u:p@host:5432/db?sslmode=require",
            "postgresql+psycopg://u:p@host:5432/db?sslmode=require",
        ),
        (
            "postgresql://u:p@host/db?sslmode=require&channel_binding=require",
            "postgresql+psycopg://u:p@host/db?sslmode=require&channel_binding=require",
        ),
        ("postgresql+psycopg://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
        ("sqlite:///C:/data/travel.db", "sqlite:///C:/data/travel.db"),
        ("sqlite:///:memory:", "sqlite:///:memory:"),
    ],
)
def test_normalize_database_url(url: str, expected: str) -> None:
    assert engine_module.normalize_database_url(url) == expected


# --- make_engine -------------------------------------------------------------------


def _capture_create_engine(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def spy(url: str, **kwargs: Any) -> Engine:
        calls.append({"url": url, **kwargs})
        return sa_create_engine(url, **kwargs)

    monkeypatch.setattr(engine_module, "create_engine", spy)
    return calls


def test_sqlite_engine_gets_check_same_thread_and_foreign_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _capture_create_engine(monkeypatch)
    engine = engine_module.make_engine(f"sqlite:///{(tmp_path / 'fk.db').as_posix()}")
    try:
        assert calls[0]["connect_args"] == {"check_same_thread": False}
        assert event.contains(engine, "connect", engine_module._enable_foreign_keys)
        with engine.connect() as conn:
            assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
    finally:
        engine.dispose()


def test_sqlite_on_delete_cascade_still_works(db: Session) -> None:
    session_row = repo.create_session(db)
    repo.add_message(db, session_row.id, "user", "hi")
    repo.delete_session(db, session_row.id)

    remaining = db.connection().exec_driver_sql("SELECT COUNT(*) FROM message").scalar()
    assert remaining == 0


def test_postgres_engine_builds_without_connecting_or_sqlite_bits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _capture_create_engine(monkeypatch)

    def no_connect(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("make_engine must not open a connection")

    engine = engine_module.make_engine(FAKE_PG)
    monkeypatch.setattr(engine, "connect", no_connect)

    assert engine.dialect.name == "postgresql"
    assert engine.url.drivername == "postgresql+psycopg"
    assert engine.url.query.get("sslmode") == "require"
    assert "connect_args" not in calls[0]
    assert calls[0].get("pool_pre_ping") is True
    assert not event.contains(engine, "connect", engine_module._enable_foreign_keys)
    engine.dispose()


# --- get_engine creates tables on first use ----------------------------------------


def test_get_engine_creates_tables_on_first_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_file = tmp_path / "fresh.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setattr(engine_module, "_engine", None)
    get_settings.cache_clear()
    try:
        engine = engine_module.get_engine()
        try:
            assert engine.url.database == db_file.as_posix()
            tables = set(inspect(engine).get_table_names())
            assert {"session", "message", "itinerary", "api_cache", "user", "auth_token"} <= tables
            assert "user_id" in {c["name"] for c in inspect(engine).get_columns("session")}
            assert engine_module.get_engine() is engine  # cached after the first call
        finally:
            engine.dispose()
    finally:
        get_settings.cache_clear()


# --- _add_missing_columns ----------------------------------------------------------


def test_add_missing_columns_adds_user_id_to_old_session_table(tmp_path: Path) -> None:
    engine = engine_module.make_engine(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "CREATE TABLE session (id VARCHAR PRIMARY KEY, title VARCHAR NOT NULL, "
                "title_is_custom BOOLEAN NOT NULL, status VARCHAR NOT NULL, "
                "trip_profile JSON NOT NULL, created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL)"
            )
        engine_module.create_tables(engine)

        columns = {c["name"] for c in inspect(engine).get_columns("session")}
        assert "user_id" in columns
        engine_module.create_tables(engine)  # a second run must not try to add it again
    finally:
        engine.dispose()


# --- repo ordering: rowid tie-breaker only on SQLite -------------------------------


def test_messages_with_equal_timestamps_keep_insertion_order(db: Session) -> None:
    session_row = repo.create_session(db)
    same = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(5):
        db.add(MessageRow(session_id=session_row.id, role="user", content=f"m{i}", created_at=same))
        db.commit()

    assert [m.content for m in repo.list_messages(db, session_row.id)] == [
        "m0",
        "m1",
        "m2",
        "m3",
        "m4",
    ]


def test_sessions_with_equal_timestamps_list_newest_created_first(db: Session) -> None:
    same = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ids = []
    for _ in range(3):
        row = SessionRow(created_at=same, updated_at=same)
        db.add(row)
        db.commit()
        ids.append(row.id)

    assert [s.id for s in repo.list_sessions(db)] == list(reversed(ids))


class _CaptureDb:
    """Stands in for a Session bound to Postgres: records the statement, returns no rows."""

    def __init__(self) -> None:
        self.bind = sa_create_engine("postgresql+psycopg://u:p@db.example.invalid/x")
        self.statements: list[Any] = []

    def get_bind(self) -> Engine:
        return self.bind

    def exec(self, statement: Any) -> Any:
        self.statements.append(statement)
        return self

    def all(self) -> list[Any]:
        return []


@pytest.mark.parametrize(
    "call",
    [
        lambda db: repo.list_messages(db, "s1"),
        lambda db: repo.list_sessions(db),
        lambda db: repo.list_sessions(db, "u1"),
    ],
)
def test_ordering_has_no_rowid_on_postgres(call: Any) -> None:
    fake = _CaptureDb()
    try:
        assert call(fake) == []
        sql = str(fake.statements[0].compile(dialect=postgresql.dialect()))
        assert "ORDER BY" in sql
        assert "rowid" not in sql.lower()
    finally:
        fake.bind.dispose()


def test_ordering_uses_rowid_on_sqlite(db_engine: Engine) -> None:
    with Session(db_engine) as real:
        captured: list[Any] = []
        original_exec = real.exec

        def spy(statement: Any) -> Any:
            captured.append(statement)
            return original_exec(statement)

        real.exec = spy  # type: ignore[method-assign]
        repo.list_messages(real, "missing")
        assert "rowid" in str(captured[0]).lower()


# --- vercel.json -------------------------------------------------------------------


def test_vercel_json_routes_api_to_backend_before_frontend() -> None:
    config = json.loads((REPO_ROOT / "vercel.json").read_text(encoding="utf-8"))

    rewrites = config["rewrites"]
    api_index = next(
        i
        for i, r in enumerate(rewrites)
        if r["source"].startswith("/api") and r["destination"].get("service") == "backend"
    )
    catch_all_index = next(
        i
        for i, r in enumerate(rewrites)
        if r["source"] in ("/(.*)", "/:path*") and r["destination"].get("service") == "frontend"
    )
    assert api_index < catch_all_index

    services = config["services"]
    assert services["frontend"]["root"].rstrip("/") == "frontend"
    assert services["backend"]["root"].rstrip("/") == "backend"
    # No `functions` block: Hobby's default duration is already its 300 s maximum, and a
    # pattern that matches no function file would fail the Vercel build (D37).
    assert "functions" not in services["backend"]
