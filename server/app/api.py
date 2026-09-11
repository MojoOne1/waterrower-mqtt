"""The REST API. Everything the browser does apart from the live socket."""

import csv
import io
import logging
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import auth
import config
import records as records_mod

log = logging.getLogger("api")
router = APIRouter()

db = None
hub = None
races = None


def init(database, live_hub, race_engine) -> None:
    global db, hub, races
    db, hub, races = database, live_hub, race_engine


# --- Models ----------------------------------------------------------------

class Login(BaseModel):
    name: str
    password: str


class JoinInvite(BaseModel):
    code: str
    password: str = Field(min_length=8)
    display_name: str = ""


class NewPassword(BaseModel):
    old_password: str
    password: str = Field(min_length=8)


class NewAthlete(BaseModel):
    name: str = Field(min_length=2, max_length=32)
    display_name: str = Field(min_length=1, max_length=40)
    is_admin: bool = False


class AthletePatch(BaseModel):
    display_name: str = Field(min_length=1, max_length=40)
    color: str = ""
    is_admin: bool | None = None        # admins only; None leaves it alone


class NewToken(BaseModel):
    label: str = ""


class NewRace(BaseModel):
    name: str = ""
    mode: str = "distance"
    target: int = 2000


class Ready(BaseModel):
    ready: bool = True


class EntryRef(BaseModel):
    entry_id: int


class GhostRef(BaseModel):
    session_id: int


# --- Session and account ---------------------------------------------------

@router.get("/api/version")
def version():
    return {"version": config.APP_VERSION, "commit": config.GIT_COMMIT}


@router.get("/api/health")
def health():
    """For the container healthcheck: no auth, and it touches the database
    so a broken volume shows up as unhealthy rather than as a blank page."""
    try:
        athletes = db.count_athletes()
    except Exception as e:
        raise HTTPException(503, f"database unavailable: {e}")
    return {"ok": True, "athletes": athletes, "uplinks": len(hub.uplinks),
            "version": config.APP_VERSION}


@router.get("/api/me")
def me(request: Request):
    athlete = auth.athlete_from_cookie(request)
    if not athlete:
        raise HTTPException(401, "Not signed in")
    return auth.public_athlete(athlete)


# Three policies, all adjustable in the arena. The per-address one is the
# tight limit; the per-name one still bites when the guesses arrive from
# everywhere at once, and is loose enough that it is no way to lock a
# friend out on a whim; the invitation one is separate because a wrong code
# says nothing about who is trying it.
BY_IP = auth.Throttle(limit=10, block_s=900, label="login_ip")
BY_NAME = auth.Throttle(limit=30, block_s=900, label="login_name")
INVITE_IP = auth.Throttle(limit=10, block_s=3600, label="invite_ip")

POLICIES = {"login_ip": BY_IP, "login_name": BY_NAME, "invite_ip": INVITE_IP}


def security_settings() -> dict:
    """Defaults, with whatever an admin has saved on top."""
    values = dict(config.SECURITY_DEFAULTS)
    values.update(db.settings().get("security") or {})
    return values


def apply_security(values: dict | None = None) -> dict:
    values = values or security_settings()
    for name, throttle in POLICIES.items():
        throttle.configure(int(values[f"{name}_limit"]),
                           float(values[f"{name}_minutes"]) * 60)
    return values


@router.post("/api/login")
def login(body: Login, request: Request, response: Response):
    name = body.name.strip().lower()
    ip = auth.client_ip(request)
    wait = max(BY_IP.retry_after(ip), BY_NAME.retry_after(name))
    if wait:
        raise HTTPException(429, f"Too many attempts - try again in {int(wait / 60) + 1} min",
                            headers={"Retry-After": str(int(wait))})

    athlete = db.athlete_by_name(name)
    ok = auth.verify_password(body.password, athlete["password_hash"] if athlete else None)
    if not ok:
        BY_IP.record(ip)
        BY_NAME.record(name)
        # Same answer either way; which half was wrong is not the caller's
        # business.
        raise HTTPException(401, "Wrong name or password")
    BY_IP.clear(ip)
    BY_NAME.clear(name)
    token = auth.new_token()
    db.add_web_session(auth.token_hash(token), athlete["id"], config.SESSION_DAYS * 86400)
    auth.set_cookie(response, token)
    return auth.public_athlete(athlete)


