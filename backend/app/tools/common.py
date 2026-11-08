"""Shared tool helpers (architecture §7): the result model, the mock switch and the api_cache.

Tools are plain synchronous functions that never raise to the caller: they return a
`ToolResult` with `ok=False` and a short `error` instead.
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from sqlmodel import Session

from app.core.config import get_settings
from app.db.engine import get_engine
from app.db.tables import ApiCacheRow, utcnow

MOCKS_DIR = Path(__file__).resolve().parent / "mocks"

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
    """Store a JSON-ready value for this call, replacing any earlier entry."""
    row = ApiCacheRow(
        key=cache_key(tool, args), value=value, created_at=now or utcnow(), ttl_seconds=ttl_seconds
    )
    with Session(get_engine()) as db:
        db.merge(row)
        db.commit()


def _as_utc(moment: datetime) -> datetime:
    # SQLite hands datetimes back without a timezone; they were stored as UTC.
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
