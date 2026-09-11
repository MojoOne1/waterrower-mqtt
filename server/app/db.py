"""SQLite storage for the arena: athletes, sessions, samples, races.

The tracker's own database keeps one row per session and one per sample of a
single machine. Here every row carries an athlete, so the same session ID
arriving from two ESPs (they are local timestamps) can no longer collide:
sessions get a surrogate key and (athlete_id, remote_id) is the unique one.
"""

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS athletes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL UNIQUE,          -- login handle, lower case
    display_name  TEXT NOT NULL,
    password_hash TEXT,                          -- NULL until the invite is redeemed
    invite_code   TEXT UNIQUE,                   -- cleared on redemption
    is_admin      INTEGER NOT NULL DEFAULT 0,
    color         TEXT NOT NULL DEFAULT '',      -- lane colour, also used in charts
    created_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS device_tokens (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    athlete_id   INTEGER NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
    token_hash   TEXT NOT NULL UNIQUE,
    label        TEXT NOT NULL DEFAULT '',
    created_at   REAL NOT NULL,
    last_seen_at REAL
);

CREATE TABLE IF NOT EXISTS web_sessions (
    token_hash TEXT PRIMARY KEY,
    athlete_id INTEGER NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    athlete_id   INTEGER NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
    remote_id    TEXT NOT NULL,                  -- the ESP's session ID
    started_at   REAL NOT NULL,
    ended_at     REAL,
    distance_m   INTEGER NOT NULL DEFAULT 0,
    duration_s   INTEGER NOT NULL DEFAULT 0,
    strokes      INTEGER NOT NULL DEFAULT 0,
    avg_speed_ms REAL NOT NULL DEFAULT 0,
    avg_spm      REAL NOT NULL DEFAULT 0,
    avg_watts    REAL NOT NULL DEFAULT 0,
    race_id      INTEGER,
    records_done INTEGER NOT NULL DEFAULT 0,     -- scanned for personal bests
    UNIQUE (athlete_id, remote_id)
);

CREATE INDEX IF NOT EXISTS idx_sessions_athlete ON sessions(athlete_id, started_at DESC);

