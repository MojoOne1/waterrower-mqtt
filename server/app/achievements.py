"""Badges, and the rules that hand them out.

Every rule has the same shape: a *metric* produces one number for an
athlete, and the badge is earned when that number passes a threshold. That
is the whole vocabulary, and it is deliberate - an admin can add badges from
the arena without anybody writing code, because there is nothing to write.
The cost is that a condition nobody anticipated cannot be expressed; a free
text field would only have looked like it could.

Checked on the server when a session closes and when a race ends, never in
the browser: a badge you can award yourself is not worth having.

A metric returns None when it does not apply - a "won by under a second"
rule has nothing to say about a session, and a start-hour rule has nothing
to say about a race. None never earns anything.
"""

import logging
import time

log = logging.getLogger("achievements")

# op -> does this value pass the threshold
OPS = {
    ">=": lambda value, threshold: value >= threshold,
    "<=": lambda value, threshold: value <= threshold,
}


# --- Metrics --------------------------------------------------------------
# Each takes (db, athlete_id, ctx) and returns a number or None. `ctx` holds
# what triggered the check: {"session": row} or {"race": row}.

def _sessions_total(db, athlete_id, ctx):
    return db.athlete_session_count(athlete_id)


def _distance_total(db, athlete_id, ctx):
    return db.athlete_distance_total(athlete_id)


def _session_distance(db, athlete_id, ctx):
    s = ctx.get("session")
    return float(s["distance_m"]) if s else None


def _session_duration(db, athlete_id, ctx):
    s = ctx.get("session")
    return float(s["duration_s"]) if s else None


def _session_start_hour(db, athlete_id, ctx):
    s = ctx.get("session")
    if not s:
        return None
    # The server's local time, which is the arena's time zone - the same one
    # the session lists are shown in, so "before six" means what it reads as.
    return float(time.localtime(s["started_at"]).tm_hour)


def _best(metres):
    def metric(db, athlete_id, ctx):
        return db.athlete_best("distance", metres, athlete_id)
    return metric


def _furthest(seconds):
    def metric(db, athlete_id, ctx):
        return db.athlete_best("time", seconds, athlete_id)
    return metric


def _race_wins(db, athlete_id, ctx):
    return float(db.athlete_race_wins(athlete_id))


def _race_win_streak(db, athlete_id, ctx):
    """Wins in a row, counting back from the most recent race they were in.

    Races they did not enter do not break it - being away is not losing.
    """
    streak = 0
    for place in db.athlete_race_places(athlete_id):
        if place == 1:
            streak += 1
        else:
            break
    return float(streak)


def _day_streak(db, athlete_id, ctx):
    """Days in a row with at least one session, counting back from the last."""
    days = db.athlete_session_days(athlete_id)
    if not days:
        return 0.0
    streak, previous = 1, days[0]
    for day in days[1:]:
        if previous - day == 86400:
            streak += 1
            previous = day
        else:
            break
    return float(streak)


def _race_margin_s(db, athlete_id, ctx):
    """Seconds between this athlete and the next one home, if they won.

    Only a distance race has an answer: in a time race the gap is metres.
    """
    race = ctx.get("race")
    if not race or race["mode"] != "distance":
        return None
    times = [(e["athlete_id"], e["time_s"]) for e in race["entries"]
             if e["kind"] == "live" and e["time_s"] is not None]
    if len(times) < 2:
        return None
    times.sort(key=lambda row: row[1])
    if times[0][0] != athlete_id:
        return None
    return float(times[1][1] - times[0][1])


METRICS = {
    "sessions_total": _sessions_total,
    "distance_total": _distance_total,
    "session_distance": _session_distance,
    "session_duration": _session_duration,
    "session_start_hour": _session_start_hour,
    "best_500": _best(500),
    "best_1000": _best(1000),
    "best_2000": _best(2000),
    "best_5000": _best(5000),
    "best_10000": _best(10000),
    "furthest_1200": _furthest(1200),
    "furthest_3600": _furthest(3600),
    "race_wins": _race_wins,
    "race_win_streak": _race_win_streak,
    "day_streak": _day_streak,
    "race_margin_s": _race_margin_s,
}

# What the admin form offers, with the unit each threshold is read in.
METRIC_UNITS = {
    "sessions_total": "Einheiten", "distance_total": "m",
    "session_distance": "m", "session_duration": "s", "session_start_hour": "Uhr",
    "best_500": "s", "best_1000": "s", "best_2000": "s",
    "best_5000": "s", "best_10000": "s",
    "furthest_1200": "m", "furthest_3600": "m",
    "race_wins": "Siege", "race_win_streak": "Siege", "day_streak": "Tage",
    "race_margin_s": "s",
}


