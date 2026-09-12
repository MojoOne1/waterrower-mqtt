"""WaterRower Workout Tracker - web UI and API."""

import asyncio
import csv
import io
import json
import logging
import os
import urllib.error
import urllib.request
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
log = logging.getLogger("tracker")

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
        "esphome_url": os.environ.get("ESPHOME_URL", ""),
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


def on_arena_command(cmd: str, msg: dict) -> None:
    """What the arena can ask of this tracker.

    The two session commands go out on the same topic the "End session"
    button uses. The firmware treats the payload "reset" as close-and-zero
    and anything else as close-only, which is exactly the distinction
    wanted here: zero the monitor before the gun, but at the finish just
    close the session and leave the numbers on the display to be read.

    "race" carries no instruction at all - it is the countdown and the
    rower's own standing, so the screen at the machine can show them
    without a phone propped up next to it.
    """
    if cmd == "reset":
        ingest.publish("cmd/end_session", "reset")
    elif cmd == "end":
        ingest.publish("cmd/end_session", "end")
    elif cmd == "race":
        state.set_race(msg.get("race"))


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


# --- Firmware --------------------------------------------------------------

def _shipped_yaml() -> Path:
    """The firmware YAML this build was made with.

    In the image the Dockerfile puts it at /app/firmware. Run straight from
    a checkout and it is still in esphome/ where it is edited, two levels
    up from here - so development sees the same card the container does.
    """
    env = os.environ.get("FIRMWARE_YAML")
    if env:
        return Path(env)
    packaged = Path("/app/firmware/waterrower.yaml")
    if packaged.is_file():
        return packaged
    return Path(__file__).resolve().parents[2] / "esphome" / "waterrower.yaml"


SHIPPED_YAML = _shipped_yaml()
# Where the ESPHome dashboard keeps its configs. Share the same folder with
# that container and a YAML written here shows up there immediately.
ESPHOME_DIR = Path(os.environ.get("ESPHOME_CONFIG", "/esphome"))
YAML_MAX = 512 * 1024
# The firmware YAML as it stands on the default branch. Fetched only when
# somebody asks for it by name - never in the background, never on a timer.
# This is code that ends up burned onto hardware, so it is a fixed address
# that no request can redirect: the browser picks "github", not a URL.
GITHUB_YAML_URL = os.environ.get(
    "FIRMWARE_YAML_URL",
    "https://raw.githubusercontent.com/MojoOne1/waterrower-mqtt/master/esphome/waterrower.yaml")


class EsphomeSettings(BaseModel):
    esphome_url: str = ""


class YamlInstall(BaseModel):
    source: str = "shipped"      # "shipped", or the name of a file already there
    name: str = "waterrower.yaml"
    content: str | None = None   # set when the browser hands over its own file
    overwrite: bool = False


def _safe_yaml_name(name: str) -> str:
    """A bare file name ending in .yaml, and nothing clever.

    Everything this writes lands in one directory that is shared with
    another container, so a name is allowed to be a name and nothing else:
    no separators, no walking up, no overwriting the secrets file the
    dashboard needs.
    """
    name = name.strip()
    # Refuse anything with a path in it rather than quietly writing the
    # stripped remainder: silently turning ../../x.yaml into x.yaml gives
    # back a file nobody asked for under a name nobody typed.
    if name != Path(name).name or "/" in name or chr(92) in name or ".." in name:
        raise HTTPException(400, "A plain file name, without a path")
    if not name.endswith((".yaml", ".yml")) or name.startswith("."):
        raise HTTPException(400, "A YAML file name is required")
    if name in ("secrets.yaml", "secrets.yml"):
        raise HTTPException(400, "secrets.yaml is the dashboard's own - pick another name")
    return name


def _yaml_version(text: str) -> str:
    """The `version:` out of the substitutions block, for the label."""
    for line in text.splitlines()[:40]:
        line = line.strip()
        if line.startswith("version:"):
            return line.split(":", 1)[1].strip().strip(chr(34) + chr(39))
    return ""


def _fetch_github_yaml() -> str:
    """The current YAML from the project's own repository.

    Deliberately strict about what comes back: HTTPS only, a size cap, and
    it has to look like an ESPHome configuration. A redirect to a login
    page or a 404 body is not something to write into the folder another
    container compiles from.
    """
    if not GITHUB_YAML_URL.startswith("https://"):
        raise HTTPException(400, "The firmware URL must be https")
    try:
        with urllib.request.urlopen(GITHUB_YAML_URL, timeout=15) as r:
            raw = r.read(YAML_MAX + 1)
    except Exception as e:
        raise HTTPException(502, f"GitHub did not answer: {type(e).__name__}")
    if len(raw) > YAML_MAX:
        raise HTTPException(502, "What came back is too large for a configuration")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(502, "What came back is not text")
    if "esphome:" not in text or "substitutions:" not in text:
        raise HTTPException(502, "What came back is not an ESPHome configuration")
    return text


