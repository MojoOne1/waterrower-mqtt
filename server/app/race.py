"""The race engine.

A race is a set of lanes fed by the live sample stream. Three modes:

  distance  a set number of metres, first one there wins
  time      a set number of seconds, the most metres wins
  free      row together, compare live, nobody wins

A lane is either *live* (an athlete's tracker) or a *ghost* (a recorded
session replayed against the race clock), which is how you get to row
against a friend who is not at home, or against your own best.

Only one race is active at a time - with a handful of friends a second
simultaneous race is a complication nobody asked for. Finished races stay
in the database as history.

Timing: the race clock is the server's, and a lane's progress is placed on
it by the arrival time of its samples. Samples come once a second, so a
finish time is interpolated between the two samples that straddle the line.
The transport latency (tens of milliseconds, and much the same for every
lane) is the accuracy limit here - this is a race between friends, not a
timing gate.
"""

import asyncio
import logging
import time

import config

log = logging.getLogger("race")


def _split_500(speed_ms: float | None) -> str:
    if not speed_ms or speed_ms <= 0.1:
        return "--:--"
    s = 500 / speed_ms
    return f"{int(s // 60)}:{int(s % 60):02d}"


class Lane:
    def __init__(self, entry_id: int, athlete: dict, kind: str = "live",
                 ghost_session_id: int | None = None, ghost_samples: list | None = None,
                 ghost_label: str = ""):
        self.entry_id = entry_id
        self.athlete_id = athlete["id"]
        self.name = athlete["display_name"] + (f" ({ghost_label})" if kind == "ghost" else "")
        self.color = athlete["color"]
        self.kind = kind
        self.ghost_session_id = ghost_session_id
        self.ghost = ghost_samples or []

        self.ready = kind == "ghost"        # a ghost is always ready
        self.session_id: int | None = None
        self.baseline: float = 0.0
        self.last_raw: float | None = None
        self.progress: float = 0.0
        self.speed_ms: float = 0.0
        self.spm: int = 0
        self.watts: int = 0
        self.prev: tuple[float, float] | None = None   # (elapsed, progress)
        self.finished = False
        self.finish_t: float | None = None
        self.place: int | None = None
        self._spm_sum = self._watts_sum = 0.0
        self._n = 0

    def note(self, spm, watts) -> None:
        if spm:
            self._spm_sum += spm
        if watts:
            self._watts_sum += watts
        self._n += 1

    @property
    def avg_spm(self) -> float:
        return round(self._spm_sum / self._n, 1) if self._n else 0.0

    @property
    def avg_watts(self) -> float:
        return round(self._watts_sum / self._n, 1) if self._n else 0.0

    def ghost_progress(self, elapsed: float) -> tuple[float, float, int, int]:
        """Where the recorded session was `elapsed` seconds in."""
        rows = self.ghost
        if not rows:
            return 0.0, 0.0, 0, 0
        lo, hi = 0, len(rows) - 1
        if elapsed <= rows[0]["t"]:
            r = rows[0]
            return float(r["distance_m"] or 0), float(r["speed_ms"] or 0), r["stroke_rate"] or 0, r["watts"] or 0
        if elapsed >= rows[hi]["t"]:
            r = rows[hi]
            return float(r["distance_m"] or 0), 0.0, 0, 0
        while lo < hi - 1:
            mid = (lo + hi) // 2
            if rows[mid]["t"] <= elapsed:
                lo = mid
            else:
                hi = mid
        a, b = rows[lo], rows[hi]
        span = max(1e-6, b["t"] - a["t"])
        f = (elapsed - a["t"]) / span
        da, db = float(a["distance_m"] or 0), float(b["distance_m"] or 0)
        return da + (db - da) * f, float(b["speed_ms"] or 0), b["stroke_rate"] or 0, b["watts"] or 0

    def public(self) -> dict:
        return {
            "entry_id": self.entry_id,
            "athlete_id": self.athlete_id,
            "name": self.name,
            "color": self.color,
            "kind": self.kind,
            "ready": self.ready,
            "progress": round(self.progress, 1),
            "speed_ms": round(self.speed_ms, 2),
            "split_500": _split_500(self.speed_ms),
            "spm": self.spm,
            "watts": self.watts,
            "finished": self.finished,
            "time_s": round(self.finish_t, 2) if self.finish_t is not None else None,
            "place": self.place,
            "avg_spm": self.avg_spm,
            "avg_watts": self.avg_watts,
        }