# --- The twelve -----------------------------------------------------------
# key, name, note, icon, metric, op, threshold, hidden

BUILTIN = [
    ("first_row", "Erste Fahrt", "Eine Einheit aufgezeichnet.", "🚣",
     "sessions_total", ">=", 1, False),
    ("ten_k", "Zehntausend", "10 km insgesamt gerudert.", "📏",
     "distance_total", ">=", 10000, False),
    ("hundred_k", "Hunderttausend", "100 km insgesamt gerudert.", "🏔",
     "distance_total", ">=", 100000, False),
    ("half_hour", "Halbe Stunde", "30 Minuten am Stück, ohne abzusetzen.", "⏳",
     "session_duration", ">=", 1800, False),
    ("sub_two", "Unter 2:00", "500 m schneller als zwei Minuten.", "⚡",
     "best_500", "<=", 120, False),
    ("sub_eight", "2 km unter 8:00", "Die klassische Distanz unter acht Minuten.", "🎯",
     "best_2000", "<=", 480, False),
    ("first_win", "Erster Sieg", "Ein Rennen gewonnen.", "🥇",
     "race_wins", ">=", 1, False),
    ("hat_trick", "Dreimal in Folge", "Drei Rennen hintereinander gewonnen.", "👑",
     "race_win_streak", ">=", 3, False),
    # The hidden four. Nobody is told these exist until they walk into one.
    # Thresholds are the *hour the session started in*: <= 7 catches
    # anything begun before eight, >= 21 anything begun from nine in the
    # evening on.
    ("early_bird", "Frühaufsteher", "Eine Einheit vor acht Uhr morgens begonnen.", "🌅",
     "session_start_hour", "<=", 7, True),
    ("night_shift", "Nachtschicht", "Eine Einheit nach 21 Uhr begonnen.", "🌙",
     "session_start_hour", ">=", 21, True),
    ("week_streak", "Wochenstreak", "Sieben Tage hintereinander gerudert.", "🔥",
     "day_streak", ">=", 7, True),
    ("photo_finish", "Fotofinish", "Ein Rennen mit unter einer Sekunde Vorsprung gewonnen.", "📸",
     "race_margin_s", "<=", 1, True),
]


def seed(db) -> None:
    """Only on an empty table: an admin who cleared them out meant it."""
    if db.count_achievements():
        return
    for key, name, note, icon, metric, op, threshold, hidden in BUILTIN:
        db.add_achievement(key, name, note, icon, metric, op, threshold, hidden, builtin=True)
    log.info("Seeded %d achievements", len(BUILTIN))


def catch_up(db) -> int:
    """Walk the history and hand out whatever it already earned.

    Needed twice over: an arena that imported a year of rowing before these
    existed, and a badge an admin adds today - "100 km in total" should not
    ask somebody to row the first hundred again. Sessions oldest first, so
    the earned-at dates come out in the order things actually happened.
    """
    awarded = 0
    for athlete in db.list_athletes():
        for session in reversed(db.list_sessions(athlete["id"], limit=5000)):
            awarded += len(check(db, athlete["id"], {"session": session}))
    for race in reversed(db.list_races(limit=500)):
        if race["state"] != "finished":
            continue
        full = db.race(race["id"])
        for entry in full["entries"]:
            if entry["kind"] == "live":
                awarded += len(check(db, entry["athlete_id"], {"race": full}))
    if awarded:
        log.info("Caught up on %d badge(s) from the history", awarded)
    return awarded


def check(db, athlete_id: int, ctx: dict) -> list[dict]:
    """Award whatever this athlete has just become eligible for."""
    earned = []
    already = db.earned_keys(athlete_id)
    for badge in db.achievements():
        if badge["key"] in already:
            continue
        metric = METRICS.get(badge["metric"])
        if not metric:
            continue
        try:
            value = metric(db, athlete_id, ctx)
        except Exception:
            log.exception("Metric %s", badge["metric"])
            continue
        if value is None:
            continue
        if not OPS.get(badge["op"], OPS[">="])(value, badge["threshold"]):
            continue
        session = ctx.get("session")
        race = ctx.get("race")
        db.award(athlete_id, badge["id"], value,
                 session["id"] if session else None,
                 race["id"] if race else None)
        log.info("%s earned %r (%s = %s)", athlete_id, badge["name"],
                 badge["metric"], round(value, 2))
        earned.append(dict(badge, value=value))
    return earned