def _yaml_choices() -> list[dict]:
    """What there is to install: the shipped one, plus whatever is there."""
    out = []
    if SHIPPED_YAML.is_file():
        out.append({"source": "shipped", "name": SHIPPED_YAML.name,
                    "version": APP_VERSION, "kind": "shipped"})
    # Listed without being fetched: the label promises nothing about the
    # version because finding that out would mean a request per page load.
    out.append({"source": "github", "name": "waterrower.yaml",
                "version": "", "kind": "github"})
    if ESPHOME_DIR.is_dir():
        for f in sorted(ESPHOME_DIR.glob("*.y*ml")):
            if f.name in ("secrets.yaml", "secrets.yml") or not f.is_file():
                continue
            try:
                version = _yaml_version(f.read_text(encoding="utf-8", errors="replace")[:4096])
            except OSError:
                version = ""
            out.append({"source": f.name, "name": f.name,
                        "version": version, "kind": "local"})
    return out


@app.get("/api/firmware")
def firmware():
    """What the ESP is running, and where to go to change it.

    The tracker does not compile or flash anything itself - that needs
    PlatformIO and a toolchain, and this container's job is to never stop
    recording. The ESPHome dashboard does the whole job already and is
    maintained by the people who wrote the firmware format, so this points
    at it and gets out of the way.

    "reachable" is from in here, not from your browser: the dashboard is
    usually published on the host, and a browser on the LAN may well get
    there when this container cannot. The link is shown either way.
    """
    url = (load_settings().get("esphome_url") or "").strip().rstrip("/")
    reachable = None
    if url:
        try:
            # urllib, not a new dependency: one HEAD-ish GET with a short
            # timeout is not worth putting another package in the image.
            with urllib.request.urlopen(url, timeout=2) as r:
                reachable = r.status < 500
        except urllib.error.HTTPError as e:
            reachable = e.code < 500       # it answered, so it is there
        except Exception:
            reachable = False
    return {
        "running": state.values.get("firmware_version") or "",
        "expected": APP_VERSION,
        "url": url,
        "reachable": reachable,
        "configs": _yaml_choices(),
        "config_dir": str(ESPHOME_DIR),
        "config_dir_ok": ESPHOME_DIR.is_dir() and os.access(ESPHOME_DIR, os.W_OK),
    }


@app.post("/api/firmware")
def set_firmware(new: EsphomeSettings):
    save_settings({"esphome_url": new.esphome_url.strip().rstrip("/")})
    return firmware()


@app.get("/api/firmware/yaml")
def get_yaml(source: str = "shipped"):
    """Hand the YAML over as a download, for when there is no shared folder."""
    if source == "github":
        body, name = _fetch_github_yaml(), "waterrower.yaml"
    else:
        path = SHIPPED_YAML if source == "shipped" else ESPHOME_DIR / _safe_yaml_name(source)
        if not path.is_file():
            raise HTTPException(404, "No such configuration")
        body, name = path.read_text(encoding="utf-8"), path.name
    return Response(body, media_type="application/yaml",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/api/firmware/yaml")
def install_yaml(req: YamlInstall):
    """Put a YAML where the ESPHome dashboard will find it.

    Either the one shipped with this release, one already in the folder
    under a new name, or one the browser read off disk and sent along.
    Nothing is flashed here - the dashboard does that, and does it well.
    """
    if not ESPHOME_DIR.is_dir():
        raise HTTPException(409, f"{ESPHOME_DIR} is not mounted - share it with the ESPHome container")
    name = _safe_yaml_name(req.name)
    target = ESPHOME_DIR / name

    if req.content is not None:
        if len(req.content.encode("utf-8")) > YAML_MAX:
            raise HTTPException(413, "That file is too large for a configuration")
        body = req.content
    elif req.source == "github":
        body = _fetch_github_yaml()
    elif req.source == "shipped":
        if not SHIPPED_YAML.is_file():
            raise HTTPException(404, "This image ships no firmware YAML")
        body = SHIPPED_YAML.read_text(encoding="utf-8")
    else:
        src = ESPHOME_DIR / _safe_yaml_name(req.source)
        if not src.is_file():
            raise HTTPException(404, "No such configuration")
        body = src.read_text(encoding="utf-8")

    if target.exists() and not req.overwrite:
        raise HTTPException(409, f"{name} is already there")
    try:
        target.write_text(body, encoding="utf-8")
    except OSError as e:
        raise HTTPException(500, f"Could not write it: {e}")
    log.info("Firmware YAML written: %s (from %s)", target, req.source)
    out = firmware()
    out["wrote"] = {"name": name, "version": _yaml_version(body[:4096])}
    return out


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
    """Asks the ESP to close the running session; the ESP answers via
    session/last. The monitor keeps its numbers, which is what you want
    while rowing the piece out - use /api/session/reset to clear them."""
    if not state.connected:
        raise HTTPException(503, "Not connected to the broker")
    ingest.publish("cmd/end_session", "end")
    return {"ok": True}


@app.post("/api/session/reset")
def reset_monitor():
    """Close the session and zero the monitor. The firmware reads the
    payload "reset" as close-and-zero and anything else as close-only."""
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
