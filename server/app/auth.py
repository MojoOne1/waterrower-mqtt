"""Passwords, cookies and the FastAPI dependencies that guard the API.

Three athletes do not justify an identity provider, but they do justify not
storing passwords in the clear: scrypt is in the standard library, so the
whole thing costs one import and no dependency.
"""

import hashlib
import hmac
import secrets
import threading
import time

from fastapi import Depends, HTTPException, Request

import config

COOKIE = "arena_session"


class Throttle:
    """Count failures, then lock out for a while.

    `limit` failures within `block_s` seconds of each other lock the key
    until `block_s` after the last one. The same number answers both "how
    long is an attempt remembered" and "how long is the lockout", which
    keeps it to the two knobs worth putting in front of somebody. A limit
    of 0 turns the policy off.

    scrypt already costs about a tenth of a second per attempt, which caps
    guessing at a few per second - but a few per second, left running for a
    week, is still a lot of guesses. In memory is enough here: one process,
    and a restart that forgets the counters is not the attack to worry
    about.
    """

    def __init__(self, limit: int, block_s: float, label: str = ""):
        self.limit = limit
        self.block_s = block_s
        self.label = label
        self._hits: dict[str, list[float]] = {}

    def configure(self, limit: int, block_s: float) -> None:
        self.limit = int(limit)
        self.block_s = float(block_s)

    def _recent(self, key: str, now: float) -> list[float]:
        hits = [t for t in self._hits.get(key, ()) if now - t < self.block_s]
        if hits:
            self._hits[key] = hits
        else:
            self._hits.pop(key, None)
        return hits

    def retry_after(self, key: str) -> float:
        """Seconds the caller has to wait; 0 when they may try."""
        if self.limit <= 0:
            return 0.0
        now = time.time()
        hits = self._recent(key, now)
        if len(hits) < self.limit:
            return 0.0
        return round(max(0.0, hits[-1] + self.block_s - now), 1)

    def record(self, key: str) -> None:
        if self.limit <= 0:
            return
        now = time.time()
        self._hits.setdefault(key, []).append(now)
        if len(self._hits) > 1000:
            # Somebody is rotating keys at us; drop whatever has aged out
            # rather than growing for ever.
            for k in [k for k, v in self._hits.items()
                      if not v or now - v[-1] > self.block_s]:
                self._hits.pop(k, None)

    def clear(self, key: str) -> None:
        self._hits.pop(key, None)

    def clear_all(self) -> None:
        self._hits.clear()

    def attempts(self, key: str) -> int:
        return len(self._recent(key, time.time()))

    def blocked(self) -> list[dict]:
        """What is locked out right now, for the admin panel."""
        out = []
        for key in list(self._hits):
            wait = self.retry_after(key)
            if wait > 0:
                out.append({"policy": self.label, "key": key, "seconds": wait})
        return out


MIN_PASSWORD = 12


def password_problem(password: str) -> str | None:
    """None when the password passes, otherwise why it does not.

    Twelve characters and three of the four kinds. Worth knowing what this
    costs: a long passphrase in one case - "correct horse battery staple" -
    is refused at twenty-eight characters while "Passwort123!" is accepted
    at twelve, though the passphrase is far harder to guess. Composition
    rules always trade that away. Three kinds rather than four at least
    leaves room for a passphrase that has a capital and a number in it.
    """
    if len(password) < MIN_PASSWORD:
        return f"The password needs at least {MIN_PASSWORD} characters"
    kinds = sum((
        any(c.islower() for c in password),
        any(c.isupper() for c in password),
        any(c.isdigit() for c in password),
        any(not c.isalnum() for c in password),
    ))
    if kinds < 3:
        return ("The password needs three of: lower case, upper case, "
                "digits, anything else")
    return None


# The lockout policies, here rather than in the API so the uplink endpoint
# can reach them without importing it. Limits come from the database at
# startup; these are placeholders.
BY_IP = Throttle(limit=10, block_s=900, label="login_ip")
BY_NAME = Throttle(limit=30, block_s=900, label="login_name")
INVITE_IP = Throttle(limit=10, block_s=3600, label="invite_ip")
UPLINK_IP = Throttle(limit=10, block_s=900, label="uplink_ip")

POLICIES = {"login_ip": BY_IP, "login_name": BY_NAME,
            "invite_ip": INVITE_IP, "uplink_ip": UPLINK_IP}


def client_ip(request: Request) -> str:
    """Behind the tunnel uvicorn has already resolved X-Forwarded-For."""
    return request.client.host if request.client else "?"


# OWASP's floor for scrypt is n=2**17; that is 128 MiB *per verification*,
# and FastAPI runs sync endpoints in a forty-wide thread pool, so a burst of
# sign-ins would take the container out. n=2**16 with at most two hashes at
# a time caps it at 128 MiB whatever arrives, and the lockout policy handles
# the rest. Raising these later is now possible because the parameters are
# written into the hash: verification uses whatever a hash was made with,
# and a password is re-hashed with the current ones on the next sign-in.
_SCRYPT = {"n": 2 ** 16, "r": 8, "p": 1}
_DKLEN = 32
_HASH_SLOTS = threading.Semaphore(2)


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> str:
    # maxmem has to be given: OpenSSL's default ceiling is 32 MiB and these
    # parameters need four times that.
    need = 128 * n * r + (1 << 20)
    with _HASH_SLOTS:
        return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p,
                              dklen=_DKLEN, maxmem=need).hex()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = _scrypt(password, salt, **_SCRYPT)
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${salt.hex()}${dk}"


def _parse(stored: str) -> tuple[int, int, int, bytes, str] | None:
    parts = stored.split("$")
    if len(parts) == 6 and parts[0] == "scrypt":
        try:
            return (int(parts[1]), int(parts[2]), int(parts[3]),
                    bytes.fromhex(parts[4]), parts[5])
        except ValueError:
            return None
    # The first release wrote scrypt$salt$hash with the parameters implied.
    if len(parts) == 3 and parts[0] == "scrypt":
        try:
            return 2 ** 14, 8, 1, bytes.fromhex(parts[1]), parts[2]
        except ValueError:
            return None
    return None


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    parsed = _parse(stored)
    if not parsed:
        return False
    n, r, p, salt, expected = parsed
    return hmac.compare_digest(_scrypt(password, salt, n, r, p), expected)


def needs_rehash(stored: str | None) -> bool:
    """True when a stored hash was made with weaker parameters than today's."""
    parsed = _parse(stored) if stored else None
    if not parsed:
        return False
    n, r, p, _, _ = parsed
    return (n, r, p) != (_SCRYPT["n"], _SCRYPT["r"], _SCRYPT["p"])


# Verifying against this costs the same as verifying against a real hash, so
# a sign-in for an account that does not exist takes as long as one that
# does. Without it the response time says which names are real.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def verify_or_waste_time(password: str, stored: str | None) -> bool:
    if stored:
        return verify_password(password, stored)
    verify_password(password, _DUMMY_HASH)
    return False


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
