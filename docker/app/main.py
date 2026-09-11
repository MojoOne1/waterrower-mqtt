"""WaterRower Tracker - web UI and API."""

import asyncio
import csv
import io
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from db import Database
from mqtt_ingest import LiveState, MqttIngest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

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
    }
    if SETTINGS_PATH.exists():
        try:
            s.update(json.loads(SETTINGS_PATH.read_text()))
        except (OSError, json.JSONDecodeError):
            pass
    return s


def save_settings(s: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(s, indent=2))


db = Database(DB_PATH)
state = LiveState()
ingest = MqttIngest(db, state, load_settings())


@asynccontextmanager
async def lifespan(_: FastAPI):
    ingest.start()
    yield
    ingest.stop()


app = FastAPI(title="WaterRower Tracker", lifespan=lifespan)


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
    save_settings(s)
    ingest.configure(s)
    ingest.start()
    return {"ok": True}


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


# --- UI --------------------------------------------------------------------

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