@router.post("/api/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(auth.COOKIE)
    if token:
        db.drop_web_session(auth.token_hash(token))
    auth.clear_cookie(response)
    return {"ok": True}


def _check_invite_code(code: str, request: Request) -> dict:
    """Shared by looking an invitation up and redeeming it - both are a
    guess at a code, and both have to count towards the same lockout."""
    ip = auth.client_ip(request)
    wait = INVITE_IP.retry_after(ip)
    if wait:
        raise HTTPException(429, f"Too many attempts - try again in {int(wait / 60) + 1} min",
                            headers={"Retry-After": str(int(wait))})
    athlete = db.athlete_by_invite(code)
    if not athlete:
        INVITE_IP.record(ip)
        raise HTTPException(404, "This invitation is not valid any more")
    INVITE_IP.clear(ip)
    return athlete


@router.get("/api/invite/{code}")
def check_invite(code: str, request: Request):
    athlete = _check_invite_code(code, request)
    return {"name": athlete["name"], "display_name": athlete["display_name"]}


@router.post("/api/join")
def join_invite(body: JoinInvite, request: Request, response: Response):
    athlete = _check_invite_code(body.code, request)
    db.set_password(athlete["id"], auth.hash_password(body.password))
    if body.display_name.strip():
        db.update_athlete(athlete["id"], body.display_name.strip(), athlete["color"])
    athlete = db.athlete(athlete["id"])
    token = auth.new_token()
    db.add_web_session(auth.token_hash(token), athlete["id"], config.SESSION_DAYS * 86400)
    auth.set_cookie(response, token)
    return auth.public_athlete(athlete)


@router.post("/api/password")
def change_password(body: NewPassword, athlete: dict = Depends(auth.current_athlete)):
    if not auth.verify_password(body.old_password, athlete["password_hash"]):
        raise HTTPException(403, "Current password is wrong")
    db.set_password(athlete["id"], auth.hash_password(body.password))
    return {"ok": True}


# --- Athletes --------------------------------------------------------------

@router.get("/api/athletes")
def list_athletes(_: dict = Depends(auth.current_athlete)):
    return [auth.public_athlete(a) for a in db.list_athletes()]


@router.post("/api/athletes")
def create_athlete(body: NewAthlete, _: dict = Depends(auth.current_admin)):
    name = body.name.strip().lower()
    if db.athlete_by_name(name):
        raise HTTPException(409, "That name is taken")
    code = secrets.token_urlsafe(12)
    color = config.LANE_COLORS[db.count_athletes() % len(config.LANE_COLORS)]
    athlete_id = db.create_athlete(name, body.display_name.strip(), code, color, body.is_admin)
    return {"athlete": auth.public_athlete(db.athlete(athlete_id)), "invite_code": code}


@router.patch("/api/athletes/{athlete_id}")
def patch_athlete(athlete_id: int, body: AthletePatch,
                  athlete: dict = Depends(auth.current_athlete)):
    if athlete["id"] != athlete_id and not athlete["is_admin"]:
        raise HTTPException(403, "Not your profile")
    target = db.athlete(athlete_id)
    if not target:
        raise HTTPException(404, "No such athlete")
    color = body.color.strip() or target["color"]
    db.update_athlete(athlete_id, body.display_name.strip(), color)
    if body.is_admin is not None and bool(target["is_admin"]) != body.is_admin:
        if not athlete["is_admin"]:
            raise HTTPException(403, "Admins only")
        if not body.is_admin and db.count_admins() <= 1:
            # Losing the last admin means nobody can hand the role back.
            raise HTTPException(409, "Someone has to stay an admin")
        db.set_admin(athlete_id, body.is_admin)
        if body.is_admin:
            races.drop_athlete(athlete_id)      # admins do not sit in races
    return auth.public_athlete(db.athlete(athlete_id))


@router.post("/api/athletes/{athlete_id}/invite")
def new_invite(athlete_id: int, _: dict = Depends(auth.current_admin)):
    """Hands out a fresh code and clears the password - this is the reset."""
    if not db.athlete(athlete_id):
        raise HTTPException(404, "No such athlete")
    code = secrets.token_urlsafe(12)
    db.reset_invite(athlete_id, code)
    db.drop_web_sessions_of(athlete_id)
    return {"invite_code": code}


@router.delete("/api/athletes/{athlete_id}")
def delete_athlete(athlete_id: int, admin: dict = Depends(auth.current_admin)):
    if athlete_id == admin["id"]:
        raise HTTPException(400, "You cannot delete yourself")
    db.delete_athlete(athlete_id)
    return {"ok": True}


def _own_or_admin(athlete: dict, athlete_id: int) -> None:
    if athlete["id"] != athlete_id and not athlete["is_admin"]:
        raise HTTPException(403, "Not yours")


@router.get("/api/athletes/{athlete_id}/tokens")
def list_tokens(athlete_id: int, athlete: dict = Depends(auth.current_athlete)):
    _own_or_admin(athlete, athlete_id)
    return db.list_tokens(athlete_id)


@router.post("/api/athletes/{athlete_id}/tokens")
def create_token(athlete_id: int, body: NewToken, athlete: dict = Depends(auth.current_athlete)):
    """The only time the token itself is ever returned - it is stored hashed."""
    _own_or_admin(athlete, athlete_id)
    token = auth.new_token()
    db.add_token(athlete_id, auth.token_hash(token), body.label.strip()[:40])
    return {"token": token}


@router.delete("/api/athletes/{athlete_id}/tokens/{token_id}")
def delete_token(athlete_id: int, token_id: int, athlete: dict = Depends(auth.current_athlete)):
    _own_or_admin(athlete, athlete_id)
    db.delete_token(athlete_id, token_id)
    return {"ok": True}


# --- Sessions --------------------------------------------------------------

@router.get("/api/sessions")
def list_sessions(athlete_id: int | None = None, limit: int = 200, days: int | None = None,
                  _: dict = Depends(auth.current_athlete)):
    since = time.time() - days * 86400 if days else None
    return db.list_sessions(athlete_id, min(limit, 1000), since)


@router.get("/api/sessions/{session_id}")
def get_session(session_id: int, _: dict = Depends(auth.current_athlete)):
    session = db.session(session_id)
    if not session:
        raise HTTPException(404, "No such session")
    return {"session": session, "samples": db.samples(session_id)}


@router.delete("/api/sessions/{session_id}")
def delete_session(session_id: int, athlete: dict = Depends(auth.current_athlete)):
    session = db.session(session_id)
    if not session:
        raise HTTPException(404, "No such session")
    _own_or_admin(athlete, session["athlete_id"])
    db.delete_session(session_id)
    hub.broadcast({"type": "session_deleted", "session_id": session_id})
    return {"ok": True}


@router.get("/api/sessions/{session_id}/export.csv")
def export_csv(session_id: int, _: dict = Depends(auth.current_athlete)):
    session = db.session(session_id)
    samples = db.samples(session_id)
    if not session or not samples:
        raise HTTPException(404, "No such session")
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(samples[0].keys()))
    w.writeheader()
    w.writerows(samples)
    name = f"{session['athlete_name']}-{session['remote_id']}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# --- Live ------------------------------------------------------------------

