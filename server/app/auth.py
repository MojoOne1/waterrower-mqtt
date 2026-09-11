"""Passwords, cookies and the FastAPI dependencies that guard the API.

Three athletes do not justify an identity provider, but they do justify not
storing passwords in the clear: scrypt is in the standard library, so the
whole thing costs one import and no dependency.
"""

import hashlib
import hmac
import secrets

from fastapi import Depends, HTTPException, Request

import config

COOKIE = "arena_session"
_SCRYPT = dict(n=2 ** 14, r=8, p=1, dklen=32)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, salt_hex, dk_hex = stored.split("$")
    except ValueError:
        return False
    if algo != "scrypt":
        return False
    dk = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), **_SCRYPT)
    return hmac.compare_digest(dk.hex(), dk_hex)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """Tokens are stored hashed; a leaked database must not hand out logins."""
    return hashlib.sha256(token.encode()).hexdigest()


def set_cookie(response, token: str) -> None:
    response.set_cookie(
        COOKIE, token,
        max_age=int(config.SESSION_DAYS * 86400),
        httponly=True, samesite="lax", secure=config.SECURE_COOKIES, path="/",
    )


def clear_cookie(response) -> None:
    response.delete_cookie(COOKIE, path="/")


# --- Dependencies ---------------------------------------------------------
# `db` is injected by main.py at import time to keep this module free of a
# circular import back to the application object.

db = None


def athlete_from_cookie(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    return db.web_session_owner(token_hash(token))


def current_athlete(request: Request) -> dict:
    athlete = athlete_from_cookie(request)
    if not athlete:
        raise HTTPException(401, "Not signed in")
    return athlete


def current_admin(athlete: dict = Depends(current_athlete)) -> dict:
    if not athlete["is_admin"]:
        raise HTTPException(403, "Admins only")
    return athlete


def public_athlete(row: dict) -> dict:
    """An athlete as the UI is allowed to see it - no hashes, no invite code."""
    return {
        "id": row["id"],
        "name": row["name"],
        "display_name": row["display_name"],
        "color": row["color"],
        "is_admin": bool(row["is_admin"]),
    }
