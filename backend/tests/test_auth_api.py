"""Accounts (decisions D32): register, log in, log out, the user profile, per-user trips."""

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.auth import hash_password, verify_password
from app.db import repo


def _register(client: TestClient, username: str = "sean", password: str = "ducks123") -> str:
    res = client.post("/api/auth/register", json={"username": username, "password": password})
    assert res.status_code == 201, res.text
    return res.json()["token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_password_hash_round_trip() -> None:
    stored = hash_password("ducks123")
    assert stored != "ducks123"
    assert verify_password("ducks123", stored)
    assert not verify_password("wrong", stored)
    assert not verify_password("ducks123", "garbage")


def test_register_login_me_logout(client: TestClient) -> None:
    token = _register(client, "Sean")

    me = client.get("/api/me", headers=_auth(token))
    assert me.status_code == 200
    assert me.json()["username"] == "sean"  # stored lower-case
    assert me.json()["profile"]["interests"] == []

    login = client.post("/api/auth/login", json={"username": "SEAN", "password": "ducks123"})
    assert login.status_code == 200
    second = login.json()["token"]
    assert second != token

    assert client.post("/api/auth/logout", headers=_auth(second)).status_code == 204
    assert client.get("/api/me", headers=_auth(second)).status_code == 401
    assert client.get("/api/me", headers=_auth(token)).status_code == 200  # other login stays


def test_register_rejects_taken_username_and_bad_input(client: TestClient) -> None:
    _register(client)
    taken = client.post("/api/auth/register", json={"username": "sean", "password": "another1"})
    assert taken.status_code == 409
    short = client.post("/api/auth/register", json={"username": "ab", "password": "ducks123"})
    assert short.status_code == 422
    weak = client.post("/api/auth/register", json={"username": "aadi", "password": "123"})
    assert weak.status_code == 422


def test_login_wrong_password_and_unknown_user(client: TestClient) -> None:
    _register(client)
    bad = client.post("/api/auth/login", json={"username": "sean", "password": "nope-nope"})
    assert bad.status_code == 401
    unknown = client.post("/api/auth/login", json={"username": "ghost", "password": "ducks123"})
    assert unknown.status_code == 401


def test_me_needs_a_valid_token(client: TestClient) -> None:
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers=_auth("not-a-token")).status_code == 401


def test_profile_update_and_new_trip_is_seeded(client: TestClient) -> None:
    token = _register(client)
    profile = {
        "home_city": " College Station ",
        "budget_level": "budget",
        "dietary": "vegan",
        "pace": "relaxed",
        "transport": "rideshare",
        "interests": ["food", " ", "museums"],
    }
    res = client.put("/api/me/profile", json=profile, headers=_auth(token))
    assert res.status_code == 200
    saved = res.json()["profile"]
    assert saved["home_city"] == "College Station"
    assert saved["interests"] == ["food", "museums"]

    trip = client.post("/api/sessions", headers=_auth(token)).json()
    tp = trip["trip_profile"]
    assert tp["origin"] == "College Station"
    assert tp["budget_level"] == "budget"
    assert tp["dietary"] == "vegan"
    assert tp["pace"] == "relaxed"
    assert tp["transport"] == "rideshare"
    assert tp["interests"] == ["food", "museums"]
    assert "origin" not in tp["missing_required"]


def test_profile_rejects_unknown_values(client: TestClient) -> None:
    token = _register(client)
    res = client.put("/api/me/profile", json={"pace": "sprint"}, headers=_auth(token))
    assert res.status_code == 422


def test_trips_are_per_user(client: TestClient) -> None:
    sean = _register(client, "sean")
    aadi = _register(client, "aadi")
    mine = client.post("/api/sessions", headers=_auth(sean)).json()["id"]
    theirs = client.post("/api/sessions", headers=_auth(aadi)).json()["id"]
    anonymous = client.post("/api/sessions").json()["id"]

    assert [s["id"] for s in client.get("/api/sessions", headers=_auth(sean)).json()] == [mine]
    assert [s["id"] for s in client.get("/api/sessions", headers=_auth(aadi)).json()] == [theirs]
    assert [s["id"] for s in client.get("/api/sessions").json()] == [anonymous]

    # Someone else's trip looks like it doesn't exist.
    assert client.get(f"/api/sessions/{theirs}", headers=_auth(sean)).status_code == 404
    rename = client.patch(f"/api/sessions/{theirs}", json={"title": "x"}, headers=_auth(sean))
    assert rename.status_code == 404
    assert client.delete(f"/api/sessions/{theirs}", headers=_auth(sean)).status_code == 404
    assert client.get(f"/api/sessions/{mine}", headers=_auth(sean)).status_code == 200


def test_trip_preferences_are_learned_into_the_user_profile(client: TestClient, db: Session) -> None:
    token = _register(client)
    trip = client.post("/api/sessions", headers=_auth(token)).json()
    user = repo.get_user_by_username(db, "sean")
    assert user is not None

    # A chat turn saving a dietary preference (as the understand step does).
    repo.update_profile(db, trip["id"], {**trip["trip_profile"], "dietary": "vegan", "cities": ["San Jose"]})

    profile = client.get("/api/me", headers=_auth(token)).json()["profile"]
    assert profile["dietary"] == "vegan"
    # Trip-only details (destination) are not copied to the account.
    assert profile["home_city"] is None
    # The next trip starts with it.
    next_trip = client.post("/api/sessions", headers=_auth(token)).json()
    assert next_trip["trip_profile"]["dietary"] == "vegan"
    assert next_trip["trip_profile"]["cities"] == []


def test_anonymous_trip_profile_updates_touch_no_account(client: TestClient, db: Session) -> None:
    _register(client)
    trip = client.post("/api/sessions").json()
    repo.update_profile(db, trip["id"], {"dietary": "vegan"})
    user = repo.get_user_by_username(db, "sean")
    assert user is not None and user.profile == {}
