"""WaterRower Arena - shared training log and live racing for a few friends.

One server, one SQLite file, one WebSocket per tracker. The trackers push
what they already record; this serves the comparison and runs the races.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

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
    """First start: create the admin so there is a way in at all."""
    existing = db.athlete_by_name(config.ADMIN_USER)
    if existing:
        return
    if not config.ADMIN_PASSWORD:
        if db.count_athletes() == 0:
            log.warning("No athletes and no ARENA_ADMIN_PASSWORD set - "
                        "nobody can sign in. Set it and restart.")
        return
    athlete_id = db.create_athlete(config.ADMIN_USER, config.ADMIN_NAME, None,
                                   config.LANE_COLORS[0], is_admin=True)
    db.set_password(athlete_id, auth.hash_password(config.ADMIN_PASSWORD))
    log.info("Created admin %r", config.ADMIN_USER)


@asynccontextmanager
async def lifespan(app: FastAPI):
    bootstrap()
    log.info("Security: %s", api.apply_security())
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
    connection is noticed."""
    while True:
        await websocket.receive_text()


# --- UI --------------------------------------------------------------------

ASSET_TAG = f"{config.APP_VERSION}-{config.GIT_COMMIT}"
ASSETS = ["style.css", "app.js", "views.js", "charts.js", "race.js"]


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
