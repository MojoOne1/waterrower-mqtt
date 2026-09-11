"""Passwords, cookies and the FastAPI dependencies that guard the API.

Three athletes do not justify an identity provider, but they do justify not
storing passwords in the clear: scrypt is in the standard library, so the
whole thing costs one import and no dependency.
"""

import hashlib
import hmac
import secrets
import time

from fastapi import Depends, HTTPException, Request

import config

COOKIE = "arena_session"
_SCRYPT = dict(n=2 ** 14, r=8, p=1, dklen=32)


class Throttle:
    """A sliding window of failures, to slow password guessing down.

    scrypt already costs about a tenth of a second per attempt, which caps
    guessing at a few per second - but a few per second, left running for a
    week, is still a lot of guesses. In memory is enough here: one process,
    and a restart that forgets the counters is not the attack to worry about.
    """

    def __init__(self, limit: int, window_s: float):
        self.limit = limit
        self.window = window_s
        self._hits: dict[str, list[float]] = {}

    def retry_after(self, key: str) -> float:
        """Seconds the caller has to wait; 0 when they may try."""
        now = time.time()
        hits = [t for t in self._hits.get(key, ()) if now - t < self.window]
        if hits:
            self._hits[key] = hits
        else:
            self._hits.pop(key, None)
        if len(hits) < self.limit:
            return 0.0
        return round(self.window - (now - hits[0]), 1)

    def record(self, key: str) -> None:
        now = time.time()
        self._hits.setdefault(key, []).append(now)
        if len(self._hits) > 1000:
            # Somebody is rotating keys at us; drop whatever has aged out
            # rather than growing for ever.
            for k in [k for k, v in self._hits.items()
                      if not v or now - v[-1] > self.window]:
                self._hits.pop(k, None)

    def clear(self, key: str) -> None:
        self._hits.pop(key, None)


def client_ip(request: Request) -> str:
    """Behind the tunnel uvicorn has already resolved X-Forwarded-For."""
    return request.client.host if request.client else "?"


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
