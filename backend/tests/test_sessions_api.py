"""Step 4: POST /api/sessions and GET /api/sessions/{id} return SessionDetail (contracts §2.6)."""

import re
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlmodel import Session

from app.db import repo
from app.schemas.profile import TripProfile

GREETING = "Hi, where do you want to go?"
SESSION_DETAIL_KEYS = {
    "id", "title", "status", "trip_profile", "messages", "itinerary", "created_at", "updated_at",
}
MESSAGE_KEYS = {"id", "role", "content", "itinerary_version", "created_at"}
TRIP_PROFILE_KEYS = {
    "cities", "vibe", "start_date", "end_date", "duration_days", "rough_timing", "origin",
    "travelers", "budget_level", "interests", "dietary", "pace", "transport", "notes",
    "missing_required",
}
# ISO-8601 UTC with a trailing Z (contracts conventions), optional fractional seconds.
UTC_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def _is_uuid4(value: str) -> bool:
    try:
        return uuid.UUID(value).version == 4
    except ValueError:
        return False


def _create(client: TestClient) -> dict[str, Any]:
    response = client.post("/api/sessions")
    assert response.status_code == 200
    return response.json()


# --- POST /api/sessions ---------------------------------------------------------------------


def test_create_returns_session_detail_shape(client: TestClient) -> None:
    body = _create(client)

    assert set(body) == SESSION_DETAIL_KEYS
    assert _is_uuid4(body["id"])
    assert body["title"] == "New trip"
    assert body["status"] == "intake"
    assert body["itinerary"] is None


def test_create_includes_exactly_one_greeting_message(client: TestClient) -> None:
    body = _create(client)

    assert len(body["messages"]) == 1
    message = body["messages"][0]
    assert set(message) == MESSAGE_KEYS
    assert message["role"] == "assistant"
    assert message["content"] == GREETING
    assert message["itinerary_version"] is None
    assert _is_uuid4(message["id"])


def test_create_returns_an_empty_trip_profile(client: TestClient) -> None:
    profile = _create(client)["trip_profile"]

    assert set(profile) == TRIP_PROFILE_KEYS
    assert profile["cities"] == []
    assert profile["interests"] == []
    # Step 16: the server computes missing_required (contracts §2.1), so a new session lists all.
    assert set(profile["missing_required"]) == {
        "destination", "dates", "origin", "travelers", "interests",
    }
    for key in TRIP_PROFILE_KEYS - {"cities", "interests", "missing_required"}:
        assert profile[key] is None, key


def test_create_timestamps_are_iso_utc_with_z(client: TestClient) -> None:
    body = _create(client)

    assert UTC_Z.match(body["created_at"]), body["created_at"]
    assert UTC_Z.match(body["updated_at"]), body["updated_at"]
    assert UTC_Z.match(body["messages"][0]["created_at"]), body["messages"][0]["created_at"]


def test_create_persists_session_and_greeting(client: TestClient, db: Session) -> None:
    body = _create(client)

    assert repo.get_session(db, body["id"]) is not None
    stored = repo.list_messages(db, body["id"])
    assert [(m.role, m.content) for m in stored] == [("assistant", GREETING)]


def test_each_create_makes_a_new_session(client: TestClient) -> None:
    first = _create(client)
    second = _create(client)

    assert first["id"] != second["id"]
    assert first["messages"][0]["id"] != second["messages"][0]["id"]


# --- GET /api/sessions/{id} -----------------------------------------------------------------


def test_get_returns_the_same_data_as_create(client: TestClient) -> None:
    created = _create(client)

    response = client.get(f"/api/sessions/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_has_null_itinerary(client: TestClient) -> None:
    created = _create(client)

    body = client.get(f"/api/sessions/{created['id']}").json()

    assert "itinerary" in body
    assert body["itinerary"] is None


def test_get_returns_messages_in_order(client: TestClient, db: Session) -> None:
    created = _create(client)
    repo.add_message(db, created["id"], "user", "San Jose please")
    repo.add_message(db, created["id"], "assistant", "Great, when?")

    body = client.get(f"/api/sessions/{created['id']}").json()

    assert [(m["role"], m["content"]) for m in body["messages"]] == [
        ("assistant", GREETING),
        ("user", "San Jose please"),
        ("assistant", "Great, when?"),
    ]


def test_get_reflects_stored_trip_profile(client: TestClient, db: Session) -> None:
    created = _create(client)
    repo.update_profile(
        db, created["id"], {"cities": ["San Jose, CA"], "travelers": 2, "interests": ["food"]}
    )

    profile = client.get(f"/api/sessions/{created['id']}").json()["trip_profile"]

    assert profile["cities"] == ["San Jose, CA"]
    assert profile["travelers"] == 2
    assert profile["interests"] == ["food"]
    assert profile["origin"] is None


def test_get_only_returns_that_sessions_messages(client: TestClient, db: Session) -> None:
    first = _create(client)
    second = _create(client)
    repo.add_message(db, second["id"], "user", "only in the second session")

    body = client.get(f"/api/sessions/{first['id']}").json()

    assert [m["content"] for m in body["messages"]] == [GREETING]


@pytest.mark.parametrize("session_id", [str(uuid.uuid4()), "not-a-uuid"])
def test_get_unknown_id_returns_404(client: TestClient, session_id: str) -> None:
    response = client.get(f"/api/sessions/{session_id}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Session not found"}


def test_get_unknown_id_after_creating_others_is_still_404(client: TestClient) -> None:
    _create(client)

    response = client.get(f"/api/sessions/{uuid.uuid4()}")

    assert response.status_code == 404


# --- TripProfile schema (contracts §2.1) ----------------------------------------------------


def test_trip_profile_all_fields_optional() -> None:
    profile = TripProfile()

    assert profile.cities == []
    assert profile.interests == []
    assert profile.missing_required == []
    assert profile.duration_days is None
    assert profile.travelers is None


def test_trip_profile_accepts_contract_example() -> None:
    profile = TripProfile.model_validate(
        {
            "cities": ["San Jose, CA"],
            "start_date": "2027-03-05",
            "end_date": "2027-03-07",
            "duration_days": 3,
            "origin": "College Station, TX",
            "travelers": 1,
            "budget_level": "budget",
            "interests": ["tech", "food", "gardens"],
            "dietary": "vegan",
            "pace": "balanced",
            "missing_required": [],
        }
    )

    assert profile.model_dump(mode="json")["start_date"] == "2027-03-05"


@pytest.mark.parametrize(
    "field",
    [
        {"cities": ["A", "B", "C"]},
        {"duration_days": 0},
        {"duration_days": 8},
        {"travelers": 0},
        {"travelers": 7},
        {"budget_level": "luxury"},
        {"pace": "fast"},
        {"transport": "boat"},
        {"missing_required": ["budget"]},
    ],
)
def test_trip_profile_rejects_out_of_contract_values(field: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        TripProfile.model_validate(field)


@pytest.mark.parametrize(
    "field",
    [
        {"cities": ["A", "B"]},
        {"duration_days": 1},
        {"duration_days": 7},
        {"travelers": 1},
        {"travelers": 6},
    ],
)
def test_trip_profile_accepts_boundary_values(field: dict[str, Any]) -> None:
    TripProfile.model_validate(field)
