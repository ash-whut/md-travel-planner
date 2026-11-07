"""SQLite engine for the app. Default file: backend/travel.db (override with DATABASE_URL)."""

from collections.abc import Iterator
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import BACKEND_DIR, get_settings

DEFAULT_DATABASE_URL = f"sqlite:///{(BACKEND_DIR / 'travel.db').as_posix()}"

# Created on first use. Tests replace it with a temp-file engine (see tests/conftest.py).
_engine: Engine | None = None


def make_engine(url: str) -> Engine:
    # check_same_thread=False: FastAPI runs sync routes in worker threads.
    engine = create_engine(url, connect_args={"check_same_thread": False})
    event.listen(engine, "connect", _enable_foreign_keys)
    return engine


def _enable_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
    # SQLite ignores foreign keys (and ON DELETE CASCADE) unless this is set per connection.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = make_engine(get_settings().database_url or DEFAULT_DATABASE_URL)
    return _engine


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one database session per request."""
    with Session(get_engine()) as db:
        yield db


def create_tables(engine: Engine) -> None:
    import app.db.tables  # noqa: F401  (registers the tables on SQLModel.metadata)

    SQLModel.metadata.create_all(engine)
