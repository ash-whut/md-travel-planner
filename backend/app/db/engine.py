"""Database engine for the app.

Local dev and tests use SQLite (default file: backend/travel.db). A deployment sets
DATABASE_URL to a Postgres URL (Neon on Vercel, decisions D37).
"""

from collections.abc import Iterator
from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import BACKEND_DIR, get_settings

DEFAULT_DATABASE_URL = f"sqlite:///{(BACKEND_DIR / 'travel.db').as_posix()}"

# Created on first use. Tests replace it with a temp-file engine (see tests/conftest.py).
_engine: Engine | None = None


def normalize_database_url(url: str) -> str:
    """Point a plain Postgres URL (as Neon/Vercel give it) at the psycopg 3 driver.

    SQLAlchemy reads `postgresql://` as psycopg2 and doesn't know `postgres://` at all.
    Query parameters such as `?sslmode=require` are kept.
    """
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def make_engine(url: str) -> Engine:
    url = normalize_database_url(url)
    if not url.startswith("sqlite"):
        # pool_pre_ping: a serverless database closes idle connections; test before reuse.
        return create_engine(url, pool_pre_ping=True)
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
        engine = make_engine(get_settings().database_url or DEFAULT_DATABASE_URL)
        # Here, not only in the app lifespan: on Vercel a cold start may skip the lifespan.
        create_tables(engine)
        _engine = engine
    return _engine


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one database session per request."""
    with Session(get_engine()) as db:
        yield db


def create_tables(engine: Engine) -> None:
    import app.db.tables  # noqa: F401  (registers the tables on SQLModel.metadata)

    SQLModel.metadata.create_all(engine)
    _add_missing_columns(engine)


def _add_missing_columns(engine: Engine) -> None:
    # create_all never alters an existing table, so a travel.db made before accounts
    # (decisions D32) gets session.user_id added here.
    columns = {column["name"] for column in inspect(engine).get_columns("session")}
    if "user_id" not in columns:
        with engine.begin() as conn:
            conn.exec_driver_sql("ALTER TABLE session ADD COLUMN user_id VARCHAR")