@router.post("/api/session/end")
async def end_my_session(athlete: dict = Depends(auth.current_athlete)):
    """Close my own session on my own monitor, from wherever I am standing.

    Your session only - nobody gets to end somebody else's row. The monitor
    keeps its numbers; this is the tracker's "End session" button reachable
    from the phone propped up on the ergometer.
    """
    sent = await hub.command(athlete["id"], "end")
    if not sent:
        raise HTTPException(503, "Your tracker is not connected")
    return {"ok": True}


@router.get("/api/live")
def live(_: dict = Depends(auth.current_athlete)):
    return {
        "athletes": hub.snapshot(),
        "race": races.active().public() if races.active() else None,
    }


# --- Races -----------------------------------------------------------------

@router.get("/api/race")
def active_race(_: dict = Depends(auth.current_athlete)):
    r = races.active()
    return r.public() if r else None


@router.post("/api/race")
def create_race(body: NewRace, athlete: dict = Depends(auth.current_athlete)):
    if body.mode not in ("distance", "time", "free"):
        raise HTTPException(400, "Unknown race mode")
    target = max(0, int(body.target))
    if body.mode == "distance" and not 100 <= target <= 100000:
        raise HTTPException(400, "Distance must be between 100 m and 100 km")
    if body.mode == "time" and not 60 <= target <= 14400:
        raise HTTPException(400, "Duration must be between 1 minute and 4 hours")
    try:
        r = races.create(body.name.strip()[:60], body.mode, target, athlete)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return r.public()


