"""Step 44: history routes (GET/PATCH/DELETE /api/sessions) and the auto-title (contracts §4, §5)."""

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from app.agent.turn import auto_title
from app.db import repo
from app.db.tables import ItineraryRow, MessageRow, SessionRow
from app.schemas.itinerary import Itinerary
from app.schemas.profile import TripProfile

FIXTURES = Path(__file__).resolve().parents[2] / "frontend" / "src" / "fixtures"
SUMMARY_KEYS = {"id", "title", "status", "updated_at"}

Event = tuple[str, dict[str, Any]]


# --- helpers --------------------------------------------------------------------------------


def _parse_sse(text: str) -> list[Event]:
    """Parse a text/event-stream body into (event name, JSON data) pairs."""
    events: list[Event] = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        name = "message"
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:"):].lstrip(" "))
        if data_lines:
            events.append((name, json.loads("\n".join(data_lines))))
    return events


def _create(client: TestClient) -> str:
    response = client.post("/api/sessions")
    assert response.status_code == 200
    return response.json()["id"]


def _send(client: TestClient, session_id: str, content: str) -> list[Event]:
    response = client.post(f"/api/sessions/{session_id}/messages", json={"content": content})
    assert response.status_code == 200
    return _parse_sse(response.text)


def _set_updated_at(engine: Engine, session_id: str, when: datetime) -> None:
    with Session(engine) as db:
        row = db.get(SessionRow, session_id)
        assert row is not None
        row.updated_at = when
        db.add(row)
        db.commit()


def _set_profile(engine: Engine, session_id: str, **fields: Any) -> None:
    with Session(engine) as db:
        repo.update_profile(db, session_id, TripProfile(**fields).model_dump(mode="json"))


def _row(engine: Engine, session_id: str) -> SessionRow | None:
    with Session(engine) as db:
        return db.get(SessionRow, session_id)


def _itinerary() -> Itinerary:
    data = json.loads((FIXTURES / "sanjose-v1.json").read_text(encoding="utf-8"))
    return Itinerary.model_validate(data)


# In the past, so a message sent now is always newer.
T0 = datetime(2020, 1, 1, 12, 0, tzinfo=timezone.utc)


# --- GET /sessions ------------------------------------------------------------------------


def test_list_is_empty_without_sessions(client: TestClient) -> None:
    response = client.get("/api/sessions")
    assert response.status_code == 200
    assert response.json() == []


def test_list_is_newest_updated_first(client: TestClient, db_engine: Engine) -> None:
    old, middle, new = _create(client), _create(client), _create(client)
    _set_updated_at(db_engine, old, T0)
    _set_updated_at(db_engine, middle, T0 + timedelta(hours=1))
    _set_updated_at(db_engine, new, T0 + timedelta(hours=2))

    ids = [s["id"] for s in client.get("/api/sessions").json()]
    assert ids == [new, middle, old]


def test_a_new_message_moves_the_session_to_the_top(client: TestClient, db_engine: Engine) -> None:
    first, second = _create(client), _create(client)
    _set_updated_at(db_engine, first, T0)
    _set_updated_at(db_engine, second, T0 + timedelta(hours=1))

    _send(client, first, "hello")

    ids = [s["id"] for s in client.get("/api/sessions").json()]
    assert ids == [first, second]


def test_list_items_are_session_summaries(client: TestClient) -> None:
    session_id = _create(client)
    [summary] = client.get("/api/sessions").json()
    assert set(summary) == SUMMARY_KEYS
    assert summary["id"] == session_id
    assert summary["title"] == "New trip"
    assert summary["status"] == "intake"
    assert summary["updated_at"].endswith("Z")


# --- PATCH /sessions/{id} -----------------------------------------------------------------


def test_rename_returns_the_summary_and_sets_custom(client: TestClient, db_engine: Engine) -> None:
    session_id = _create(client)
    response = client.patch(f"/api/sessions/{session_id}", json={"title": "  Spring break  "})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == SUMMARY_KEYS
    assert body["title"] == "Spring break"  # trimmed
    row = _row(db_engine, session_id)
    assert row is not None and row.title == "Spring break" and row.title_is_custom


