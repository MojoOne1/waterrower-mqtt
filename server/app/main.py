"""WaterRower Arena - shared training log and live racing for a few friends.

One server, one SQLite file, one WebSocket per tracker. The trackers push
what they already record; this serves the comparison and runs the races.
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

import achievements
import api
import auth
import config
import ingest
import records
from db import Database
from hub import Hub, Viewer
from race import RaceEngine

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("arena")

STATIC = Path(__file__).parent / "static"

db = Database(config.DB_PATH)
hub = Hub(db)
races = RaceEngine(db, hub)
hub.races = races
auth.db = db
api.init(db, hub, races)


def bootstrap() -> None:
    """First start: create the admin so there is a way in at all.

    And, with ARENA_ADMIN_RESET=1, the way back in when that password is
    lost - the account keeps its history, only the password and the open
    browser sessions go.
    """
    existing = db.athlete_by_name(config.ADMIN_USER)
    if existing:
        if config.ADMIN_RESET and config.ADMIN_PASSWORD:
            db.set_password(existing["id"], auth.hash_password(config.ADMIN_PASSWORD))
            db.drop_web_sessions_of(existing["id"])
            if not existing["is_admin"]:
                db.set_admin(existing["id"], True)
            log.warning("ARENA_ADMIN_RESET: reset the password of %r and signed "
                        "it out everywhere. Remove the variable again, or every "
                        "restart puts this password back.", config.ADMIN_USER)
        elif config.ADMIN_RESET:
            log.warning("ARENA_ADMIN_RESET is set but ARENA_ADMIN_PASSWORD is "
                        "empty - nothing to reset to.")
        return
    if not config.ADMIN_PASSWORD:
        if db.count_athletes() == 0:
            log.warning("No athletes and no ARENA_ADMIN_PASSWORD set - "
                        "nobody can sign in. Set it and restart.")
        return
    weak = auth.password_problem(config.ADMIN_PASSWORD)
    if weak:
        log.warning("ARENA_ADMIN_PASSWORD is weak: %s. Creating the account "
                    "anyway - change it in the arena.", weak.lower())
    athlete_id = db.create_athlete(config.ADMIN_USER, config.ADMIN_NAME, None,
                                   config.LANE_COLORS[0], is_admin=True)
    db.set_password(athlete_id, auth.hash_password(config.ADMIN_PASSWORD))
    log.info("Created admin %r", config.ADMIN_USER)


DEFAULT_TEMPLATES = [
    ("2000 m", "distance", 2000, "Die klassische Renndistanz."),
    ("500 m Sprint", "distance", 500, "Kurz und alles rein."),
    ("5000 m", "distance", 5000, "Lange Distanz, gleichmäßig fahren."),
    ("20 Minuten", "time", 1200, "Wer kommt in zwanzig Minuten am weitesten?"),
    ("Frei rudern", "free", 0, "Zusammen rudern, ohne Wertung."),
]


def seed_templates() -> None:
    """Only on an empty table: an admin who deletes them all means it."""
    if db.count_templates():
        return
    for name, mode, target, note in DEFAULT_TEMPLATES:
        db.add_template(name, mode, target, note)
    log.info("Seeded %d race templates", len(DEFAULT_TEMPLATES))


@asynccontextmanager
async def lifespan(app: FastAPI):
    bootstrap()
    seed_templates()
    achievements.seed(db)
    # History predating the badges still counts; so does a badge added
    # later, which is caught up again when it is created.
    await asyncio.to_thread(achievements.catch_up, db)
    log.info("Security: %s", api.apply_security())
    dropped = db.prune_failures(time.time() - api.FAILURE_KEEP_S)
    if dropped:
        log.info("Pruned %d old sign-in failure(s)", dropped)
    # A race cannot survive a restart: its lanes live in memory, and the
    # sample stream it was built on is gone.
    for r in db.list_races(limit=20):
        if r["state"] in ("lobby", "countdown", "running"):
            db.set_race_state(r["id"], "aborted")
            log.info("Race %s was still open at startup - marked aborted", r["id"])
    await asyncio.to_thread(records.index_missing, db)
    task = asyncio.create_task(hub.run())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="WaterRower Arena", version=config.APP_VERSION, lifespan=lifespan)

# Everything the page needs it serves itself, so the policy can say "self"
# and nothing else. That is the second lock on cross-site scripting: even
# if a value slipped into the page as markup, an injected script has no
# origin it is allowed to load from and no inline execution. frame-ancestors
# keeps the arena out of somebody else's iframe.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; "
       "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
       "form-action 'self'; base-uri 'none'; frame-ancestors 'none'; "
       "object-src 'none'")

MAX_BODY = 1 << 20      # 1 MiB; nothing the API takes comes near it


@app.middleware("http")
async def guard(request, call_next):
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_BODY:
        return JSONResponse({"detail": "Request too large"}, status_code=413)
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if config.SECURE_COOKIES:
        # Only when TLS is actually in front, or a plain-HTTP test install
        # would lock itself out of its own browser for a year.
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


app.include_router(api.router)


# --- WebSockets ------------------------------------------------------------

@app.websocket("/ws/uplink")
async def ws_uplink(websocket: WebSocket):
    await ingest.uplink_endpoint(websocket, db, hub)


@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    """The browsers' feed: live tiles, race ticks, new sessions."""
    token = websocket.cookies.get(auth.COOKIE)
    athlete = db.web_session_owner(auth.token_hash(token)) if token else None
    if not athlete:
        await websocket.close(code=4401, reason="not signed in")
        return

    await websocket.accept()
    viewer = Viewer(athlete["id"])
    hub.add_viewer(viewer)
    try:
        await websocket.send_json({
            "type": "hello",
            "athletes": hub.snapshot(),
            "race": races.active().public() if races.active() else None,
        })
        sender = asyncio.create_task(_pump(websocket, viewer))
        reader = asyncio.create_task(_drain(websocket))
        done, pending = await asyncio.wait({sender, reader},
                                          return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
    except WebSocketDisconnect:
        pass
    finally:
        hub.remove_viewer(viewer)


async def _pump(websocket: WebSocket, viewer: Viewer) -> None:
    while True:
        try:
            msg = await asyncio.wait_for(viewer.queue.get(), timeout=20)
        except asyncio.TimeoutError:
            msg = {"type": "ping"}      # keeps the tunnel from timing out
        await websocket.send_json(msg)


async def _drain(websocket: WebSocket) -> None:
    """Nothing useful comes up this socket, but reading it is how a closed
    connection is noticed - which is the normal end, not an error. Letting
    the disconnect escape put a stack trace in the log on every page the
    browser navigated away from."""
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        return


# --- UI --------------------------------------------------------------------

ASSET_TAG = f"{config.APP_VERSION}-{config.GIT_COMMIT}"
ASSETS = ["style.css", "app.js", "views.js", "charts.js", "race.js", "badges.js"]


@app.get("/")
def index():
    """Uncached shell with a per-release query on its assets, so a new
    index.html never runs last release's scripts."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for asset in ASSETS:
        html = html.replace(f"/static/{asset}", f"/static/{asset}?v={ASSET_TAG}")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache, must-revalidate"})


from fastapi.staticfiles import StaticFiles  # noqa: E402  (mounted last, on purpose)

app.mount("/static", StaticFiles(directory=STATIC), name="static")
