"""Uplink to a WaterRower Arena server.

The tracker keeps doing exactly what it did - subscribe to MQTT, write
every sample to its own database - and additionally pushes the same values
to a shared server over one outbound WebSocket. Outbound is the point: the
machine at home needs no port forwarding, no certificate and no fixed
address, which is also why this survives sitting behind a Cloudflare
Tunnel on the other end.

It runs in its own thread with its own event loop. The MQTT client calls
`sample()` and `summary()` from the paho thread; those hand the message
over to the loop and return immediately, so a slow or dead uplink can
never stall the recording.

If the connection was down for a while, the server says on connect which
sessions it already has, and everything else that has finished is sent
after it - so a weekend with the internet out costs nothing but a delay.
"""

import asyncio
import json
import logging
import threading
import time

import websockets

log = logging.getLogger("uplink")

AGENT = "waterrower-tracker"
QUEUE_MAX = 600            # ~10 minutes of samples before the oldest go
BACKFILL_MAX_SAMPLES = 20000
RETRY_MIN, RETRY_MAX = 3, 60


class Uplink:
    def __init__(self, db, settings: dict, on_command=None):
        self.db = db
        self.on_command = on_command
        self.settings = {"url": "", "token": "", "enabled": False}
        self.connected = False
        self.last_error = ""
        self.athlete = ""
        self.last_sent = 0.0
        self._loop = None
        self._queue = None
        self._thread = None
        self._stop = threading.Event()
        self._version = ""
        self.configure(settings)

    # --- Lifecycle --------------------------------------------------------

    def configure(self, settings: dict) -> None:
        self.settings = {
            "url": (settings.get("arena_url") or "").strip().rstrip("/"),
            "token": (settings.get("arena_token") or "").strip(),
            "enabled": bool(settings.get("arena_enabled")),
        }
        self.last_error = ""
        if self._loop:
            # Drop the current connection; the run loop reconnects with the
            # new settings on its next turn.
            self._loop.call_soon_threadsafe(self._queue.put_nowait, {"type": "__reconnect__"})

    def start(self, version: str = "") -> None:
        self._version = version
        if self._thread:
            return
        self._thread = threading.Thread(target=self._thread_main, name="uplink", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._loop:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, {"type": "__stop__"})

    def status(self) -> dict:
        return {
            "url": self.settings["url"],
            "enabled": self.settings["enabled"],
            "token_set": bool(self.settings["token"]),
            "connected": self.connected,
            "athlete": self.athlete,
            "error": self.last_error,
            "last_sent": self.last_sent,
        }

    # --- Called from the MQTT thread --------------------------------------

    def sample(self, session_id: str, started_at: float, data: dict) -> None:
        self._push({
            "type": "sample",
            "session": session_id,
            "started_at": started_at,
            "t": int(data.get("duration_s") or 0),
            "distance_m": data.get("distance_m"),
            "speed_ms": data.get("speed_ms"),
            "stroke_rate": data.get("stroke_rate"),
            "strokes": data.get("strokes"),
            "watts": data.get("watts"),
        })

    def summary(self, session_id: str, started_at: float, data: dict) -> None:
        self._push({"type": "summary", "session": session_id,
                    "started_at": started_at, **data})

    def _push(self, msg: dict) -> None:
        if not (self.settings["enabled"] and self.settings["url"] and self.settings["token"]):
            return
        loop, queue = self._loop, self._queue
        if loop is None or queue is None:
            return
        try:
            loop.call_soon_threadsafe(self._enqueue, msg)
        except RuntimeError:
            pass                       # loop shutting down

    def _enqueue(self, msg: dict) -> None:
        if self._queue.full():
            try:
                self._queue.get_nowait()    # live data: the newest matters
            except asyncio.QueueEmpty:
                pass
        self._queue.put_nowait(msg)

    # --- The loop ---------------------------------------------------------

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._queue = asyncio.Queue(maxsize=QUEUE_MAX)
        try:
            loop.run_until_complete(self._run())
        finally:
            loop.close()

    async def _run(self) -> None:
        delay = RETRY_MIN
        while not self._stop.is_set():
            if not (self.settings["enabled"] and self.settings["url"] and self.settings["token"]):
                await asyncio.sleep(2)
                continue
            try:
                await self._session()
                # A clean return means the far end closed. Reconnect, but
                # never in a tight loop.
                delay = RETRY_MIN
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.connected = False
                self.last_error = f"{type(e).__name__}: {e}"[:200]
                log.info("Uplink: %s - retrying in %ds", self.last_error, delay)
                await asyncio.sleep(delay)
                delay = min(RETRY_MAX, delay * 2)

    def _ws_url(self) -> str:
        url = self.settings["url"]
        if url.startswith("https://"):
            url = "wss://" + url[8:]
        elif url.startswith("http://"):
            url = "ws://" + url[7:]
        elif not url.startswith(("ws://", "wss://")):
            url = "wss://" + url
        return url + "/ws/uplink"

    async def _session(self) -> None:
        url = self._ws_url()
        log.info("Uplink connecting to %s", url)
        async with websockets.connect(url, open_timeout=15, close_timeout=5,
                                      ping_interval=20, ping_timeout=20,
                                      max_queue=64) as ws:
            await ws.send(json.dumps({
                "type": "hello",
                "token": self.settings["token"],
                "agent": f"{AGENT}/{self._version or 'dev'}",
            }))
            welcome = json.loads(await asyncio.wait_for(ws.recv(), timeout=20))
            if welcome.get("type") != "welcome":
                raise RuntimeError(welcome.get("reason") or "rejected")
            self.connected = True
            self.last_error = ""
            self.athlete = (welcome.get("athlete") or {}).get("display_name", "")
            log.info("Uplink up as %s", self.athlete or "?")

            reader = asyncio.create_task(self._read(ws))
            writer = asyncio.create_task(self._write(ws))
            backfill = asyncio.create_task(self._backfill(ws, welcome.get("known") or []))
            try:
                # Only the reader and the writer decide how long the
                # connection lives. Waiting on the backfill as well would
                # tear the socket down the moment it ran out of history.
                done, _ = await asyncio.wait({reader, writer},
                                             return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()              # re-raise whatever ended it
            finally:
                for task in (reader, writer, backfill):
                    task.cancel()
                self.connected = False

    async def _write(self, ws) -> None:
        while True:
            msg = await self._queue.get()
            if msg.get("type") == "__stop__":
                raise RuntimeError("stopping")
            if msg.get("type") == "__reconnect__":
                raise RuntimeError("settings changed")
            await ws.send(json.dumps(msg))
            self.last_sent = time.time()

    async def _read(self, ws) -> None:
        while True:
            msg = json.loads(await ws.recv())
            kind = msg.get("type")
            if kind == "ping":
                await ws.send(json.dumps({"type": "pong"}))
            elif kind == "cmd" and self.on_command:
                log.info("Uplink command: %s", msg.get("cmd"))
                try:
                    self.on_command(msg.get("cmd"), msg)
                except Exception:
                    log.exception("Command handler")

    async def _backfill(self, ws, known: list) -> None:
        """Send finished sessions the server has never seen."""
        have = set(known)
        try:
            rows = await asyncio.to_thread(self.db.sessions_for_uplink)
        except Exception:
            log.exception("Backfill query")
            return
        missing = [r for r in rows if r["session_id"] not in have and r["ended_at"]]
        if not missing:
            return
        log.info("Uplink backfilling %d session(s)", len(missing))
        for row in reversed(missing):          # oldest first, so history reads right
            samples = await asyncio.to_thread(self.db.get_samples, row["session_id"])
            if not samples or len(samples) > BACKFILL_MAX_SAMPLES:
                continue
            summary = {}
            if row.get("summary_json"):
                try:
                    summary = json.loads(row["summary_json"])
                except json.JSONDecodeError:
                    summary = {}
            summary.setdefault("distance_m", row["distance_m"])
            summary.setdefault("duration_s", row["duration_s"])
            summary.setdefault("strokes", row["strokes"])
            summary.setdefault("avg_speed_ms", row["avg_speed_ms"])
            summary.setdefault("avg_spm", row["avg_spm"])
            await ws.send(json.dumps({
                "type": "backfill",
                "session": row["session_id"],
                "started_at": row["started_at"],
                "ended_at": row["ended_at"],
                "summary": summary,
                "samples": [
                    {"t": int(s.get("duration_s") or 0), "distance_m": s.get("distance_m"),
                     "speed_ms": s.get("speed_ms"), "stroke_rate": s.get("stroke_rate"),
                     "strokes": s.get("strokes"), "watts": s.get("watts")}
                    for s in samples
                ],
            }))
            # A backlog is not urgent; leave room for the live stream.
            await asyncio.sleep(0.5)
        log.info("Uplink backfill done")