@router.post("/api/race/join")
def join_race(athlete: dict = Depends(auth.current_athlete)):
    try:
        races.join(athlete)
    except ValueError as e:
        raise HTTPException(409, str(e))
    except PermissionError as e:
        raise HTTPException(403, str(e))
    return races.active().public()


@router.post("/api/race/leave")
def leave_race(body: EntryRef, athlete: dict = Depends(auth.current_athlete)):
    try:
        races.leave(athlete, body.entry_id)
    except ValueError as e:
        raise HTTPException(409, str(e))
    except PermissionError as e:
        raise HTTPException(403, str(e))
    r = races.active()
    return r.public() if r else None


@router.post("/api/race/ready")
def ready(body: Ready, athlete: dict = Depends(auth.current_athlete)):
    try:
        races.set_ready(athlete, body.ready)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return races.active().public()


@router.post("/api/race/ghost")
def add_ghost(body: GhostRef, athlete: dict = Depends(auth.current_athlete)):
    session = db.session(body.session_id)
    if not session:
        raise HTTPException(404, "No such session")
    samples = db.samples(body.session_id)
    if len(samples) < 2:
        raise HTTPException(400, "That session has too few samples to row against")
    try:
        races.add_ghost(athlete, session, samples)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return races.active().public()


@router.post("/api/race/start")
async def start_race(athlete: dict = Depends(auth.current_athlete)):
    try:
        await races.start(athlete)
    except ValueError as e:
        raise HTTPException(409, str(e))
    except PermissionError as e:
        raise HTTPException(403, str(e))
    return races.active().public()


@router.post("/api/race/finish")
async def finish_race(athlete: dict = Depends(auth.current_athlete)):
    try:
        await races.finish(reason="host", athlete=athlete)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    r = races.active()
    return r.public() if r else None


@router.post("/api/race/abort")
async def abort_race(athlete: dict = Depends(auth.current_athlete)):
    try:
        await races.abort(athlete)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    return {"ok": True}


@router.post("/api/race/clear")
def clear_race(_: dict = Depends(auth.current_athlete)):
    """Drop a finished race off the live view so the lobby is free again."""
    cleared = races.clear_if_done()
    if cleared:
        hub.broadcast({"type": "race", "race": None})
    return {"ok": True, "cleared": cleared}


@router.get("/api/races")
def list_races(limit: int = 50, _: dict = Depends(auth.current_athlete)):
    return db.list_races(min(limit, 200))


@router.get("/api/races/{race_id}")
def get_race(race_id: int, _: dict = Depends(auth.current_athlete)):
    r = db.race(race_id)
    if not r:
        raise HTTPException(404, "No such race")
    return r


