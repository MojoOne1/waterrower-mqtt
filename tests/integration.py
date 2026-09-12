"""The tracker's uplink client against a real arena server in a subprocess.

Two processes on purpose: both halves have a module called db.py, and the
point is to exercise the real client, not a stand-in.
"""
import os
import subprocess
import sys
import tempfile
import time

import httpx

HERE = os.path.dirname(os.path.abspath(__file__))
# Whatever interpreter is running this suite runs the servers too.
PY = sys.executable
REPO = os.path.dirname(HERE)
PORT = 8791

sys.path.insert(0, os.path.join(REPO, "docker", "app"))
from db import Database          # noqa: E402  the tracker's
from uplink import Uplink        # noqa: E402

ok = fail = 0


def check(label, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ok   {label}")
    else:
        fail += 1
        print(f"  FAIL {label} {extra}")


def wait_for(fn, timeout=20, step=0.2):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if fn():
                return True
        except Exception:
            pass
        time.sleep(step)
    return False


tmp = tempfile.mkdtemp()
env = dict(os.environ,
           DB_PATH=os.path.join(tmp, "arena.db"),
           ARENA_ADMIN_PASSWORD="Supersecret1!",
           ARENA_SECURE_COOKIES="0",
           ARENA_COUNTDOWN="2",
           PYTHONUNBUFFERED="1")
# To a file, not a pipe: nobody drains a pipe here, and a full buffer
# would block the server mid-test.
LOG = open(os.path.join(tmp, "server.log"), "w+")
server = subprocess.Popen(
    [PY, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
    cwd=os.path.join(REPO, "server", "app"), env=env,
    stdout=LOG, stderr=subprocess.STDOUT, text=True)

base = f"http://127.0.0.1:{PORT}"
link = None
try:
    # /api/health, not /api/version: the latter is behind the sign-in now.
    up = wait_for(lambda: httpx.get(base + "/api/health", timeout=1).status_code == 200)
    if not up:
        LOG.seek(0)
        print(LOG.read())
        raise SystemExit("server did not start")
    print("\n-- server up")

    admin = httpx.Client(base_url=base, timeout=10)
    admin.post("/api/login", json={"name": "admin", "password": "Supersecret1!"}).raise_for_status()
    # The admin runs the arena; the rowing is done by an athlete account.
    made = admin.post("/api/athletes", json={"name": "rower", "display_name": "Rower"}).json()
    c = httpx.Client(base_url=base, timeout=10)
    c.post("/api/join", json={"code": made["invite_code"], "password": "Rowerspassword1!"}).raise_for_status()
    me = c.get("/api/me").json()
    token = c.post(f"/api/athletes/{me['id']}/tokens", json={"label": "test"}).json()["token"]
    check("token minted", bool(token))
    check("the rower is not an admin", me["is_admin"] is False, me)

    print("\n-- a tracker with two recorded sessions")
    tdb = Database(os.path.join(tmp, "tracker.db"))
    for sid, n in (("20260910T180000", 120), ("20260910T193000", 240)):
        for t in range(n):
            tdb.add_sample(sid, time.time(), {
                "distance_m": t * 4, "speed_ms": 4.0, "stroke_rate": 24,
                "strokes": t * 2, "duration_s": t, "watts": 150})
        tdb.close_session(sid, time.time(), {
            "session_id": sid, "distance_m": (n - 1) * 4, "duration_s": n - 1,
            "strokes": (n - 1) * 2, "avg_speed_ms": 4.0, "avg_spm": 24})
    check("tracker has 2 sessions", len(tdb.list_sessions()) == 2)

    # The session commands and the race pushes go down the same uplink,
    # so keep them apart: one asks the monitor to do something, the
    # other is just the race telling the tracker where it stands.
    commands, race_pushes = [], []

    def on_command(cmd, msg):
        if cmd == "race":
            race_pushes.append(msg.get("race"))
        else:
            commands.append(cmd)

    link = Uplink(tdb, {"arena_url": base, "arena_token": token, "arena_enabled": True},
                  on_command=on_command)
    link.start(version="1.7.0")

    print("\n-- uplink")
    check("connects", wait_for(lambda: link.status()["connected"]), link.status())
    check("knows the athlete", link.status()["athlete"] == "Rower", link.status())

    print("\n-- backfill")
    check("both sessions arrive", wait_for(lambda: len(c.get("/api/sessions").json()) == 2, 25),
          c.get("/api/sessions").json())
    rows = sorted(c.get("/api/sessions").json(), key=lambda r: r["remote_id"])
    check("summary carried over", rows[0]["distance_m"] == 476, rows[0])
    check("samples carried over",
          len(c.get(f"/api/sessions/{rows[0]['id']}").json()["samples"]) == 120)
    check("sessions are closed", all(r["ended_at"] for r in rows), rows)
    recs = c.get("/api/records").json()
    check("records computed from backfill", any(b["key"] == 500 for b in recs), recs)

    print("\n-- live samples")
    live_sid = "20260911T210000"
    started = time.time()
    for t in range(10):
        link.sample(live_sid, started, {
            "distance_m": t * 5, "speed_ms": 5.0, "stroke_rate": 28,
            "strokes": t * 2, "duration_s": t, "watts": 200})
        time.sleep(0.05)
    check("live session appears",
          wait_for(lambda: any(r["remote_id"] == live_sid for r in c.get("/api/sessions").json())))
    check("athlete shows as rowing",
          wait_for(lambda: any(a["rowing"] for a in c.get("/api/live").json()["athletes"])),
          c.get("/api/live").json())

    print("\n-- the arena drives the monitor")
    admin.post("/api/race", json={"name": "T", "mode": "distance", "target": 500}).raise_for_status()
    r = admin.post("/api/race/join")
    check("the admin cannot join their own race", r.status_code == 403, r.status_code)
    c.post("/api/race/join").raise_for_status()
    admin.post("/api/race/start").raise_for_status()
    check("reset reached the tracker", wait_for(lambda: commands == ["reset"], 10), commands)
    check("race is running", wait_for(
        lambda: (c.get("/api/race").json() or {}).get("state") == "running", 15))
    # The hub pushes twice a second; finishing in the same breath as the
    # start would skip the running state the tracker is meant to show.
    time.sleep(1.5)
    admin.post("/api/race/finish").raise_for_status()
    time.sleep(1.5)
    check("the finish does not end the session by itself", commands == ["reset"], commands)
    states = [r.get("state") for r in race_pushes if r]
    check("the race reached the tracker", "running" in states, states)
    check("and so did the finish", "finished" in states, states)
    last = [r for r in race_pushes if r][-1]
    check("with a place on it", last.get("place") == 1, last)
    c.post("/api/session/end").raise_for_status()
    check("ending it myself reaches the tracker",
          wait_for(lambda: commands == ["reset", "end"], 10), commands)
    admin.post("/api/race/clear")

    print("\n-- reconnect")
    # Twice, and on a short leash. Saving the form is not a failure: it
    # must not be shown to the rower as an error, and it must not feed the
    # backoff that exists for a broken network - which it did, so the
    # second save cost 35 seconds and the third would have cost more.
    for round_no in (1, 2):
        link.configure({"arena_url": base, "arena_token": token, "arena_enabled": False})
        check(f"disables cleanly ({round_no})",
              wait_for(lambda: not link.status()["connected"], 10), link.status())
        errors = []
        link.configure({"arena_url": base, "arena_token": token, "arena_enabled": True})

        def back():
            if link.status()["error"]:
                errors.append(link.status()["error"])
            return link.status()["connected"]

        check(f"comes straight back ({round_no})", wait_for(back, 8), link.status())
        check(f"saving is not an error ({round_no})", not errors, errors[:2])

    print("\n-- a bad token is reported, not retried blindly")
    link.configure({"arena_url": base, "arena_token": "nonsense", "arena_enabled": True})
    check("error surfaces", wait_for(lambda: link.status()["error"] and not link.status()["connected"], 15),
          link.status())

finally:
    if link:
        link.stop()
    LOG.seek(0)
    tail = LOG.read().splitlines()[-25:]
    server.terminate()
    try:
        server.wait(timeout=10)
    except subprocess.TimeoutExpired:
        server.kill()

print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