class Race:
    def __init__(self, row: dict):
        self.id = row["id"]
        self.name = row["name"]
        self.mode = row["mode"]
        self.target = row["target"]
        self.state = "lobby"
        self.created_by = row["created_by"]
        self.lanes: list[Lane] = []
        self.started_at: float | None = None
        self.countdown_ends: float | None = None
        self.first_finish: float | None = None

    def lane_of(self, athlete_id: int) -> Lane | None:
        for l in self.lanes:
            if l.kind == "live" and l.athlete_id == athlete_id:
                return l
        return None

    @property
    def elapsed(self) -> float:
        return time.time() - self.started_at if self.started_at else 0.0

    def leader(self) -> Lane | None:
        if not self.lanes:
            return None
        done = [l for l in self.lanes if l.finished and l.finish_t is not None]
        if done and self.mode == "distance":
            return min(done, key=lambda l: l.finish_t)
        return max(self.lanes, key=lambda l: l.progress)

    def public(self) -> dict:
        lead = self.leader()
        lanes = []
        for l in self.lanes:
            d = l.public()
            if lead and self.target:
                d["pct"] = round(min(100.0, l.progress / self.target * 100), 1) \
                    if self.mode == "distance" else round(min(100.0, self.elapsed / self.target * 100), 1)
            else:
                d["pct"] = 0.0
            gap_m = (lead.progress - l.progress) if lead else 0.0
            d["gap_m"] = round(gap_m, 1)
            # Seconds behind: at whose pace? The one still moving. Using the
            # leader's speed answers "how long until I am where they are",
            # which is the number that means something mid-race.
            pace = lead.speed_ms if lead and lead.speed_ms > 0.4 else l.speed_ms
            d["gap_s"] = round(gap_m / pace, 1) if pace > 0.4 and gap_m > 0 else 0.0
            if self.mode == "distance" and not l.finished and l.speed_ms > 0.4:
                d["eta_s"] = round(max(0.0, self.target - l.progress) / l.speed_ms, 1)
            else:
                d["eta_s"] = None
            lanes.append(d)
        return {
            "id": self.id,
            "name": self.name,
            "mode": self.mode,
            "target": self.target,
            "state": self.state,
            "created_by": self.created_by,
            "elapsed": round(self.elapsed, 2),
            "countdown_in": round(self.countdown_ends - time.time(), 2) if self.countdown_ends else None,
            "lanes": lanes,
        }


