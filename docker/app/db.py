"""SQLite-Speicher für Sessions und Messpunkte."""

import json
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

_SID = re.compile(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})$")


def started_from_sid(session_id: str, fallback: float) -> float:
    """Session-IDs der ESPHome-Bridge sind Zeitstempel (lokale Zeit des ESP)."""
    m = _SID.match(session_id)
    if not m:
        return fallback
    y, mo, d, h, mi, s = map(int, m.groups())
    return time.mktime((y, mo, d, h, mi, s, 0, 0, -1))

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    started_at   REAL NOT NULL,
    ended_at     REAL,
    distance_m   INTEGER DEFAULT 0,
    duration_s   INTEGER DEFAULT 0,
    strokes      INTEGER DEFAULT 0,
    avg_speed_ms REAL    DEFAULT 0,
    avg_spm      REAL    DEFAULT 0,
    summary_json TEXT
);

CREATE TABLE IF NOT EXISTS samples (
    session_id   TEXT NOT NULL,
    ts           REAL NOT NULL,
    distance_m   INTEGER,
    speed_ms     REAL,
    stroke_rate  INTEGER,
    strokes      INTEGER,
    duration_s   INTEGER,
    watts        INTEGER,
    PRIMARY KEY (session_id, ts)
);

CREATE INDEX IF NOT EXISTS idx_samples_session ON samples(session_id);
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
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # --- Schreiben -------------------------------------------------------

    def add_sample(self, session_id: str, ts: float, data: dict) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO sessions (session_id, started_at) VALUES (?, ?)",
                (session_id, started_from_sid(session_id, ts)),
            )
            c.execute(
                """INSERT OR REPLACE INTO samples
                   (session_id, ts, distance_m, speed_ms, stroke_rate, strokes, duration_s, watts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id, ts,
                    data.get("distance_m"), data.get("speed_ms"), data.get("stroke_rate"),
                    data.get("strokes"), data.get("duration_s"), data.get("watts"),
                ),
            )
            # laufende Kennzahlen mitführen, damit die Liste auch ohne
            # Zusammenfassung sinnvolle Werte zeigt
            c.execute(
                """UPDATE sessions SET
                     distance_m = ?, duration_s = ?, strokes = ?,
                     avg_speed_ms = (SELECT AVG(speed_ms)    FROM samples WHERE session_id = ?),
                     avg_spm      = (SELECT AVG(stroke_rate) FROM samples WHERE session_id = ?)
                   WHERE session_id = ?""",
                (
                    data.get("distance_m", 0), data.get("duration_s", 0), data.get("strokes", 0),
                    session_id, session_id, session_id,
                ),
            )

    def close_session(self, session_id: str, ts: float, summary: dict) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO sessions (session_id, started_at) VALUES (?, ?)",
                (session_id, started_from_sid(session_id, ts)),
            )
            c.execute(
                """UPDATE sessions SET
                     ended_at = ?, distance_m = ?, duration_s = ?, strokes = ?,
                     avg_speed_ms = ?, avg_spm = ?, summary_json = ?
                   WHERE session_id = ?""",
                (
                    ts,
                    summary.get("distance_m", 0), summary.get("duration_s", 0),
                    summary.get("strokes", 0), summary.get("avg_speed_ms", 0),
                    summary.get("avg_spm", 0), json.dumps(summary), session_id,
                ),
            )

    def delete_session(self, session_id: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM samples  WHERE session_id = ?", (session_id,))
            c.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))

    # --- Lesen -----------------------------------------------------------

    def list_sessions(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM sessions ORDER BY started_at DESC"
            ).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d["sparkline"] = self._sparkline(c, d["session_id"])
                out.append(d)
        return out

    @staticmethod
    def _sparkline(c, session_id: str, points: int = 40) -> list[float]:
        """Geschwindigkeit auf `points` Stützstellen reduziert, für die Liste."""
        rows = c.execute(
            "SELECT speed_ms FROM samples WHERE session_id = ? ORDER BY ts", (session_id,)
        ).fetchall()
        vals = [r[0] or 0 for r in rows]
        if len(vals) <= points:
            return vals
        step = len(vals) / points
        return [round(sum(vals[int(i * step):int((i + 1) * step)]) / max(1, int((i + 1) * step) - int(i * step)), 2)
                for i in range(points)]

    def get_session(self, session_id: str) -> dict | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if not row:
                return None
            samples = c.execute(
                "SELECT * FROM samples WHERE session_id = ? ORDER BY ts", (session_id,)
            ).fetchall()
        return {"session": dict(row), "samples": [dict(s) for s in samples]}

    def get_samples(self, session_id: str) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM samples WHERE session_id = ? ORDER BY ts", (session_id,)
            ).fetchall()
        return [dict(r) for r in rows]
