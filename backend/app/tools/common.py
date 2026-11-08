"""Shared tool helpers (architecture §7): the result model, the mock switch and the api_cache.

Tools are plain synchronous functions that never raise to the caller: they return a
`ToolResult` with `ok=False` and a short `error` instead.
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from app.core.config import get_settings
from app.db.engine import get_engine
from app.db.tables import ApiCacheRow, utcnow

logger = logging.getLogger(__name__)

MOCKS_DIR = Path(__file__).resolve().parent / "mocks"
TIMEOUT_SECONDS = 10.0

# Cache lifetimes per tool (contracts §1, api_cache).
WEATHER_TTL_SECONDS = 3 * 60 * 60
PLACES_TTL_SECONDS = 7 * 24 * 60 * 60
HOTELS_TTL_SECONDS = 6 * 60 * 60
GEOCODE_TTL_SECONDS = 30 * 24 * 60 * 60  # city coordinates rarely change


class ToolResult(BaseModel):
    ok: bool
    data: Any = None
    error: str | None = None


def tool_ok(data: Any) -> ToolResult:
    return ToolResult(ok=True, data=data)


def tool_error(message: str) -> ToolResult:
    return ToolResult(ok=False, error=message)


def is_mock() -> bool:
    """True when tools should return recorded JSON instead of calling real services."""
    return get_settings().tool_provider_mode == "mock"


def load_mock(name: str) -> Any:
    """The parsed JSON of `tools/mocks/{name}.json`, e.g. load_mock("weather_forecast")."""
    path = MOCKS_DIR / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def cache_key(tool: str, args: dict[str, Any]) -> str:
    """`"{tool}:{sha256 of the args JSON}"`; sorted keys, so argument order doesn't matter."""
    args_json = json.dumps(args, sort_keys=True, default=str)
    return f"{tool}:{hashlib.sha256(args_json.encode('utf-8')).hexdigest()}"


def cache_get(tool: str, args: dict[str, Any], now: datetime | None = None) -> Any | None:
    """The cached value for this call, or None if there is none or it has expired."""
    now = _as_utc(now or utcnow())
    with Session(get_engine()) as db:
        row = db.get(ApiCacheRow, cache_key(tool, args))
        if row is None:
            return None
        if now - _as_utc(row.created_at) >= timedelta(seconds=row.ttl_seconds):
            return None
        return row.value


def cache_set(
    tool: str, args: dict[str, Any], value: Any, ttl_seconds: int, now: datetime | None = None
) -> None:
    """Store a JSON-ready value for this call, replacing any earlier entry.

    Best-effort: a DB error is logged and ignored, since the tool already has its result. Two
    parallel calls (e.g. two searches geocoding the same city) can both miss the cache and race
    to insert the same key; the loser gets an IntegrityError, and the winner's row is kept.
    """
    row = ApiCacheRow(
        key=cache_key(tool, args), value=value, created_at=now or utcnow(), ttl_seconds=ttl_seconds
    )
    with Session(get_engine()) as db:
        try:
            db.merge(row)
            db.commit()
        except SQLAlchemyError as error:
            db.rollback()
            logger.warning("api_cache write for %s skipped: %s", tool, type(error).__name__)


def get_json(
    client: httpx.Client | None,
    url: str,
    params: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> Any:
    """GET and parse a JSON body. Raises httpx.HTTPError on network or HTTP errors.

    Uses `client` when given (tests pass one with a MockTransport), else a short-lived one."""
    http = client or httpx.Client(timeout=TIMEOUT_SECONDS)
    try:
        response = http.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response.json()
    finally:
        if client is None:
            http.close()


def describe_error(error: Exception) -> str:
    """A one-line reason without the request URL (which may hold a key), e.g. "HTTP 500"."""
    if isinstance(error, httpx.HTTPStatusError):
        return f"HTTP {error.response.status_code}"
    if isinstance(error, httpx.HTTPError):
        return type(error).__name__  # e.g. ConnectTimeout
    if isinstance(error, KeyError):
        return f"missing {error}"
    return str(error) or type(error).__name__


def _as_utc(moment: datetime) -> datetime:
    # SQLite hands datetimes back without a timezone; they were stored as UTC.
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
