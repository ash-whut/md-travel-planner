"""Account routes (contracts §4): register, log in, log out, and the user's profile."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlmodel import Session

from app.core.auth import CurrentUser, bearer_token, hash_password, new_token, verify_password
from app.db import repo
from app.db.engine import get_db
from app.db.tables import UserRow
from app.schemas.user import AuthBody, AuthResponse, User, UserProfile, load_user_profile

router = APIRouter()

Db = Annotated[Session, Depends(get_db)]


def to_user(row: UserRow) -> User:
    return User(id=row.id, username=row.username, profile=load_user_profile(row.profile))


@router.post("/auth/register", status_code=201)
def register(body: AuthBody, db: Db) -> AuthResponse:
    if repo.get_user_by_username(db, body.username) is not None:
        raise HTTPException(status_code=409, detail="That username is taken")
    user = repo.create_user(db, body.username, hash_password(body.password))
    return AuthResponse(token=repo.create_token(db, user.id, new_token()), user=to_user(user))


@router.post("/auth/login")
def login(body: AuthBody, db: Db) -> AuthResponse:
    user = repo.get_user_by_username(db, body.username)
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Wrong username or password")
    return AuthResponse(token=repo.create_token(db, user.id, new_token()), user=to_user(user))


@router.post("/auth/logout", status_code=204)
def logout(
    _user: CurrentUser, db: Db, authorization: Annotated[str | None, Header()] = None
) -> Response:
    token = bearer_token(authorization)
    if token:
        repo.delete_token(db, token)
    return Response(status_code=204)


@router.get("/me")
def me(user: CurrentUser) -> User:
    return to_user(user)


@router.put("/me/profile")
def update_my_profile(body: UserProfile, user: CurrentUser, db: Db) -> User:
    return to_user(repo.set_user_profile(db, user.id, body.model_dump(mode="json")))
