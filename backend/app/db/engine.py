"""Database engine, table creation and the per-request session (04-backend-design §2, §8)."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, event
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import get_settings
from app.db import tables  # noqa: F401  (registers the tables on SQLModel.metadata)


def make_engine(database_url: str) -> Engine:
    """Create an engine; for SQLite, turn on foreign keys so cascade deletes work."""
    is_sqlite = database_url.startswith("sqlite")
    # FastAPI runs sync routes in a thread pool, so SQLite connections cross threads.
    connect_args = {"check_same_thread": False} if is_sqlite else {}
    engine = create_engine(database_url, connect_args=connect_args)
    if is_sqlite:
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    # SQLite ignores FOREIGN KEY / ON DELETE CASCADE unless this is set on every connection.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@lru_cache
def get_engine() -> Engine:
    """The app's engine, built once from `DATABASE_URL` (default backend/travel.db)."""
    return make_engine(get_settings().database_url)


def init_db(engine: Engine | None = None) -> None:
    """Create any missing tables. Called on app startup; existing tables are left as they are."""
    SQLModel.metadata.create_all(engine or get_engine())


def get_session() -> Iterator[Session]:
    """FastAPI dependency: `session: Session = Depends(get_session)`.

    Outside a route (e.g. inside an SSE generator) use a short `with Session(get_engine())`
    block instead, and never hold it across an LLM await (04 §7.0).
    """
    with Session(get_engine()) as session:
        yield session
