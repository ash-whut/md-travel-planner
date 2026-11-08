"""Step 20: the `itinerary` table (contracts §1), its repo functions and GET returning the latest."""

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.db import repo
from app.db.tables import ItineraryRow, SessionRow
from app.schemas.itinerary import Itinerary

FIXTURES = Path(__file__).resolve().parents[2] / "frontend" / "src" / "fixtures"


def _itinerary(title: str = "San Jose weekend", version: int = 1) -> Itinerary:
    data: dict[str, Any] = json.loads((FIXTURES / "sanjose-v1.json").read_text(encoding="utf-8"))
    data["title"] = title
    data["version"] = version
    return Itinerary.model_validate(data)


# --- table ----------------------------------------------------------------------------------


def test_itinerary_table_has_contract_columns(db_engine: Engine) -> None:
    columns = {c["name"] for c in inspect(db_engine).get_columns("itinerary")}
    assert {"id", "session_id", "version", "data", "created_at"} <= columns


def test_session_id_and_version_are_unique_together(db: Session) -> None:
    session_row = repo.create_session(db)
    repo.save_itinerary(db, session_row.id, _itinerary())

    db.add(ItineraryRow(session_id=session_row.id, version=1, data={}))
    with pytest.raises(IntegrityError):
        db.commit()


def test_itinerary_requires_existing_session(db: Session) -> None:
    db.add(ItineraryRow(session_id="does-not-exist", version=1, data={}))
    with pytest.raises(IntegrityError):
        db.commit()


def test_deleting_session_cascades_to_itineraries(db_engine: Engine, db: Session) -> None:
    session_row = repo.create_session(db)
    repo.save_itinerary(db, session_row.id, _itinerary())
    repo.save_itinerary(db, session_row.id, _itinerary())
    session_id = session_row.id

    with Session(db_engine) as other:
        row = other.get(SessionRow, session_id)
        assert row is not None
        other.delete(row)
        other.commit()

    with Session(db_engine) as other:
        assert repo.list_itineraries(other, session_id) == []
        assert repo.get_latest_itinerary(other, session_id) is None


# --- save_itinerary: versions ---------------------------------------------------------------


def test_first_save_is_version_1(db: Session) -> None:
    session_row = repo.create_session(db)

    saved = repo.save_itinerary(db, session_row.id, _itinerary())

    assert saved.version == 1


def test_versions_increment_per_save(db: Session) -> None:
    session_row = repo.create_session(db)

    versions = [repo.save_itinerary(db, session_row.id, _itinerary()).version for _ in range(3)]

    assert versions == [1, 2, 3]


def test_save_ignores_the_version_passed_in(db: Session) -> None:
    session_row = repo.create_session(db)

    first = repo.save_itinerary(db, session_row.id, _itinerary(version=7))
    second = repo.save_itinerary(db, session_row.id, _itinerary(version=1))

    assert (first.version, second.version) == (1, 2)


def test_versions_are_counted_per_session(db: Session) -> None:
    first = repo.create_session(db)
    second = repo.create_session(db)
    repo.save_itinerary(db, first.id, _itinerary())
    repo.save_itinerary(db, first.id, _itinerary())

    assert repo.save_itinerary(db, second.id, _itinerary()).version == 1
    assert repo.save_itinerary(db, first.id, _itinerary()).version == 3


def test_save_keeps_the_itinerary_content(db_engine: Engine, db: Session) -> None:
    session_row = repo.create_session(db)
    original = _itinerary(title="Round trip")

    repo.save_itinerary(db, session_row.id, original)

    with Session(db_engine) as other:
        loaded = repo.get_latest_itinerary(other, session_row.id)
    assert loaded is not None
    assert loaded.model_dump(exclude={"version"}) == original.model_dump(exclude={"version"})


def test_save_unknown_session_raises(db: Session) -> None:
    with pytest.raises(ValueError):
        repo.save_itinerary(db, "does-not-exist", _itinerary())


# --- get_latest_itinerary / list_itineraries ------------------------------------------------


def test_get_latest_is_none_without_itineraries(db: Session) -> None:
    session_row = repo.create_session(db)
    assert repo.get_latest_itinerary(db, session_row.id) is None


def test_get_latest_returns_highest_version(db: Session) -> None:
    session_row = repo.create_session(db)
    for title in ("first", "second", "third"):
        repo.save_itinerary(db, session_row.id, _itinerary(title=title))

    latest = repo.get_latest_itinerary(db, session_row.id)

    assert latest is not None
    assert (latest.version, latest.title) == (3, "third")


def test_get_latest_only_looks_at_that_session(db: Session) -> None:
    first = repo.create_session(db)
    second = repo.create_session(db)
    repo.save_itinerary(db, first.id, _itinerary(title="first trip"))
    repo.save_itinerary(db, second.id, _itinerary(title="second trip"))
    repo.save_itinerary(db, second.id, _itinerary(title="second trip v2"))

    latest = repo.get_latest_itinerary(db, first.id)

    assert latest is not None
    assert (latest.version, latest.title) == (1, "first trip")


def test_list_itineraries_oldest_first(db: Session) -> None:
    session_row = repo.create_session(db)
    for title in ("v1", "v2", "v3"):
        repo.save_itinerary(db, session_row.id, _itinerary(title=title))

    listed = repo.list_itineraries(db, session_row.id)

    assert [(i.version, i.title) for i in listed] == [(1, "v1"), (2, "v2"), (3, "v3")]


def test_list_itineraries_empty_and_scoped_to_session(db: Session) -> None:
    first = repo.create_session(db)
    second = repo.create_session(db)
    repo.save_itinerary(db, second.id, _itinerary())

    assert repo.list_itineraries(db, first.id) == []
    assert len(repo.list_itineraries(db, second.id)) == 1


# --- GET /api/sessions/{id} -----------------------------------------------------------------


def test_create_still_has_null_itinerary(client: TestClient) -> None:
    assert client.post("/api/sessions").json()["itinerary"] is None


def test_get_includes_latest_itinerary(client: TestClient, db: Session) -> None:
    session_id = client.post("/api/sessions").json()["id"]
    repo.save_itinerary(db, session_id, _itinerary(title="old plan"))
    repo.save_itinerary(db, session_id, _itinerary(title="new plan"))

    response = client.get(f"/api/sessions/{session_id}")

    assert response.status_code == 200
    body = response.json()["itinerary"]
    assert body is not None
    assert body["version"] == 2
    assert body["title"] == "new plan"
    # The JSON still satisfies the Itinerary contract (§2.2).
    parsed = Itinerary.model_validate(body)
    assert parsed.model_dump(exclude={"version", "title"}) == _itinerary().model_dump(
        exclude={"version", "title"}
    )


def test_get_itinerary_is_per_session(client: TestClient, db: Session) -> None:
    with_plan = client.post("/api/sessions").json()["id"]
    without_plan = client.post("/api/sessions").json()["id"]
    repo.save_itinerary(db, with_plan, _itinerary())

    assert client.get(f"/api/sessions/{without_plan}").json()["itinerary"] is None
    assert client.get(f"/api/sessions/{with_plan}").json()["itinerary"]["version"] == 1
