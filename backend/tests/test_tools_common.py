"""Step 28: ToolResult helpers, mock switch + loading, the api_cache with TTL, and the
status() wrapper around a tool call (in agent/planner.py since step 33a)."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select

from app.agent import planner
from app.core.config import get_settings
from app.db.tables import ApiCacheRow
from app.tools import common
from app.tools.common import (
    HOTELS_TTL_SECONDS,
    PLACES_TTL_SECONDS,
    WEATHER_TTL_SECONDS,
    ToolResult,
    cache_get,
    cache_set,
    is_mock,
    load_mock,
    tool_error,
    tool_ok,
)

T0 = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
ARGS = {"lat": 37.33, "lng": -121.89, "start": "2026-03-05", "end": "2026-03-07"}
VALUE = {"days": [{"date": "2026-03-05", "high_f": 68, "low_f": 50}]}


# ---- ToolResult ----

def test_tool_ok_and_tool_error() -> None:
    ok = tool_ok({"a": 1})
    assert ok == ToolResult(ok=True, data={"a": 1}, error=None)
    failed = tool_error("timed out")
    assert failed.ok is False
    assert failed.error == "timed out"
    assert failed.data is None


# ---- Mock switch + loading ----

def test_is_mock_follows_tool_provider_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    assert is_mock() is True  # conftest sets TOOL_PROVIDER_MODE=mock
    monkeypatch.setenv("TOOL_PROVIDER_MODE", "live")
    get_settings.cache_clear()
    try:
        assert is_mock() is False
    finally:
        monkeypatch.setenv("TOOL_PROVIDER_MODE", "mock")
        get_settings.cache_clear()


def test_load_mock_reads_named_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"hourly": [1, 2, 3], "city": "San José"}
    (tmp_path / "weather_forecast.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(common, "MOCKS_DIR", tmp_path)
    assert load_mock("weather_forecast") == payload


def test_load_mock_missing_file_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(common, "MOCKS_DIR", tmp_path)
    with pytest.raises(FileNotFoundError):
        load_mock("does_not_exist")


def test_default_mocks_dir_is_tools_mocks() -> None:
    assert common.MOCKS_DIR.name == "mocks"
    assert common.MOCKS_DIR.parent.name == "tools"
    assert common.MOCKS_DIR.is_dir()


# ---- api_cache ----

def test_api_cache_table_exists(db_engine: Engine) -> None:
    columns = {c["name"] for c in inspect(db_engine).get_columns("api_cache")}
    assert columns == {"key", "value", "created_at", "ttl_seconds"}


def test_ttl_constants_match_contract() -> None:
    assert WEATHER_TTL_SECONDS == 3 * 3600
    assert PLACES_TTL_SECONDS == 7 * 24 * 3600
    assert HOTELS_TTL_SECONDS == 6 * 3600


def test_cache_miss_returns_none() -> None:
    assert cache_get("weather", ARGS, now=T0) is None


def test_cache_hit_within_ttl() -> None:
    cache_set("weather", ARGS, VALUE, WEATHER_TTL_SECONDS, now=T0)
    assert cache_get("weather", ARGS, now=T0) == VALUE
    later = T0 + timedelta(seconds=WEATHER_TTL_SECONDS - 1)
    assert cache_get("weather", ARGS, now=later) == VALUE


def test_cache_expires_at_ttl() -> None:
    cache_set("weather", ARGS, VALUE, WEATHER_TTL_SECONDS, now=T0)
    assert cache_get("weather", ARGS, now=T0 + timedelta(seconds=WEATHER_TTL_SECONDS)) is None
    assert cache_get("weather", ARGS, now=T0 + timedelta(days=1)) is None


def test_cache_key_ignores_arg_order() -> None:
    cache_set("weather", {"a": 1, "b": 2}, VALUE, 60, now=T0)
    assert cache_get("weather", {"b": 2, "a": 1}, now=T0) == VALUE


def test_cache_separates_tools_and_args() -> None:
    cache_set("weather", ARGS, VALUE, 60, now=T0)
    assert cache_get("places", ARGS, now=T0) is None
    assert cache_get("weather", {**ARGS, "lat": 0.0}, now=T0) is None


def test_cache_set_replaces_earlier_entry() -> None:
    cache_set("weather", ARGS, {"v": 1}, 60, now=T0)
    later = T0 + timedelta(seconds=120)  # first entry would be expired here
    cache_set("weather", ARGS, {"v": 2}, 60, now=later)
    assert cache_get("weather", ARGS, now=later) == {"v": 2}


def test_cache_set_stores_row_with_contract_key(db_engine: Engine) -> None:
    cache_set("weather", ARGS, VALUE, WEATHER_TTL_SECONDS, now=T0)
    with Session(db_engine) as db:
        rows = list(db.exec(select(ApiCacheRow)).all())
    assert len(rows) == 1
    key = rows[0].key
    tool, digest = key.split(":", 1)
    assert tool == "weather"
    assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)
    assert rows[0].ttl_seconds == WEATHER_TTL_SECONDS
    assert rows[0].value == VALUE


def test_cache_get_default_now_uses_current_time() -> None:
    cache_set("weather", ARGS, VALUE, 60)
    assert cache_get("weather", ARGS) == VALUE


def test_cache_set_survives_a_duplicate_key_race(
    db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two parallel calls both miss the cache; the other one inserts first. A plain INSERT of the
    # same key then raises IntegrityError, which cache_set must swallow (the tool has its data).
    cache_set("place_geocode", ARGS, {"v": "first"}, 60, now=T0)
    monkeypatch.setattr(common.Session, "merge", lambda self, row: self.add(row))

    cache_set("place_geocode", ARGS, {"v": "second"}, 60, now=T0)  # must not raise

    assert cache_get("place_geocode", ARGS, now=T0) == {"v": "first"}
    with Session(db_engine) as db:
        assert len(list(db.exec(select(ApiCacheRow)).all())) == 1


def test_cache_set_ignores_a_db_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_commit(self: Session) -> None:
        raise OperationalError("COMMIT", {}, Exception("database is locked"))

    monkeypatch.setattr(common.Session, "commit", broken_commit)

    cache_set("weather", ARGS, VALUE, 60, now=T0)  # must not raise

    monkeypatch.undo()
    assert cache_get("weather", ARGS, now=T0) is None


# ---- planner.status() ----

def collect(label: str, tool: Any, *args: Any) -> list[Any]:
    async def run() -> list[Any]:
        return [item async for item in planner.status(label, tool, *args)]

    return asyncio.run(run())


def status_events(items: list[Any]) -> list[dict[str, Any]]:
    events = [item for item in items if not isinstance(item, ToolResult)]
    assert all(e["event"] == "status" for e in events)
    return [json.loads(e["data"]) for e in events]


def test_status_emits_start_then_end_on_success() -> None:
    calls: list[tuple[Any, ...]] = []

    def tool(a: int, b: int) -> ToolResult:
        calls.append((a, b))
        return tool_ok(a + b)

    items = collect("Checking weather", tool, 2, 3)
    assert calls == [(2, 3)]
    assert status_events(items) == [
        {"label": "Checking weather", "state": "start"},
        {"label": "Checking weather", "state": "end"},
    ]
    assert len(items) == 3
    assert items[-1] == tool_ok(5)


def test_status_emits_start_then_error_on_failed_result() -> None:
    def tool() -> ToolResult:
        return tool_error("service down")

    items = collect("Checking weather", tool)
    assert status_events(items) == [
        {"label": "Checking weather", "state": "start"},
        {"label": "Checking weather", "state": "error"},
    ]
    assert items[-1] == tool_error("service down")


def test_status_turns_raising_tool_into_error() -> None:
    def tool() -> ToolResult:
        raise RuntimeError("boom")

    items = collect("Finding places", tool)
    assert status_events(items) == [
        {"label": "Finding places", "state": "start"},
        {"label": "Finding places", "state": "error"},
    ]
    result = items[-1]
    assert isinstance(result, ToolResult)
    assert result.ok is False
    assert result.error == "boom"


def test_status_raising_tool_without_message_still_has_error_text() -> None:
    def tool() -> ToolResult:
        raise ValueError()

    result = collect("x", tool)[-1]
    assert result.ok is False
    assert result.error