@router.delete("/api/races/{race_id}")
def delete_race(race_id: int, _: dict = Depends(auth.current_admin)):
    if races.active() and races.active().id == race_id:
        raise HTTPException(409, "That race is still running")
    db.delete_race(race_id)
    return {"ok": True}


# --- Standings -------------------------------------------------------------

@router.get("/api/records")
def leaderboards(_: dict = Depends(auth.current_athlete)):
    """Best effort per athlete for each standard distance and duration."""
    rows = db.all_records()
    out = []
    for kind, keys in (("distance", config.RECORD_DISTANCES), ("time", config.RECORD_TIMES)):
        lower_is_better = kind == "distance"       # a time; metres go the other way
        for key in keys:
            best: dict[int, dict] = {}
            for r in rows:
                if r["kind"] != kind or r["key"] != key:
                    continue
                cur = best.get(r["athlete_id"])
                if cur is None or (r["value"] < cur["value"] if lower_is_better
                                   else r["value"] > cur["value"]):
                    best[r["athlete_id"]] = r
            ranked = sorted(best.values(), key=lambda r: r["value"], reverse=not lower_is_better)
            if ranked:
                out.append({"kind": kind, "key": key, "entries": ranked})
    return out


@router.get("/api/totals")
def totals(days: int | None = None, _: dict = Depends(auth.current_athlete)):
    return db.totals(time.time() - days * 86400 if days else None)


@router.get("/api/h2h")
def head_to_head(_: dict = Depends(auth.current_athlete)):
    """Who beat whom, counted across every finished race."""
    by_race: dict[int, list[dict]] = {}
    for row in db.finished_race_places():
        by_race.setdefault(row["race_id"], []).append(row)
    wins: dict[tuple[int, int], int] = {}
    for places in by_race.values():
        for a in places:
            for b in places:
                if a["athlete_id"] == b["athlete_id"]:
                    continue
                if a["place"] < b["place"]:
                    key = (a["athlete_id"], b["athlete_id"])
                    wins[key] = wins.get(key, 0) + 1
    return {
        "races": len(by_race),
        "pairs": [{"winner": a, "loser": b, "wins": n} for (a, b), n in wins.items()],
    }


# --- Security --------------------------------------------------------------

class SecurityPatch(BaseModel):
    login_ip_limit: int = Field(ge=0, le=1000)
    login_ip_minutes: int = Field(ge=1, le=10080)
    login_name_limit: int = Field(ge=0, le=1000)
    login_name_minutes: int = Field(ge=1, le=10080)
    invite_ip_limit: int = Field(ge=0, le=1000)
    invite_ip_minutes: int = Field(ge=1, le=10080)


class Unblock(BaseModel):
    policy: str = ""
    key: str = ""


def _blocked() -> list[dict]:
    return [b for throttle in POLICIES.values() for b in throttle.blocked()]


@router.get("/api/security")
def get_security(_: dict = Depends(auth.current_admin)):
    return {"settings": security_settings(), "blocked": _blocked()}


@router.post("/api/security")
def set_security(body: SecurityPatch, _: dict = Depends(auth.current_admin)):
    values = body.model_dump()
    db.save_settings({"security": values})
    apply_security(values)
    log.info("Security settings changed: %s", values)
    return {"settings": values, "blocked": _blocked()}


@router.post("/api/security/unblock")
def unblock(body: Unblock, _: dict = Depends(auth.current_admin)):
    """Let somebody back in - a locked-out friend, or yourself after a
    typo. Without a key the whole policy is cleared; without either, all
    of them."""
    if body.policy and body.policy not in POLICIES:
        raise HTTPException(404, "No such policy")
    targets = [POLICIES[body.policy]] if body.policy else list(POLICIES.values())
    for throttle in targets:
        if body.key:
            throttle.clear(body.key)
        else:
            throttle.clear_all()
    return {"blocked": _blocked()}


@router.post("/api/reindex")
def reindex(_: dict = Depends(auth.current_admin)):
    """Rescan sessions for personal bests - after an import, say."""
    n = records_mod.index_missing(db, limit=2000)
    return {"indexed": n}
