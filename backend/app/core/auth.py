"""Password hashing, login tokens, and the current-user dependency (decisions D32)."""

import hashlib
import hmac
import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlmodel import Session

from app.db import repo
from app.db.engine import get_db
from app.db.tables import UserRow

ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _scheme, iterations, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
        )
    except ValueError:
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def bearer_token(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


def optional_user(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> UserRow | None:
    """The logged-in user, or None without a token. A token that is sent but unknown is a 401,
    so the app can send the user back to the login screen."""
    token = bearer_token(authorization)
    if token is None:
        return None
    user = repo.get_user_by_token(db, token)
    if user is None:
        raise HTTPException(status_code=401, detail="Please log in again")
    return user


def require_user(user: Annotated[UserRow | None, Depends(optional_user)]) -> UserRow:
    if user is None:
        raise HTTPException(status_code=401, detail="Please log in")
    return user


OptionalUser = Annotated[UserRow | None, Depends(optional_user)]
CurrentUser = Annotated[UserRow, Depends(require_user)]