-- One row per standard effort a session contains: kind 'distance' stores the
-- seconds for those metres, kind 'time' the metres in those seconds.
CREATE TABLE IF NOT EXISTS session_records (
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,
    key        INTEGER NOT NULL,
    value      REAL NOT NULL,
    PRIMARY KEY (session_id, kind, key)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS samples (
    session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    t           INTEGER NOT NULL,   -- seconds since session start, the device's own clock
    ts          REAL,               -- server time of arrival (NULL when backfilled)
    distance_m  INTEGER,
    speed_ms    REAL,
    stroke_rate INTEGER,
    strokes     INTEGER,
    watts       INTEGER,
    PRIMARY KEY (session_id, t)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS races (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL DEFAULT '',
    mode        TEXT NOT NULL,                   -- distance | time | free
    target      INTEGER NOT NULL DEFAULT 0,      -- metres, or seconds; 0 for free
    state       TEXT NOT NULL DEFAULT 'lobby',   -- lobby|countdown|running|finished|aborted
    created_by  INTEGER REFERENCES athletes(id) ON DELETE SET NULL,
    created_at  REAL NOT NULL,
    started_at  REAL,
    finished_at REAL
);

CREATE TABLE IF NOT EXISTS race_entries (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id          INTEGER NOT NULL REFERENCES races(id) ON DELETE CASCADE,
    athlete_id       INTEGER NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
    kind             TEXT NOT NULL DEFAULT 'live',   -- live | ghost
    ghost_session_id INTEGER,
    session_id       INTEGER,
    distance_m       INTEGER NOT NULL DEFAULT 0,
    time_s           REAL,
    avg_spm          REAL NOT NULL DEFAULT 0,
    avg_watts        REAL NOT NULL DEFAULT 0,
    place            INTEGER,
    -- A ghost of your own past session is a legitimate second lane, so the
    -- unique key has to include the kind.
    UNIQUE (race_id, athlete_id, kind, ghost_session_id)
);
"""


class Database:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self._path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # --- Athletes ---------------------------------------------------------

    def create_athlete(self, name: str, display_name: str, invite_code: str,
                       color: str, is_admin: bool = False) -> int:
        with self._lock, self._conn() as c:
            cur = c.execute(
                """INSERT INTO athletes (name, display_name, invite_code, color, is_admin, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (name, display_name, invite_code, color, int(is_admin), time.time()),
            )
            return cur.lastrowid

    def athlete(self, athlete_id: int) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM athletes WHERE id = ?", (athlete_id,)).fetchone()
        return dict(r) if r else None

    def athlete_by_name(self, name: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM athletes WHERE name = ?", (name.lower(),)).fetchone()
        return dict(r) if r else None

    def athlete_by_invite(self, code: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM athletes WHERE invite_code = ?", (code,)).fetchone()
        return dict(r) if r else None

    def list_athletes(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM athletes ORDER BY display_name").fetchall()
        return [dict(r) for r in rows]

    def count_athletes(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM athletes").fetchone()[0]

    def set_password(self, athlete_id: int, password_hash: str) -> None:
        """Redeeming an invite also burns it - the code is single use."""
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE athletes SET password_hash = ?, invite_code = NULL WHERE id = ?",
                (password_hash, athlete_id),
            )

    def update_athlete(self, athlete_id: int, display_name: str, color: str) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE athletes SET display_name = ?, color = ? WHERE id = ?",
                (display_name, color, athlete_id),
            )

    def reset_invite(self, athlete_id: int, code: str) -> None:
        """A new invite also clears the old password - that is the point of it."""
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE athletes SET invite_code = ?, password_hash = NULL WHERE id = ?",
                (code, athlete_id),
            )

    def set_admin(self, athlete_id: int, is_admin: bool) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE athletes SET is_admin = ? WHERE id = ?",
                      (int(is_admin), athlete_id))

    def count_admins(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM athletes WHERE is_admin = 1").fetchone()[0]

    def delete_athlete(self, athlete_id: int) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM athletes WHERE id = ?", (athlete_id,))

    # --- Tokens and web sessions -----------------------------------------

    def add_token(self, athlete_id: int, token_hash: str, label: str) -> int:
        with self._lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO device_tokens (athlete_id, token_hash, label, created_at) VALUES (?, ?, ?, ?)",
                (athlete_id, token_hash, label, time.time()),
            )
            return cur.lastrowid

    def token_owner(self, token_hash: str) -> dict | None:
        with self._conn() as c:
            r = c.execute(
                """SELECT a.*, d.id AS token_id FROM device_tokens d
                   JOIN athletes a ON a.id = d.athlete_id
                   WHERE d.token_hash = ?""",
                (token_hash,),
            ).fetchone()
        return dict(r) if r else None

    def touch_token(self, token_id: int) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE device_tokens SET last_seen_at = ? WHERE id = ?",
                      (time.time(), token_id))

    def list_tokens(self, athlete_id: int) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                """SELECT id, label, created_at, last_seen_at FROM device_tokens
                   WHERE athlete_id = ? ORDER BY id""",
                (athlete_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_token(self, athlete_id: int, token_id: int) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM device_tokens WHERE id = ? AND athlete_id = ?",
                      (token_id, athlete_id))

    def add_web_session(self, token_hash: str, athlete_id: int, ttl_s: float) -> None:
        now = time.time()
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM web_sessions WHERE expires_at < ?", (now,))
            c.execute(
                """INSERT OR REPLACE INTO web_sessions (token_hash, athlete_id, created_at, expires_at)
                   VALUES (?, ?, ?, ?)""",
                (token_hash, athlete_id, now, now + ttl_s),
            )

    def web_session_owner(self, token_hash: str) -> dict | None:
        with self._conn() as c:
            r = c.execute(
                """SELECT a.* FROM web_sessions w JOIN athletes a ON a.id = w.athlete_id
                   WHERE w.token_hash = ? AND w.expires_at > ?""",
                (token_hash, time.time()),
            ).fetchone()
        return dict(r) if r else None

    def drop_web_session(self, token_hash: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM web_sessions WHERE token_hash = ?", (token_hash,))

    def drop_web_sessions_of(self, athlete_id: int) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM web_sessions WHERE athlete_id = ?", (athlete_id,))

    # --- Sessions and samples --------------------------------------------

    def session_id_for(self, athlete_id: int, remote_id: str, started_at: float) -> int:
        """The surrogate key for a device session, created on first sight."""
        with self._lock, self._conn() as c:
            r = c.execute(
                "SELECT id FROM sessions WHERE athlete_id = ? AND remote_id = ?",
                (athlete_id, remote_id),
            ).fetchone()
            if r:
                return r[0]
            cur = c.execute(
                "INSERT INTO sessions (athlete_id, remote_id, started_at) VALUES (?, ?, ?)",
                (athlete_id, remote_id, started_at),
            )
            return cur.lastrowid

    def add_sample(self, session_id: int, t: int, ts: float | None, data: dict) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                """INSERT OR REPLACE INTO samples
                   (session_id, t, ts, distance_m, speed_ms, stroke_rate, strokes, watts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id, t, ts,
                    data.get("distance_m"), data.get("speed_ms"), data.get("stroke_rate"),
                    data.get("strokes"), data.get("watts"),
                ),
            )
            # Keep running figures on the session row so one that is still
            # open already shows sensible numbers in the lists. Guarded by
            # the duration so a late-arriving older sample cannot rewind it.
            c.execute(
                """UPDATE sessions SET distance_m = ?, duration_s = ?, strokes = ?
                   WHERE id = ? AND ? >= duration_s""",
                (int(data.get("distance_m") or 0), t, int(data.get("strokes") or 0),
                 session_id, t),
            )

    def add_samples(self, session_id: int, rows: list[dict]) -> None:
        """Bulk path for backfill: one transaction for a whole session."""
        if not rows:
            return
        with self._lock, self._conn() as c:
            c.executemany(
                """INSERT OR IGNORE INTO samples
                   (session_id, t, ts, distance_m, speed_ms, stroke_rate, strokes, watts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (session_id, int(r.get("t") or 0), r.get("ts"),
                     r.get("distance_m"), r.get("speed_ms"), r.get("stroke_rate"),
                     r.get("strokes"), r.get("watts"))
                    for r in rows
                ],
            )

    def close_session(self, session_id: int, ended_at: float, summary: dict) -> None:
        """Write the device summary, folding the averages out of the samples.

        The ESP reports distance, duration, strokes and its own two averages;
        watts it does not average, so that one is computed here.
        """
        with self._lock, self._conn() as c:
            agg = c.execute(
                """SELECT AVG(speed_ms), AVG(stroke_rate), AVG(watts), MAX(distance_m), MAX(t)
                   FROM samples WHERE session_id = ?""",
                (session_id,),
            ).fetchone()
            avg_speed = summary.get("avg_speed_ms") or agg[0] or 0
            avg_spm = summary.get("avg_spm") or agg[1] or 0
            c.execute(
                """UPDATE sessions SET
                     ended_at = ?, distance_m = ?, duration_s = ?, strokes = ?,
                     avg_speed_ms = ?, avg_spm = ?, avg_watts = ?
                   WHERE id = ?""",
                (
                    ended_at,
                    int(summary.get("distance_m") or agg[3] or 0),
                    int(summary.get("duration_s") or agg[4] or 0),
                    int(summary.get("strokes") or 0),
                    round(float(avg_speed), 3), round(float(avg_spm), 2),
                    round(float(agg[2] or 0), 1),
                    session_id,
                ),
            )

    def session(self, session_id: int) -> dict | None:
        with self._conn() as c:
            r = c.execute(
                """SELECT s.*, a.display_name, a.color, a.name AS athlete_name
                   FROM sessions s JOIN athletes a ON a.id = s.athlete_id WHERE s.id = ?""",
                (session_id,),
            ).fetchone()
        return dict(r) if r else None

    def list_sessions(self, athlete_id: int | None = None, limit: int = 200,
                      since: float | None = None) -> list[dict]:
        sql = """SELECT s.*, a.display_name, a.color, a.name AS athlete_name
                 FROM sessions s JOIN athletes a ON a.id = s.athlete_id"""
        where, args = [], []
        if athlete_id:
            where.append("s.athlete_id = ?")
            args.append(athlete_id)
        if since:
            where.append("s.started_at >= ?")
            args.append(since)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY s.started_at DESC LIMIT ?"
        args.append(limit)
        with self._conn() as c:
            rows = c.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def samples(self, session_id: int) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                """SELECT t, distance_m, speed_ms, stroke_rate, strokes, watts
                   FROM samples WHERE session_id = ? ORDER BY t""",
                (session_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def known_remote_ids(self, athlete_id: int, limit: int = 500) -> list[str]:
        """What the server already holds, so an uplink knows what to backfill."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT remote_id FROM sessions WHERE athlete_id = ? ORDER BY started_at DESC LIMIT ?",
                (athlete_id, limit),
            ).fetchall()
        return [r[0] for r in rows]

    def delete_session(self, session_id: int) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM session_records WHERE session_id = ?", (session_id,))
            c.execute("DELETE FROM samples        WHERE session_id = ?", (session_id,))
            c.execute("DELETE FROM sessions       WHERE id = ?", (session_id,))

    # --- Personal bests ---------------------------------------------------

    def save_records(self, session_id: int, rows: list[tuple[str, int, float]]) -> None:
        """Replace a session's records. Marked done even when it holds none,
        so a short row is not rescanned on every start."""
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM session_records WHERE session_id = ?", (session_id,))
            c.executemany(
                "INSERT INTO session_records (session_id, kind, key, value) VALUES (?, ?, ?, ?)",
                [(session_id, k, key, val) for k, key, val in rows],
            )
            c.execute("UPDATE sessions SET records_done = 1 WHERE id = ?", (session_id,))

    def sessions_missing_records(self, limit: int = 500) -> list[int]:
        with self._conn() as c:
            rows = c.execute(
                """SELECT id FROM sessions
                   WHERE records_done = 0 AND ended_at IS NOT NULL
                   ORDER BY started_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [r[0] for r in rows]

    def mark_records_stale(self, session_id: int) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE sessions SET records_done = 0 WHERE id = ?", (session_id,))

    def all_records(self) -> list[dict]:
        """Every recorded effort with its owner; the API groups and ranks."""
        with self._conn() as c:
            rows = c.execute(
                """SELECT r.kind, r.key, r.value, s.id AS session_id, s.athlete_id,
                          s.started_at, a.display_name, a.color
                   FROM session_records r
                   JOIN sessions s ON s.id = r.session_id
                   JOIN athletes a ON a.id = s.athlete_id
                   WHERE a.is_admin = 0"""
            ).fetchall()
        return [dict(r) for r in rows]

    def link_session_to_race(self, session_id: int, race_id: int) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE sessions SET race_id = ? WHERE id = ?", (race_id, session_id))

    def totals(self, since: float | None = None) -> list[dict]:
        """One row per athlete. The date filter belongs in the JOIN, not in a
        WHERE - otherwise an athlete with nothing in the window disappears."""
        sql = """SELECT a.id AS athlete_id, a.display_name, a.color,
                        COUNT(s.id) AS sessions,
                        COALESCE(SUM(s.distance_m), 0) AS distance_m,
                        COALESCE(SUM(s.duration_s), 0) AS duration_s,
                        COALESCE(SUM(s.strokes), 0)    AS strokes
                 FROM athletes a LEFT JOIN sessions s ON s.athlete_id = a.id"""
        args: list = []
        if since:
            sql += " AND s.started_at >= ?"
            args.append(since)
        # Admins administer; they are not in the standings.
        sql += " WHERE a.is_admin = 0 GROUP BY a.id ORDER BY distance_m DESC"
        with self._conn() as c:
            rows = c.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    # --- Races ------------------------------------------------------------

    def create_race(self, name: str, mode: str, target: int, created_by: int) -> int:
        with self._lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO races (name, mode, target, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
                (name, mode, target, created_by, time.time()),
            )
            return cur.lastrowid

    def race(self, race_id: int) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM races WHERE id = ?", (race_id,)).fetchone()
            if not r:
                return None
            entries = c.execute(
                """SELECT e.*, a.display_name, a.color, a.name AS athlete_name
                   FROM race_entries e JOIN athletes a ON a.id = e.athlete_id
                   WHERE e.race_id = ? ORDER BY e.place IS NULL, e.place, e.id""",
                (race_id,),
            ).fetchall()
        out = dict(r)
        out["entries"] = [dict(e) for e in entries]
        return out

    def list_races(self, limit: int = 50) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM races ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            races = []
            for r in rows:
                d = dict(r)
                d["entries"] = [
                    dict(e) for e in c.execute(
                        """SELECT e.*, a.display_name, a.color FROM race_entries e
                           JOIN athletes a ON a.id = e.athlete_id
                           WHERE e.race_id = ? ORDER BY e.place IS NULL, e.place, e.id""",
                        (d["id"],),
                    ).fetchall()
                ]
                races.append(d)
        return races

    def add_entry(self, race_id: int, athlete_id: int, kind: str = "live",
                  ghost_session_id: int | None = None) -> int | None:
        with self._lock, self._conn() as c:
            try:
                cur = c.execute(
                    "INSERT INTO race_entries (race_id, athlete_id, kind, ghost_session_id) VALUES (?, ?, ?, ?)",
                    (race_id, athlete_id, kind, ghost_session_id),
                )
                return cur.lastrowid
            except sqlite3.IntegrityError:
                return None            # already in this race on that lane

    def remove_entry(self, race_id: int, entry_id: int) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM race_entries WHERE race_id = ? AND id = ?", (race_id, entry_id))

    def set_race_state(self, race_id: int, state: str, started_at: float | None = None,
                       finished_at: float | None = None) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                """UPDATE races SET state = ?,
                     started_at  = COALESCE(?, started_at),
                     finished_at = COALESCE(?, finished_at)
                   WHERE id = ?""",
                (state, started_at, finished_at, race_id),
            )

    def save_entry_result(self, entry_id: int, distance_m: int, time_s: float | None,
                          place: int | None, avg_spm: float, avg_watts: float,
                          session_id: int | None) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                """UPDATE race_entries SET distance_m = ?, time_s = ?, place = ?,
                     avg_spm = ?, avg_watts = ?, session_id = COALESCE(?, session_id)
                   WHERE id = ?""",
                (distance_m, time_s, place, avg_spm, avg_watts, session_id, entry_id),
            )

    def delete_race(self, race_id: int) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM race_entries WHERE race_id = ?", (race_id,))
            c.execute("DELETE FROM races WHERE id = ?", (race_id,))

    def finished_race_places(self) -> list[dict]:
        """Every placing of every finished race, for the head-to-head table."""
        with self._conn() as c:
            rows = c.execute(
                """SELECT r.id AS race_id, e.athlete_id, e.place
                   FROM races r JOIN race_entries e ON e.race_id = r.id
                   WHERE r.state = 'finished' AND e.place IS NOT NULL AND e.kind = 'live'
                   ORDER BY r.id, e.place"""
            ).fetchall()
        return [dict(r) for r in rows]
