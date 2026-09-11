"""Personal bests, scanned out of the recorded samples.

A "2 km best" is not the same as "a session that happened to be 2 km long" -
the best 2 km of a 6 km row counts too. So every session is scanned with a
rolling window: the fastest 500 m / 1 k / 2 k / 5 k / 10 k it contains, and
the furthest it got in 5 / 10 / 20 / 30 / 60 minutes.

The scan is linear in the number of samples and runs once per session, when
it closes; the results land in a table the leaderboards then just read.
"""

import logging

import config

log = logging.getLogger("records")


def _series(samples: list[dict]) -> tuple[list[float], list[float]]:
    """Time and distance, cleaned into two monotonic lists."""
    ts: list[float] = []
    ds: list[float] = []
    for s in samples:
        t = s.get("t")
        d = s.get("distance_m")
        if t is None or d is None:
            continue
        t, d = float(t), float(d)
        # The monitor can repeat a second, and a mid-session reset would send
        # distance backwards; neither may turn into a record.
        if ts and (t <= ts[-1] or d < ds[-1]):
            continue
        ts.append(t)
        ds.append(d)
    return ts, ds


def best_time_for(samples: list[dict], metres: int) -> float | None:
    """Shortest time in which `metres` were covered, anywhere in the session."""
    ts, ds = _series(samples)
    if len(ts) < 2 or ds[-1] - ds[0] < metres:
        return None
    best = None
    i = 0
    for j in range(1, len(ts)):
        while i + 1 < j and ds[j] - ds[i + 1] >= metres:
            i += 1
        if ds[j] - ds[i] < metres:
            continue
        # The window starts between sample i and i+1: interpolate the moment
        # the rower was exactly `metres` behind where they are at j.
        want = ds[j] - metres
        if i + 1 < len(ds) and ds[i + 1] > ds[i]:
            f = min(1.0, max(0.0, (want - ds[i]) / (ds[i + 1] - ds[i])))
            t_start = ts[i] + f * (ts[i + 1] - ts[i])
        else:
            t_start = ts[i]
        span = ts[j] - t_start
        if span > 0 and (best is None or span < best):
            best = span
    return round(best, 2) if best else None


def best_distance_in(samples: list[dict], seconds: int) -> float | None:
    """Furthest covered in any window of `seconds`."""
    ts, ds = _series(samples)
    if len(ts) < 2 or ts[-1] - ts[0] < seconds:
        return None
    best = None
    i = 0
    for j in range(1, len(ts)):
        while i + 1 < j and ts[j] - ts[i + 1] >= seconds:
            i += 1
        if ts[j] - ts[i] < seconds:
            continue
        want = ts[j] - seconds
        if i + 1 < len(ts) and ts[i + 1] > ts[i]:
            f = min(1.0, max(0.0, (want - ts[i]) / (ts[i + 1] - ts[i])))
            d_start = ds[i] + f * (ds[i + 1] - ds[i])
        else:
            d_start = ds[i]
        span = ds[j] - d_start
        if best is None or span > best:
            best = span
    return round(best, 1) if best else None


def scan(samples: list[dict]) -> list[tuple[str, int, float]]:
    """Every record this session holds, as (kind, key, value) rows."""
    out: list[tuple[str, int, float]] = []
    for m in config.RECORD_DISTANCES:
        v = best_time_for(samples, m)
        if v:
            out.append(("distance", m, v))
    for s in config.RECORD_TIMES:
        v = best_distance_in(samples, s)
        if v:
            out.append(("time", s, v))
    return out


def index_session(db, session_id: int) -> int:
    """(Re)scan one session. Returns how many records it yielded."""
    rows = scan(db.samples(session_id))
    db.save_records(session_id, rows)
    return len(rows)


def index_missing(db, limit: int = 500) -> int:
    """Catch up on sessions recorded before this ran - e.g. after a backfill."""
    ids = db.sessions_missing_records(limit)
    for sid in ids:
        try:
            index_session(db, sid)
        except Exception:
            log.exception("Indexing session %s", sid)
    if ids:
        log.info("Indexed %d session(s) for records", len(ids))
    return len(ids)
