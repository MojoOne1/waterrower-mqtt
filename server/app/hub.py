"""Live state and the fan-out to browsers.

One hub holds what every athlete is doing right now, the open uplink of each
of their trackers, and the set of browsers watching. Samples arrive at 1 Hz
per athlete; browsers are served from a coalescing loop instead of per
message, so a busy race is still one frame per tick rather than one frame
per rower.
"""

import asyncio
import logging
import time

import config

log = logging.getLogger("hub")


class Viewer:
    """A browser on /ws/live. Slow ones lose frames, never the connection."""

    def __init__(self, athlete_id: int):
        self.athlete_id = athlete_id
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=60)

    def send(self, msg: dict) -> None:
        if self.queue.full():
            try:
                self.queue.get_nowait()     # the newest frame is what matters
            except asyncio.QueueEmpty:
                pass
        self.queue.put_nowait(msg)


class Uplink:
    """A tracker's WebSocket, from the hub's side: somewhere to send commands."""

    def __init__(self, athlete_id: int, websocket, agent: str):
        self.athlete_id = athlete_id
        self.websocket = websocket
        self.agent = agent
        self.connected_at = time.time()
        self.last_seen = time.time()

    async def send(self, msg: dict) -> None:
        try:
            await self.websocket.send_json(msg)
        except Exception as e:                      # closing mid-send is normal
            log.debug("Uplink send failed (athlete %s): %s", self.athlete_id, e)


class Hub:
    def __init__(self, db):
        self.db = db
        self.viewers: set[Viewer] = set()
        self.uplinks: dict[int, Uplink] = {}
        self.live: dict[int, dict] = {}
        self._dirty: set[int] = set()
        self.races = None                  # set by main.py; avoids a cycle
        self._race_sent: dict[int, str] = {}   # athlete -> last payload sent

    # --- Live state -------------------------------------------------------

    def state_of(self, athlete_id: int) -> dict:
        return self.live.setdefault(athlete_id, {
            "athlete_id": athlete_id,
            "online": False,
            "rowing": False,
            "session_id": None,
            "remote_id": "",
            "values": {},
            "updated_at": 0.0,
        })

    def snapshot(self) -> list[dict]:
        now = time.time()
        out = []
        for athlete_id, s in self.live.items():
            d = dict(s)
            # A tracker that went quiet is not rowing, whatever it last said.
            d["rowing"] = bool(s["rowing"] and now - s["updated_at"] < 15)
            out.append(d)
        return out

    def set_online(self, athlete_id: int, online: bool, agent: str = "") -> None:
        s = self.state_of(athlete_id)
        s["online"] = online
        s["agent"] = agent
        if not online:
            s["rowing"] = False
        s["updated_at"] = time.time()
        self._dirty.add(athlete_id)

    def on_sample(self, athlete_id: int, remote_id: str, session_id: int, t: int, data: dict) -> None:
        s = self.state_of(athlete_id)
        s["rowing"] = True
        s["session_id"] = session_id
        s["remote_id"] = remote_id
        s["values"] = {
            "t": t,
            "distance_m": data.get("distance_m"),
            "speed_ms": data.get("speed_ms"),
            "stroke_rate": data.get("stroke_rate"),
            "strokes": data.get("strokes"),
            "watts": data.get("watts"),
        }
        s["updated_at"] = time.time()
        self._dirty.add(athlete_id)
        if self.races:
            self.races.on_sample(athlete_id, session_id, t, data)

    def on_session_end(self, athlete_id: int, session_id: int) -> None:
        s = self.state_of(athlete_id)
        s["rowing"] = False
        s["updated_at"] = time.time()
        self._dirty.add(athlete_id)
        if self.races:
            self.races.on_session_end(athlete_id, session_id)

    # --- Fan-out ----------------------------------------------------------

    def add_viewer(self, viewer: Viewer) -> None:
        self.viewers.add(viewer)

    def remove_viewer(self, viewer: Viewer) -> None:
        self.viewers.discard(viewer)

    def broadcast(self, msg: dict) -> None:
        for v in list(self.viewers):
            v.send(msg)

    async def _push_race(self) -> None:
        """Send each racer their own slice of the race, down their uplink.

        So the tracker at the machine can show the countdown and where they
        stand - the arena is on a phone somewhere, the tracker is on the
        screen in front of them. Only their own lane and the gap, not the
        whole field: the tracker has no room for it and the arena is where
        you go to watch everybody.
        """
        race = self.races.active() if self.races else None
        if not race or race.state not in ("countdown", "running", "finished"):
            for athlete_id in list(self._race_sent):
                self._race_sent.pop(athlete_id, None)
                await self.command(athlete_id, "race", race=None)
            return

        public = race.public()
        leader = max((l for l in public["lanes"]), key=lambda l: l["progress"], default=None)
        for lane in public["lanes"]:
            if lane["kind"] != "live":
                continue
            payload = {
                "state": public["state"],
                "name": public["name"],
                "mode": public["mode"],
                "target": public["target"],
                "elapsed": public["elapsed"],
                "countdown_in": public["countdown_in"],
                "place": lane["place"] or (1 if leader and lane is leader else None),
                "progress": lane["progress"],
                "gap_m": lane["gap_m"],
                "finished": lane["finished"],
                "time_s": lane["time_s"],
                "lanes": len([l for l in public["lanes"]]),
            }
            fingerprint = repr(payload)
            if self._race_sent.get(lane["athlete_id"]) == fingerprint:
                continue
            self._race_sent[lane["athlete_id"]] = fingerprint
            await self.command(lane["athlete_id"], "race", race=payload)

    async def command(self, athlete_id: int, cmd: str, **extra) -> bool:
        """Ask an athlete's tracker to do something (today: reset the monitor)."""
        uplink = self.uplinks.get(athlete_id)
        if not uplink:
            return False
        await uplink.send({"type": "cmd", "cmd": cmd, **extra})
        return True

    async def run(self) -> None:
        """Flush changed live state to the browsers, and time out dead uplinks."""
        interval = 1 / config.TICK_HZ
        while True:
            await asyncio.sleep(interval)
            try:
                now = time.time()
                for athlete_id, s in self.live.items():
                    if s["online"] and now - s["updated_at"] > config.UPLINK_TIMEOUT_S:
                        s["online"] = s["rowing"] = False
                        self._dirty.add(athlete_id)
                if self._dirty:
                    states = [dict(self.live[a], rowing=bool(
                        self.live[a]["rowing"] and now - self.live[a]["updated_at"] < 15))
                        for a in self._dirty if a in self.live]
                    self._dirty.clear()
                    self.broadcast({"type": "live", "athletes": states})
                await self._push_race()
            except Exception:
                log.exception("Hub loop")