def test_rename_shows_in_get_and_list(client: TestClient) -> None:
    session_id = _create(client)
    client.patch(f"/api/sessions/{session_id}", json={"title": "Spring break"})
    assert client.get(f"/api/sessions/{session_id}").json()["title"] == "Spring break"
    assert client.get("/api/sessions").json()[0]["title"] == "Spring break"


def test_rename_does_not_move_the_session_to_the_top(client: TestClient, db_engine: Engine) -> None:
    first, second = _create(client), _create(client)
    _set_updated_at(db_engine, first, T0)
    _set_updated_at(db_engine, second, T0 + timedelta(hours=1))

    client.patch(f"/api/sessions/{first}", json={"title": "Renamed"})

    ids = [s["id"] for s in client.get("/api/sessions").json()]
    assert ids == [second, first]


@pytest.mark.parametrize("title", ["", "   ", "x" * 81])
def test_rename_rejects_bad_titles(client: TestClient, title: str) -> None:
    session_id = _create(client)
    response = client.patch(f"/api/sessions/{session_id}", json={"title": title})
    assert response.status_code == 422


def test_rename_accepts_80_chars(client: TestClient) -> None:
    session_id = _create(client)
    response = client.patch(f"/api/sessions/{session_id}", json={"title": "x" * 80})
    assert response.status_code == 200


def test_rename_unknown_session_is_404(client: TestClient) -> None:
    response = client.patch("/api/sessions/nope", json={"title": "Trip"})
    assert response.status_code == 404


# --- DELETE /sessions/{id} ----------------------------------------------------------------


def test_delete_removes_the_session_its_messages_and_itineraries(
    client: TestClient, db_engine: Engine
) -> None:
    session_id = _create(client)
    _send(client, session_id, "hello")
    with Session(db_engine) as db:
        repo.save_itinerary(db, session_id, _itinerary())

    response = client.delete(f"/api/sessions/{session_id}")

    assert response.status_code == 204
    assert response.content == b""
    with Session(db_engine) as db:
        assert db.get(SessionRow, session_id) is None
        assert db.exec(select(MessageRow).where(MessageRow.session_id == session_id)).all() == []
        assert db.exec(select(ItineraryRow).where(ItineraryRow.session_id == session_id)).all() == []
    assert client.get(f"/api/sessions/{session_id}").status_code == 404
    assert client.get("/api/sessions").json() == []


def test_delete_leaves_other_sessions_alone(client: TestClient, db_engine: Engine) -> None:
    keep, remove = _create(client), _create(client)
    with Session(db_engine) as db:
        repo.save_itinerary(db, keep, _itinerary())

    client.delete(f"/api/sessions/{remove}")

    assert [s["id"] for s in client.get("/api/sessions").json()] == [keep]
    detail = client.get(f"/api/sessions/{keep}").json()
    assert len(detail["messages"]) == 1  # the greeting
    assert detail["itinerary"] is not None


def test_delete_unknown_session_is_404(client: TestClient) -> None:
    assert client.delete("/api/sessions/nope").status_code == 404


