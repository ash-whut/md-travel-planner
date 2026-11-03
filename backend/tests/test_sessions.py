"""Session routes (03-contracts §3): POST /api/sessions and GET /api/sessions/{id}."""

from datetime import UTC, datetime
from uuid import UUID

from sqlmodel import Session, select

from app.agent.fixed_messages import GREETING
from app.db.tables import ItineraryRow, MessageRow, SessionRow
from app.schemas import SessionDetail


def add_session(engine, **fields) -> str:
    with Session(engine) as db:
        row = SessionRow(**fields)
        db.add(row)
        db.commit()
        return row.id


def test_create_session_returns_new_session_with_greeting(client):
    response = client.post("/api/sessions")

    assert response.status_code == 200
    body = response.json()
    SessionDetail.model_validate(body)  # matches the contract shape
    assert UUID(body["id"]).version == 4
    assert body["title"] == "New trip"
    assert body["status"] == "intake"
    assert body["trip_profile"]["cities"] == []
    assert body["trip_profile"]["budget_level"] == "budget"
    assert body["trip_profile"]["missing_required"] == []  # not computed until Stage 3
    assert body["itinerary"] is None
    assert body["chat_enabled"] is True
    assert body["created_at"].endswith("Z") and body["updated_at"].endswith("Z")

    [greeting] = body["messages"]
    assert greeting["role"] == "assistant"
    assert greeting["content"] == GREETING
    assert greeting["itinerary_version"] is None
    assert greeting["created_at"].endswith("Z")


def test_create_session_persists_session_and_greeting(client, engine):
    body = client.post("/api/sessions").json()

    with Session(engine) as db:
        row = db.get(SessionRow, body["id"])
        messages = db.exec(select(MessageRow).where(MessageRow.session_id == body["id"])).all()
    assert row.llm_provider == "fake"
    assert row.trip_profile == {} and row.agent_transcript == []
    assert [(m.id, m.role, m.content) for m in messages] == [(body["messages"][0]["id"], "assistant", GREETING)]


def test_each_post_creates_a_separate_session(client):
    first = client.post("/api/sessions").json()
    second = client.post("/api/sessions").json()

    assert first["id"] != second["id"]


def test_get_session_returns_what_post_created(client):
    created = client.post("/api/sessions").json()

    response = client.get(f"/api/sessions/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_unknown_session_is_404(client):
    response = client.get("/api/sessions/no-such-session")

    assert response.status_code == 404
    assert response.json() == {"detail": "Session not found"}


def test_get_session_orders_messages_by_created_at(client, engine):
    session_id = add_session(engine, llm_provider="fake")
    with Session(engine) as db:
        # Inserted out of order; the 2nd and 3rd share a timestamp -> insertion order wins.
        db.add(MessageRow(session_id=session_id, role="assistant", content="third", created_at=datetime(2026, 11, 2, 10, 5, tzinfo=UTC)))
        db.add(MessageRow(session_id=session_id, role="assistant", content="first", created_at=datetime(2026, 11, 2, 10, 0, tzinfo=UTC)))
        db.commit()
        db.add(MessageRow(session_id=session_id, role="user", content="fourth", created_at=datetime(2026, 11, 2, 10, 5, tzinfo=UTC)))
        db.commit()

    body = client.get(f"/api/sessions/{session_id}").json()

    assert [m["content"] for m in body["messages"]] == ["first", "third", "fourth"]


def test_get_session_returns_latest_itinerary(client, engine, austin):
    session_id = add_session(engine, llm_provider="fake", status="planned")
    newer = {**austin, "version": 2, "summary": "Second draft"}
    with Session(engine) as db:
        db.add(ItineraryRow(session_id=session_id, version=2, data=newer))
        db.add(ItineraryRow(session_id=session_id, version=1, data=austin))
        db.commit()

    body = client.get(f"/api/sessions/{session_id}").json()

    assert body["status"] == "planned"
    assert body["itinerary"]["version"] == 2
    assert body["itinerary"]["summary"] == "Second draft"


def test_chat_disabled_when_session_has_another_provider(client, engine):
    session_id = add_session(engine, llm_provider="anthropic")

    body = client.get(f"/api/sessions/{session_id}").json()

    assert body["chat_enabled"] is False