class RaceEngine:
    def __init__(self, db, hub):
        self.db = db
        self.hub = hub
        self.race: Race | None = None
        self._task: asyncio.Task | None = None
        self._gun: asyncio.Task | None = None

    # --- Lobby ------------------------------------------------------------

    def active(self) -> Race | None:
        return self.race

    def create(self, name: str, mode: str, target: int, athlete: dict) -> Race:
        if self.race and self.race.state != "finished":
            raise ValueError("A race is already running")
        race_id = self.db.create_race(name, mode, target, athlete["id"])
        self.race = Race({"id": race_id, "name": name, "mode": mode,
                          "target": target, "created_by": athlete["id"]})
        self.join(athlete)
        self._publish()
        return self.race

    def join(self, athlete: dict) -> Lane:
        r = self._lobby()
        existing = r.lane_of(athlete["id"])
        if existing:
            return existing
        entry_id = self.db.add_entry(r.id, athlete["id"], "live")
        lane = Lane(entry_id, athlete)
        r.lanes.append(lane)
        self._publish()
        return lane

    def add_ghost(self, athlete: dict, session: dict, samples: list) -> Lane:
        r = self._lobby()
        entry_id = self.db.add_entry(r.id, session["athlete_id"], "ghost", session["id"])
        if entry_id is None:
            raise ValueError("That recording is already a lane")
        ghost_athlete = {"id": session["athlete_id"], "display_name": session["display_name"],
                         "color": session["color"]}
        label = time.strftime("%d.%m.", time.localtime(session["started_at"]))
        lane = Lane(entry_id, ghost_athlete, "ghost", session["id"], samples, label)
        r.lanes.append(lane)
        self._publish()
        return lane

    def leave(self, athlete: dict, entry_id: int) -> None:
        r = self._lobby()
        lane = next((l for l in r.lanes if l.entry_id == entry_id), None)
        if not lane:
            return
        if lane.athlete_id != athlete["id"] and athlete["id"] != r.created_by and not athlete["is_admin"]:
            raise PermissionError("Not your lane")
        r.lanes.remove(lane)
        self.db.remove_entry(r.id, entry_id)
        self._publish()

    def set_ready(self, athlete: dict, ready: bool) -> None:
        r = self._lobby()
        lane = r.lane_of(athlete["id"])
        if lane:
            lane.ready = ready
            self._publish()

    def _lobby(self) -> Race:
        if not self.race or self.race.state not in ("lobby",):
            raise ValueError("No race is taking entries")
        return self.race

    # --- Start and finish -------------------------------------------------

    async def start(self, athlete: dict) -> None:
        r = self.race
        if not r or r.state != "lobby":
            raise ValueError("No race to start")
        if athlete["id"] != r.created_by and not athlete["is_admin"]:
            raise PermissionError("Only the host starts the race")
        if not [l for l in r.lanes if l.kind == "live"]:
            raise ValueError("Nobody is in the race")

        # Zero every monitor before the gun. The tracker turns this into
        # waterrower/cmd/end_session, which resets the S4 - so everyone
        # starts from 0 m and a fresh session.
        for lane in r.lanes:
            if lane.kind == "live":
                await self.hub.command(lane.athlete_id, "reset", race_id=r.id)

        r.state = "countdown"
        r.countdown_ends = time.time() + config.COUNTDOWN_S
        self.db.set_race_state(r.id, "countdown")
        self._publish()
        self._gun = asyncio.create_task(self._fire(r))

    async def _fire(self, r: Race) -> None:
        try:
            await asyncio.sleep(max(0.0, r.countdown_ends - time.time()))
            if self.race is not r or r.state != "countdown":
                return
            now = time.time()
            r.started_at = now
            r.countdown_ends = None
            r.state = "running"
            # Whatever they have already rowed during the countdown is theirs
            # to keep, not part of the race.
            for lane in r.lanes:
                if lane.kind != "live":
                    continue
                live = self.hub.live.get(lane.athlete_id) or {}
                lane.baseline = float((live.get("values") or {}).get("distance_m") or 0)
                lane.last_raw = lane.baseline
                lane.session_id = live.get("session_id")
            self.db.set_race_state(r.id, "running", started_at=now)
            self._publish()
            self._task = asyncio.create_task(self._run(r))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Race start")

    async def _run(self, r: Race) -> None:
        interval = 1 / config.TICK_HZ
        try:
            while self.race is r and r.state == "running":
                await asyncio.sleep(interval)
                e = r.elapsed
                for lane in r.lanes:
                    if lane.kind == "ghost" and not lane.finished:
                        d, v, spm, w = lane.ghost_progress(e)
                        lane.speed_ms, lane.spm, lane.watts = v, spm, w
                        lane.note(spm, w)
                        self._advance(r, lane, d, e)
                    elif lane.kind == "live" and not lane.finished:
                        # No sample for a while means they stopped rowing.
                        live = self.hub.live.get(lane.athlete_id) or {}
                        if time.time() - (live.get("updated_at") or 0) > 4:
                            lane.speed_ms, lane.spm, lane.watts = 0.0, 0, 0
                if r.mode == "time" and e >= r.target:
                    await self.finish(reason="time")
                    return
                if r.mode in ("distance",) and r.first_finish and \
                        time.time() - r.first_finish > config.FINISH_GRACE_S:
                    await self.finish(reason="grace")
                    return
                if r.mode == "distance" and all(l.finished for l in r.lanes):
                    await self.finish(reason="all")
                    return
                self._publish()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Race loop")

    def _advance(self, r: Race, lane: Lane, raw_distance: float, elapsed: float) -> None:
        """Move a lane to `raw_distance` and check whether it crossed the line."""
        # A monitor reset mid-race sends distance back to zero. Rebasing on
        # the drop keeps the lane's progress instead of throwing the race.
        if lane.last_raw is not None and raw_distance < lane.last_raw - 5:
            lane.baseline = raw_distance - lane.progress
        lane.last_raw = raw_distance
        progress = max(0.0, raw_distance - lane.baseline)
        prev = lane.prev
        lane.prev = (elapsed, progress)
        lane.progress = progress

        if r.mode != "distance" or lane.finished or progress < r.target:
            return
        # Interpolate the moment the line was crossed, between this sample
        # and the one before it.
        if prev and progress > prev[1]:
            f = (r.target - prev[1]) / (progress - prev[1])
            lane.finish_t = prev[0] + f * (elapsed - prev[0])
        else:
            lane.finish_t = elapsed
        lane.finished = True
        lane.progress = float(r.target)
        if r.first_finish is None:
            r.first_finish = time.time()
        log.info("Race %s: %s finished in %.2fs", r.id, lane.name, lane.finish_t)

    def on_sample(self, athlete_id: int, session_id: int, t: int, data: dict) -> None:
        r = self.race
        if not r or r.state != "running":
            return
        lane = r.lane_of(athlete_id)
        if not lane or lane.finished:
            return
        lane.session_id = session_id
        lane.speed_ms = float(data.get("speed_ms") or 0)
        lane.spm = int(data.get("stroke_rate") or 0)
        lane.watts = int(data.get("watts") or 0)
        lane.note(lane.spm, lane.watts)
        self._advance(r, lane, float(data.get("distance_m") or 0), r.elapsed)

    def on_session_end(self, athlete_id: int, session_id: int) -> None:
        r = self.race
        if r and r.state == "running":
            lane = r.lane_of(athlete_id)
            if lane and lane.session_id is None:
                lane.session_id = session_id

    async def finish(self, reason: str = "host", athlete: dict | None = None) -> None:
        r = self.race
        if not r or r.state not in ("running", "countdown", "lobby"):
            return
        if athlete and athlete["id"] != r.created_by and not athlete["is_admin"]:
            raise PermissionError("Only the host ends the race")
        if r.state != "running":
            await self.abort(athlete)
            return

        r.state = "finished"
        now = time.time()
        for lane in r.lanes:
            if not lane.finished:
                lane.finish_t = None if r.mode == "distance" else r.elapsed
        self._place(r)
        for lane in r.lanes:
            self.db.save_entry_result(
                lane.entry_id, int(round(lane.progress)), lane.finish_t, lane.place,
                lane.avg_spm, lane.avg_watts,
                lane.session_id if lane.kind == "live" else lane.ghost_session_id,
            )
            if lane.kind == "live" and lane.session_id:
                self.db.link_session_to_race(lane.session_id, r.id)
        self.db.set_race_state(r.id, "finished", finished_at=now)

        # Close the session on each monitor, the mirror image of the reset
        # before the gun. Without this the S4 keeps the session open until
        # its own activity timeout, so the summary - and with it the
        # averages and the personal bests - arrives minutes late and covers
        # more than the race.
        if config.END_AT_FINISH:
            for lane in r.lanes:
                if lane.kind == "live":
                    await self.hub.command(lane.athlete_id, "end", race_id=r.id)

        log.info("Race %s finished (%s)", r.id, reason)
        self._publish()
        self.hub.broadcast({"type": "race_result", "race": self.db.race(r.id)})

    @staticmethod
    def _place(r: Race) -> None:
        """Ranking: finishers by time, then whoever got furthest."""
        if r.mode == "distance":
            done = sorted([l for l in r.lanes if l.finish_t is not None], key=lambda l: l.finish_t)
            rest = sorted([l for l in r.lanes if l.finish_t is None],
                          key=lambda l: l.progress, reverse=True)
        else:
            done = sorted(r.lanes, key=lambda l: l.progress, reverse=True)
            rest = []
        for i, lane in enumerate(done + rest, start=1):
            lane.place = i if r.mode != "free" else None

    async def abort(self, athlete: dict | None = None) -> None:
        r = self.race
        if not r:
            return
        if athlete and athlete["id"] != r.created_by and not athlete["is_admin"]:
            raise PermissionError("Only the host cancels the race")
        for task in (self._task, self._gun):
            if task and not task.done():
                task.cancel()
        self.db.set_race_state(r.id, "aborted", finished_at=time.time())
        r.state = "aborted"
        self._publish()
        self.race = None

    def clear_if_done(self) -> bool:
        """Put the lobby back. Says whether it actually did anything, so a
        running race cannot be blanked off everyone's screen."""
        if self.race and self.race.state in ("finished", "aborted"):
            self.race = None
            return True
        return False

    # --- Fan-out ----------------------------------------------------------

    def _publish(self) -> None:
        if self.race:
            self.hub.broadcast({"type": "race", "race": self.race.public()})
        else:
            self.hub.broadcast({"type": "race", "race": None})