# --- auto_title (pure) --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"cities": ["San Jose"], "start_date": date(2027, 3, 5), "end_date": date(2027, 3, 7)},
         "San Jose · Mar 5–7"),
        ({"cities": ["San Jose, CA"], "start_date": date(2027, 3, 5), "end_date": date(2027, 3, 7)},
         "San Jose · Mar 5–7"),
        ({"cities": ["Austin"], "start_date": date(2027, 3, 30), "end_date": date(2027, 4, 2)},
         "Austin · Mar 30–Apr 2"),
        ({"cities": ["Dallas", "Fort Worth"], "start_date": date(2027, 3, 6),
          "end_date": date(2027, 3, 9)},
         "Dallas & Fort Worth · Mar 6–9"),
        ({"cities": ["Austin"], "start_date": date(2027, 3, 5), "end_date": date(2027, 3, 5)},
         "Austin · Mar 5"),
        ({"cities": ["Austin"], "start_date": date(2027, 3, 5), "duration_days": 3},
         "Austin · Mar 5–7"),
        ({"cities": ["Austin"], "start_date": date(2027, 3, 31), "duration_days": 2},
         "Austin · Mar 31–Apr 1"),
        ({"cities": ["Austin"], "start_date": date(2027, 3, 5)}, "Austin · Mar 5"),
    ],
)
def test_auto_title_format(fields: dict[str, Any], expected: str) -> None:
    assert auto_title(TripProfile(**fields)) == expected


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"cities": ["Austin"]},
        {"start_date": date(2027, 3, 5), "end_date": date(2027, 3, 7)},
        {"vibe": "beach weekend", "start_date": date(2027, 3, 5)},
        {"cities": ["Austin"], "rough_timing": "a weekend in March", "duration_days": 2},
    ],
)
def test_no_auto_title_without_a_city_and_start_date(fields: dict[str, Any]) -> None:
    assert auto_title(TripProfile(**fields)) is None


# --- auto-title in a chat turn -------------------------------------------------------------


def test_title_event_after_city_and_dates_are_known(client: TestClient, db_engine: Engine) -> None:
    session_id = _create(client)
    # The fake LLM turns these phrases into cities=["San Jose, CA"], Mar 5–7 2027.
    events = _send(client, session_id, "San Jose, the first weekend of March")

    names = [name for name, _ in events]
    assert names.count("title") == 1
    assert names[0] == "message_start"
    assert names.index("profile") < names.index("title") < names.index("token")
    assert dict(events)["title"] == {"title": "San Jose · Mar 5–7"}
    row = _row(db_engine, session_id)
    assert row is not None and row.title == "San Jose · Mar 5–7" and not row.title_is_custom
    assert client.get("/api/sessions").json()[0]["title"] == "San Jose · Mar 5–7"


def test_no_title_event_while_details_are_missing(client: TestClient, db_engine: Engine) -> None:
    session_id = _create(client)
    events = _send(client, session_id, "San Jose sounds fun")  # a city, no dates
    assert "title" not in [name for name, _ in events]
    row = _row(db_engine, session_id)
    assert row is not None and row.title == "New trip"


def test_title_event_fires_once(client: TestClient) -> None:
    session_id = _create(client)
    first = _send(client, session_id, "San Jose, the first weekend of March")
    second = _send(client, session_id, "sounds good")
    third = _send(client, session_id, "San Jose, the first weekend of March")  # same details again

    assert [name for name, _ in first].count("title") == 1
    assert "title" not in [name for name, _ in second]
    assert "title" not in [name for name, _ in third]


def test_title_follows_a_new_destination(client: TestClient, db_engine: Engine) -> None:
    session_id = _create(client)
    _set_profile(db_engine, session_id, cities=["Austin"], start_date=date(2027, 3, 5),
                 end_date=date(2027, 3, 7))
    assert dict(_send(client, session_id, "hello"))["title"] == {"title": "Austin · Mar 5–7"}

    _set_profile(db_engine, session_id, cities=["Dallas"], start_date=date(2027, 3, 5),
                 end_date=date(2027, 3, 7))
    assert dict(_send(client, session_id, "hello"))["title"] == {"title": "Dallas · Mar 5–7"}


def test_rename_stops_auto_titling(client: TestClient, db_engine: Engine) -> None:
    session_id = _create(client)
    client.patch(f"/api/sessions/{session_id}", json={"title": "Spring break"})

    events = _send(client, session_id, "San Jose, the first weekend of March")

    assert "title" not in [name for name, _ in events]
    row = _row(db_engine, session_id)
    assert row is not None and row.title == "Spring break" and row.title_is_custom
