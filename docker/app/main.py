"""WaterRower Workout Tracker - web UI and API."""

import asyncio
import csv
import io
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import xlsx_export
from db import Database
from mqtt_ingest import LiveState, MqttIngest
from uplink import Uplink

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

APP_VERSION = os.environ.get("APP_VERSION", "dev")
GIT_COMMIT = os.environ.get("GIT_COMMIT", "unknown")
DB_PATH = os.environ.get("DB_PATH", "/data/waterrower.db")
SETTINGS_PATH = Path(DB_PATH).parent / "settings.json"
STATIC = Path(__file__).parent / "static"


def load_settings() -> dict:
    """Saved settings; environment variables serve as defaults."""
    s = {
        "host": os.environ.get("MQTT_HOST", ""),
        "port": int(os.environ.get("MQTT_PORT", "1883")),
        "username": os.environ.get("MQTT_USERNAME", ""),
        "password": os.environ.get("MQTT_PASSWORD", ""),
        "prefix": os.environ.get("MQTT_PREFIX", "waterrower"),
        "arena_url": os.environ.get("ARENA_URL", ""),
        "arena_token": os.environ.get("ARENA_TOKEN", ""),
        "arena_enabled": os.environ.get("ARENA_URL", "") != "",
    }
    if SETTINGS_PATH.exists():
        try:
            s.update(json.loads(SETTINGS_PATH.read_text()))
        except (OSError, json.JSONDecodeError):
            pass
    return s


def save_settings(changed: dict) -> dict:
    """Merge into what is on disk: the broker form and the arena form each
    write only their own keys, and neither may erase the other's."""
    s = load_settings()
    s.update(changed)
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(s, indent=2))
    return s


db = Database(DB_PATH)
state = LiveState()


def on_arena_command(cmd: str, _msg: dict) -> None:
    """Both of these go out on the same topic the "End session" button uses.

    The firmware treats the payload "reset" as close-and-zero and anything
    else as close-only, which is exactly the distinction wanted here: zero
    the monitor before the gun, but at the finish just close the session
    and leave the numbers on the display to be read.
    """
    if cmd == "reset":
        ingest.publish("cmd/end_session", "reset")
    elif cmd == "end":
        ingest.publish("cmd/end_session", "end")


link = Uplink(db, load_settings(), on_command=on_arena_command)
ingest = MqttIngest(db, state, load_settings(), uplink=link)


@asynccontextmanager
async def lifespan(_: FastAPI):
    ingest.start()
    link.start(version=APP_VERSION)
    yield
    link.stop()
    ingest.stop()


app = FastAPI(title="WaterRower Workout Tracker", version=APP_VERSION, lifespan=lifespan)


@app.get("/api/version")
def version():
    return {"version": APP_VERSION, "commit": GIT_COMMIT}


# --- Settings --------------------------------------------------------------

class Settings(BaseModel):
    host: str
    port: int = 1883
    username: str = ""
    password: str = ""
    prefix: str = "waterrower"


@app.get("/api/settings")
def get_settings():
    s = dict(ingest.settings)
    s["password"] = "••••••" if s.get("password") else ""
    s["connected"] = state.connected
    s["error"] = ingest.last_error
    return s


@app.post("/api/settings")
def set_settings(new: Settings):
    s = new.model_dump()
    s["host"] = s["host"].strip()
    s["prefix"] = s["prefix"].strip().strip("/") or "waterrower"
    if s["password"] == "••••••":              # left unchanged in the form
        s["password"] = ingest.settings.get("password", "")
    if not s["host"]:
        raise HTTPException(400, "Broker address missing")
    merged = save_settings(s)
    ingest.configure(merged)
    ingest.start()
    return {"ok": True}


# --- Arena -----------------------------------------------------------------

class ArenaSettings(BaseModel):
    arena_url: str = ""
    arena_token: str = ""
    arena_enabled: bool = False


@app.get("/api/arena")
def get_arena():
    return link.status()


@app.post("/api/arena")
def set_arena(new: ArenaSettings):
    s = new.model_dump()
    s["arena_url"] = s["arena_url"].strip().rstrip("/")
    s["arena_token"] = s["arena_token"].strip()
    if s["arena_token"] == "••••••":           # left unchanged in the form
        s["arena_token"] = load_settings().get("arena_token", "")
    if s["arena_enabled"] and not (s["arena_url"] and s["arena_token"]):
        raise HTTPException(400, "Arena needs both an address and a token")
    link.configure(save_settings(s))
    return link.status()


# --- Live ------------------------------------------------------------------

@app.get("/api/live")
def live():
    return state.snapshot()


@app.get("/api/stream")
async def stream():
    """Server-Sent Events: every MQTT update reaches the browser immediately."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    loop = asyncio.get_running_loop()

    def enqueue(snap):
        # Slow consumer: drop the oldest snapshot, the newest is what matters.
        if queue.full():
            queue.get_nowait()
        queue.put_nowait(snap)

    def push(snap):
        loop.call_soon_threadsafe(enqueue, snap)

    state.subscribe(push)

    async def gen():
        try:
            yield f"data: {json.dumps(state.snapshot())}\n\n"
            while True:
                try:
                    snap = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {json.dumps(snap)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            state.unsubscribe(push)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


@app.post("/api/session/end")
def end_session():
    """Asks the ESP to close the running session and reset the monitor;
    the ESP answers via session/last."""
    if not state.connected:
        raise HTTPException(503, "Not connected to the broker")
    ingest.publish("cmd/end_session", "reset")
    return {"ok": True}


# --- Sessions --------------------------------------------------------------

@app.get("/api/sessions")
def sessions():
    return db.list_sessions()


@app.get("/api/sessions/{session_id}")
def session(session_id: str):
    data = db.get_session(session_id)
    if not data:
        raise HTTPException(404, "Session not found")
    return data


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    db.delete_session(session_id)
    return {"ok": True}


@app.get("/api/sessions/{session_id}/export.csv")
def export_csv(session_id: str):
    samples = db.get_samples(session_id)
    if not samples:
        raise HTTPException(404, "Session not found")
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=samples[0].keys())
    w.writeheader()
    w.writerows(samples)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{session_id}.csv"'},
    )


def _xlsx(content: bytes, filename: str) -> Response:
    return Response(
        content=content, media_type=xlsx_export.MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/sessions/{session_id}/export.xlsx")
def export_session_xlsx(session_id: str):
    """One workbook: summary, all samples, and a chart."""
    data = db.get_session(session_id)
    if not data:
        raise HTTPException(404, "Session not found")
    content = xlsx_export.build_session(data["session"], data["samples"])
    return _xlsx(content, f"waterrower-{session_id}.xlsx")


@app.get("/api/export.xlsx")
def export_all_xlsx():
    """One row per session, with totals and a distance chart."""
    sessions = db.list_sessions()
    if not sessions:
        raise HTTPException(404, "No sessions recorded yet")
    content = xlsx_export.build_overview(sessions)
    return _xlsx(content, "waterrower-sessions.xlsx")


# --- UI --------------------------------------------------------------------

ASSET_TAG = f"{APP_VERSION}-{GIT_COMMIT}"


@app.get("/")
def index():
    """Serve index.html uncached, with a per-release query on its assets.

    Without this a browser can end up with a new index.html and a cached
    app.js from the previous release, which silently breaks whatever the
    new markup expects the script to wire up.
    """
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for asset in ("style.css", "app.js"):
        html = html.replace(f"/static/{asset}", f"/static/{asset}?v={ASSET_TAG}")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache, must-revalidate"})


app.mount("/static", StaticFiles(directory=STATIC), name="static")
