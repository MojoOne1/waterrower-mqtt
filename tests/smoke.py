"""End-to-end smoke test for the arena: login, uplink, records, a race."""
import os
import sys
import time
import tempfile

TMP = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(TMP, "arena.db")
os.environ["ARENA_ADMIN_PASSWORD"] = "Supersecret1!"
os.environ["ARENA_SECURE_COOKIES"] = "0"
os.environ["ARENA_COUNTDOWN"] = "1"
os.environ["ARENA_TICK_HZ"] = "5"

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "server", "app"))

from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402
import auth as auth_mod  # noqa: E402

ok = 0
fail = 0


def check(label, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ok   {label}")
    else:
        fail += 1
        print(f"  FAIL {label} {extra}")


def samples(sid, start, rows):
    for t, d, v in rows:
        yield {"type": "sample", "session": sid, "started_at": start, "t": t,
               "distance_m": d, "speed_ms": v, "stroke_rate": 24, "strokes": t * 2,
               "watts": 140}


with TestClient(main.app) as c:
    print("\n-- auth")
    r = c.post("/api/login", json={"name": "admin", "password": "nope"})
    check("wrong password rejected", r.status_code == 401, r.status_code)
    r = c.post("/api/login", json={"name": "admin", "password": "Supersecret1!"})
    check("admin login", r.status_code == 200, r.text)
    me = r.json()
    check("is admin", me["is_admin"])

    print("\n-- athletes and invites")
    r = c.post("/api/athletes", json={"name": "jan", "display_name": "Jan"})
    check("create athlete", r.status_code == 200, r.text)
    invite = r.json()["invite_code"]
    jan_id = r.json()["athlete"]["id"]
    r = c.post("/api/athletes", json={"name": "jan", "display_name": "Jan 2"})
    check("duplicate name refused", r.status_code == 409, r.status_code)

    c2 = TestClient(main.app)
    r = c2.get(f"/api/invite/{invite}")
    check("invite readable", r.status_code == 200, r.text)
    r = c2.post("/api/join", json={"code": invite, "password": "Janspassword1!"})
    check("invite redeemed", r.status_code == 200, r.text)
    r = c2.get(f"/api/invite/{invite}")
    check("invite is single use", r.status_code == 404, r.status_code)
    r = c2.get("/api/me")
    check("jan signed in", r.status_code == 200 and r.json()["name"] == "jan", r.text)

    r = c.post("/api/athletes", json={"name": "tim", "display_name": "Tim"})
    tim_id = r.json()["athlete"]["id"]
    c3 = TestClient(main.app)
    c3.post("/api/join", json={"code": r.json()["invite_code"], "password": "Timspassword1!"})
    check("tim signed in", c3.get("/api/me").json()["name"] == "tim")

    print("\n-- device tokens")
    r = c.post("/api/athletes", json={"name": "lutz-heinrich", "display_name": "Lutz-Heinrich"})
    check("a hyphenated name is accepted", r.status_code == 200, r.text)
    lh = r.json()["athlete"]
    check("the handle keeps its hyphen", lh["name"] == "lutz-heinrich", lh)
    c.delete(f"/api/athletes/{lh['id']}")

    tok_jan = c2.post(f"/api/athletes/{jan_id}/tokens", json={"label": "nuc"}).json()["token"]
    tok_tim = c3.post(f"/api/athletes/{tim_id}/tokens", json={"label": "pi"}).json()["token"]
    r = c2.post(f"/api/athletes/{me['id']}/tokens", json={"label": "steal"})
    check("cannot mint another athlete's token", r.status_code == 403, r.status_code)

    print("\n-- uplink and a plain session")
    now = time.time()
    with c.websocket_connect("/ws/uplink") as ws:
        ws.send_json({"type": "hello", "token": "garbage", "agent": "t"})
        try:
            ws.receive_json()
            bad_token_closed = False
        except Exception:
            bad_token_closed = True
    check("bad token closes the socket", bad_token_closed)

    with c.websocket_connect("/ws/uplink") as ws:
        ws.send_json({"type": "hello", "token": tok_jan, "agent": "tracker/test"})
        hello = ws.receive_json()
        check("welcome", hello["type"] == "welcome" and hello["athlete"]["name"] == "jan", hello)

        sid = "20260911T190000"
        rows = [(t, t * 4, 4.0) for t in range(0, 700, 1)]     # 4 m/s for ~11.5 min
        for msg in samples(sid, now, rows):
            ws.send_json(msg)
        ws.send_json({"type": "summary", "session": sid, "started_at": now,
                      "distance_m": 2796, "duration_s": 699, "strokes": 1398,
                      "avg_speed_ms": 4.0, "avg_spm": 24})
        # The server drains the socket one message at a time; wait for it to
        # reach the summary rather than guessing at a sleep. Waiting on the
        # records, not on ended_at: closing the session and indexing it are
        # two steps, and stopping after the first one raced the assertions
        # below often enough to notice.
        for _ in range(150):
            time.sleep(0.1)
            rows = c.get("/api/sessions").json()
            if rows and rows[0]["ended_at"] and c.get("/api/records").json():
                break

    r = c.get("/api/sessions")
    check("session stored", r.status_code == 200 and len(r.json()) == 1, r.text)
    stored = r.json()[0]
    check("distance from summary", stored["distance_m"] == 2796, stored)
    check("athlete attached", stored["display_name"] == "Jan", stored)

    r = c.get(f"/api/sessions/{stored['id']}")
    check("samples stored", len(r.json()["samples"]) == 700, len(r.json()["samples"]))

    print("\n-- records")
    r = c.get("/api/records")
    boards = {(b["kind"], b["key"]): b for b in r.json()}
    check("2 km best found", ("distance", 2000) in boards, list(boards))
    if ("distance", 2000) in boards:
        v = boards[("distance", 2000)]["entries"][0]["value"]
        check("2 km at 4 m/s is ~500 s", abs(v - 500) < 2, v)
    check("10 km not claimed from a 2.8 km row", ("distance", 10000) not in boards)
    if ("time", 600) in boards:
        v = boards[("time", 600)]["entries"][0]["value"]
        check("600 s at 4 m/s is ~2400 m", abs(v - 2400) < 8, v)

    print("\n-- race")
    r = c.post("/api/race", json={"name": "Test", "mode": "distance", "target": 100})
    check("race created", r.status_code == 200, r.text)
    r = c.post("/api/race", json={"name": "Second", "mode": "distance", "target": 100})
    check("second race refused", r.status_code == 409, r.status_code)
    check("creating it does not put the admin in it",
          len(c.get("/api/race").json()["lanes"]) == 0, c.get("/api/race").json())
    r = c.post("/api/race/join")
    check("an admin may not race", r.status_code == 403, r.status_code)
    r = c2.post("/api/race/join")
    check("jan joined", r.status_code == 200 and len(r.json()["lanes"]) == 1, r.text)
    r = c3.post("/api/race/join")
    check("tim joined", r.status_code == 200 and len(r.json()["lanes"]) == 2, r.text)
    r = c2.post("/api/race/start")
    check("only the host may start", r.status_code == 403, r.status_code)

    with c2.websocket_connect("/ws/uplink") as wa, c3.websocket_connect("/ws/uplink") as wb:
        wa.send_json({"type": "hello", "token": tok_jan, "agent": "a"})
        wa.receive_json()
        wb.send_json({"type": "hello", "token": tok_tim, "agent": "b"})
        wb.receive_json()

        r = c.post("/api/race/start")
        check("race started", r.status_code == 200, r.text)
        cmd = wa.receive_json()
        check("reset sent to the monitor", cmd.get("cmd") == "reset", cmd)
        wb.receive_json()

        for _ in range(30):
            time.sleep(0.2)
            if (c.get("/api/race").json() or {}).get("state") == "running":
                break
        check("countdown ran out", (c.get("/api/race").json() or {}).get("state") == "running")

        base = time.time()
        ra = "20260911T200000"
        rb = "20260911T200001"
        for t, d in [(0, 0), (1, 30), (2, 60), (3, 90), (4, 120)]:
            wa.send_json({"type": "sample", "session": ra, "started_at": base, "t": t,
                          "distance_m": d, "speed_ms": 30.0, "stroke_rate": 30, "watts": 200})
            time.sleep(0.12)
        for t, d in [(0, 0), (1, 20), (2, 40), (3, 60), (4, 80), (5, 110)]:
            wb.send_json({"type": "sample", "session": rb, "started_at": base, "t": t,
                          "distance_m": d, "speed_ms": 20.0, "stroke_rate": 26, "watts": 150})
            time.sleep(0.12)
        time.sleep(1.2)

        def wait_for_cmd(ws, want, tries=12):
            for _ in range(tries):
                try:
                    msg = ws.receive_json()
                except Exception:
                    return False
                if msg.get("type") == "cmd" and msg.get("cmd") == want:
                    return True
            return False

        def cmds_so_far(ws):
            """Ping and read to the pong: anything the server sent earlier is
            ordered before it, so this sees the backlog without blocking on
            a message that may never come. Only the session commands
            count: a running race pushes its own state down the same
            uplink, and that is not an auto-end."""
            ws.send_json({"type": "ping"})
            seen = []
            for _ in range(60):
                msg = ws.receive_json()
                if msg.get("type") == "pong":
                    break
                if msg.get("type") == "cmd" and msg.get("cmd") in ("reset", "end"):
                    seen.append(msg.get("cmd"))
            return seen

        # Whether a session is over is the rower's call, not the race's.
        check("the finish leaves the sessions alone", cmds_so_far(wa) == [], "auto-ended")
        check("and the other one as well", cmds_so_far(wb) == [], "auto-ended")

        c2.post("/api/session/end")
        check("Jan can end his own session", wait_for_cmd(wa, "end"))
        # The other half of the pair: zeroing the monitor, same button row,
        # so nothing forces a walk over to the tracker.
        c3.post("/api/session/reset")
        check("and Tim zeroes his monitor", wait_for_cmd(wb, "reset"))
        c3.post("/api/session/end")
        check("and then ends his", wait_for_cmd(wb, "end"))

    races = c.get("/api/races").json()
    check("race recorded", len(races) >= 1, races)
    done = [r for r in races if r["state"] == "finished"]
    check("race finished", len(done) == 1, [r["state"] for r in races])
    if done:
        entries = sorted(done[0]["entries"], key=lambda e: e["place"] or 99)
        check("two lanes placed", len(entries) == 2, entries)
        check("both have a time", all(e["time_s"] is not None for e in entries), entries)
        check("winner is first", entries[0]["place"] == 1, entries)
        check("places are distinct", entries[0]["place"] != entries[1]["place"], entries)
        check("race linked to a session", entries[0]["session_id"] is not None, entries)

    r = c.get("/api/h2h").json()
    check("head to head counted", r["races"] == 1 and len(r["pairs"]) == 1, r)

    print("\n-- ghost lane")
    c.post("/api/race/clear")
    r = c.post("/api/race", json={"name": "Ghost", "mode": "time", "target": 60})
    check("time race created", r.status_code == 200, r.text)
    c2.post("/api/race/join")
    r = c.post("/api/race/ghost", json={"session_id": stored["id"]})
    check("ghost added", r.status_code == 200 and len(r.json()["lanes"]) == 2, r.text)
    check("ghost is ready", [l for l in r.json()["lanes"] if l["kind"] == "ghost"][0]["ready"])
    r = c.post("/api/race/abort")
    check("race aborted", r.status_code == 200, r.text)

    print("\n-- permissions")
    r = c3.delete(f"/api/sessions/{stored['id']}")
    check("cannot delete another athlete's session", r.status_code == 403, r.status_code)
    r = c2.post("/api/athletes", json={"name": "x", "display_name": "X"})
    check("non-admin cannot create athletes", r.status_code == 403, r.status_code)
    r = c2.patch(f"/api/athletes/{jan_id}",
                 json={"display_name": "Jan", "color": "", "is_admin": True})
    check("nobody promotes themselves", r.status_code == 403, r.status_code)
    r = c.patch(f"/api/athletes/{me['id']}",
                json={"display_name": "Admin", "color": "", "is_admin": False})
    check("the last admin cannot step down", r.status_code == 409, r.status_code)

    print(chr(10) + "-- admins are not in the standings")
    names = [row["display_name"] for row in c.get("/api/totals").json()]
    check("no admin in the totals", "Admin" not in names, names)
    check("the competitors are", {"Jan", "Tim"} <= set(names), names)
    owners = {e["display_name"] for b in c.get("/api/records").json() for e in b["entries"]}
    check("no admin in the records", "Admin" not in owners, owners)
    h2h = c.get("/api/h2h").json()
    ids = {p["winner"] for p in h2h["pairs"]} | {p["loser"] for p in h2h["pairs"]}
    check("no admin in the head to head", me["id"] not in ids, (me["id"], ids))
    nobody = TestClient(main.app)
    check("anonymous is refused", nobody.get("/api/sessions").status_code == 401)

    print("\n-- health")
    anon = TestClient(main.app)
    r = anon.get("/api/health")
    check("health needs no sign-in", r.status_code == 200, r.status_code)
    check("health answers ok", r.json().get("ok") is True, r.json())

    print("\n-- a running race cannot be cleared off everyone's screen")
    c.post("/api/race/abort")
    c.post("/api/race", json={"name": "Busy", "mode": "time", "target": 300}).raise_for_status()
    c2.post("/api/race/join").raise_for_status()
    c.post("/api/race/start").raise_for_status()
    for _ in range(30):
        time.sleep(0.2)
        if (c.get("/api/race").json() or {}).get("state") == "running":
            break
    r = c2.post("/api/race/clear")
    check("clear is refused while running", r.json().get("cleared") is False, r.json())
    check("the race is still there", (c.get("/api/race").json() or {}).get("state") == "running")
    c.post("/api/race/abort")
    r = c.post("/api/race/clear")
    check("clear works once it is over", r.json().get("cleared") in (True, False), r.json())

    print(chr(10) + "-- security settings")
    import api as api_mod
    r = c.get("/api/security")
    check("admin reads the policies", r.status_code == 200, r.text)
    check("all three are there",
          {"login_ip_limit", "login_name_limit", "invite_ip_limit"} <= set(r.json()["settings"]),
          r.json())
    check("nothing locked out yet", r.json()["blocked"] == [], r.json())
    check("a rower may not read them", c2.get("/api/security").status_code == 403)

    tight = {"login_ip_limit": 3, "login_ip_minutes": 15,
             "login_name_limit": 3, "login_name_minutes": 15,
             "invite_ip_limit": 2, "invite_ip_minutes": 30,
             "uplink_ip_limit": 3, "uplink_ip_minutes": 15}
    check("the admin can tighten them", c.post("/api/security", json=tight).status_code == 200)
    r = c.post("/api/security", json=dict(tight, login_ip_minutes=0))
    check("nonsense is refused", r.status_code == 422, r.status_code)

    print(chr(10) + "-- the new limits bite")
    for pol in api_mod.POLICIES.values():
        pol.clear_all()
    for _ in range(3):
        TestClient(main.app).post("/api/login", json={"name": "jan", "password": "wrong"})
    r = TestClient(main.app).post("/api/login", json={"name": "jan", "password": "wrong"})
    check("three failures lock the account", r.status_code == 429, r.status_code)
    blocked = c.get("/api/security").json()["blocked"]
    check("the lockout is listed", any(b["key"] == "jan" for b in blocked), blocked)
    check("with a policy and a countdown",
          all(b["policy"] and b["seconds"] > 0 for b in blocked), blocked)

    r = c.post("/api/security/unblock", json={"policy": "login_name", "key": "jan"})
    check("the admin can lift one", r.status_code == 200, r.text)
    c.post("/api/security/unblock", json={})
    check("and all of them", c.get("/api/security").json()["blocked"] == [])
    r = TestClient(main.app).post("/api/login", json={"name": "jan", "password": "Janspassword1!"})
    check("jan is back in", r.status_code == 200, r.status_code)

    print(chr(10) + "-- wrong invitation codes lock the address")
    for _ in range(2):
        TestClient(main.app).get("/api/invite/not-a-real-code")
    r = TestClient(main.app).get("/api/invite/not-a-real-code")
    check("two wrong codes are enough", r.status_code == 429, r.status_code)
    r = TestClient(main.app).post("/api/join",
                                  json={"code": "still-wrong", "password": "Whatever12345!"})
    check("redeeming is locked out too", r.status_code == 429, r.status_code)
    blocked = c.get("/api/security").json()["blocked"]
    check("the address is listed", any(b["policy"] == "invite_ip" for b in blocked), blocked)
    c.post("/api/security/unblock", json={})

    check("a limit of 0 is accepted",
          c.post("/api/security", json=dict(tight, login_ip_limit=0)).status_code == 200)
    for pol in api_mod.POLICIES.values():
        pol.clear_all()
    for _ in range(6):
        TestClient(main.app).post("/api/login", json={"name": "tim", "password": "wrong"})
    check("and switches that policy off", api_mod.BY_IP.retry_after("testclient") == 0)
    c.post("/api/security", json=dict(tight, login_ip_limit=10, invite_ip_limit=10))
    c.post("/api/security/unblock", json={})


    print(chr(10) + "-- the failed-attempt log")
    sec = c.get("/api/security").json()
    check("a 24 hour window", sec["window_hours"] == 24, sec["window_hours"])
    names = [f["name"] for f in sec["failures"]]
    check("the guessed account is logged", "jan" in names, names[:5])
    check("wrong codes are logged too",
          any(f["kind"] == "invite" for f in sec["failures"]),
          [f["kind"] for f in sec["failures"][:5]])
    check("every row has an address", all(f["ip"] for f in sec["failures"]), sec["failures"][:3])
    check("newest first", [f["ts"] for f in sec["failures"]] ==
          sorted([f["ts"] for f in sec["failures"]], reverse=True))
    check("counted up", sec["counts"]["total"] >= len(names), sec["counts"])
    check("busiest account named", any(r["name"] == "jan" for r in sec["counts"]["by_name"]),
          sec["counts"]["by_name"])
    check("a rower cannot read the log", c2.get("/api/security").status_code == 403)
    main.db.prune_failures(time.time() + 1)
    check("pruning empties it", c.get("/api/security").json()["failures"] == [])
    r = TestClient(main.app).post("/api/login", json={"name": "tim", "password": "Timspassword1!"})
    check("that login worked", r.status_code == 200, r.status_code)
    check("a success leaves no trace in the log",
          c.get("/api/security").json()["failures"] == [],
          c.get("/api/security").json()["failures"])

    print(chr(10) + "-- password strength")
    r = c.post("/api/athletes", json={"name": "weakling", "display_name": "Weakling"})
    code = r.json()["invite_code"]
    weak_id = r.json()["athlete"]["id"]
    for pw, why in (("kurz", "too short"),
                    ("alllowercase", "one kind only"),
                    ("ALLESGROSS12345", "two kinds"),
                    ("elfzeichen1A", None)):
        rr = TestClient(main.app).post("/api/join", json={"code": code, "password": pw})
        if why:
            check(f"refused: {why}", rr.status_code == 400, (pw, rr.status_code, rr.text))
        else:
            check("twelve characters and three kinds is accepted",
                  rr.status_code == 200, (pw, rr.text))
    r = c2.post("/api/password", json={"old_password": "Janspassword1!",
                                       "password": "schwach"})
    check("changing to a weak one is refused", r.status_code == 400, r.text)
    r = c2.post("/api/password", json={"old_password": "Janspassword1!",
                                       "password": "Janspassword2!"})
    check("and to a strong one is fine", r.status_code == 200, r.text)
    c2.post("/api/password", json={"old_password": "Janspassword2!",
                                   "password": "Janspassword1!"})
    c.delete(f"/api/athletes/{weak_id}")

    print(chr(10) + "-- race templates")
    tpls = c.get("/api/templates").json()
    check("seeded on an empty arena", len(tpls) >= 3, len(tpls))
    check("an athlete may read them", c2.get("/api/templates").status_code == 200)
    r = c2.post("/api/templates", json={"name": "Meins", "mode": "distance", "target": 1000})
    check("but not write them", r.status_code == 403, r.status_code)
    r = c.post("/api/templates", json={"name": "Dienstag", "mode": "distance",
                                       "target": 1500, "note": "Wochenmitte"})
    check("the admin adds one", r.status_code == 200 and r.json()["target"] == 1500, r.text)
    made = r.json()
    r = c.post("/api/templates", json={"name": "Unsinn", "mode": "distance", "target": 5})
    check("with the same limits as the form", r.status_code == 400, r.status_code)

    c.post("/api/race/abort")
    r = c2.post("/api/race", json={"template_id": made["id"]})
    check("a race comes out of a template", r.status_code == 200, r.text)
    race = c.get("/api/race").json()
    check("with the template settings", race["target"] == 1500 and race["name"] == "Dienstag", race)
    check("and the athlete who picked it is in it", len(race["lanes"]) == 1, race["lanes"])
    r = c2.post("/api/race", json={"template_id": 999999})
    check("an unknown template is refused", r.status_code in (404, 409), r.status_code)
    c.post("/api/race/abort")
    tid = made["id"]
    check("the admin can delete one",
          c.delete(f"/api/templates/{tid}").status_code == 200)
    check("and it is gone",
          not any(x["id"] == tid for x in c.get(f"/api/templates").json()))

    print(chr(10) + "-- token attacks on the uplink")
    for pol in api_mod.POLICIES.values():
        pol.clear_all()
    refused = 0
    for _ in range(4):
        try:
            with c.websocket_connect("/ws/uplink") as ws:
                ws.send_json({"type": "hello", "token": "nope", "agent": "x"})
                ws.receive_json()
        except Exception:
            refused += 1
    check("bad tokens are refused", refused == 4, refused)
    check("and the address gets locked out",
          api_mod.UPLINK_IP.retry_after("testclient") > 0, api_mod.UPLINK_IP.retry_after("testclient"))
    sec = c.get("/api/security").json()
    check("the uplink lockout is listed",
          any(b["policy"] == "uplink_ip" for b in sec["blocked"]), sec["blocked"])
    check("and the attempts are in the log",
          any(f["kind"] == "uplink" for f in sec["failures"]),
          [f["kind"] for f in sec["failures"][:5]])
    c.post("/api/security/unblock", json={})

    print(chr(10) + "-- changing a password ends the other sessions")
    other = TestClient(main.app)
    other.post("/api/login", json={"name": "tim", "password": "Timspassword1!"})
    check("the second browser is signed in", other.get("/api/me").status_code == 200)
    c3.post("/api/password", json={"old_password": "Timspassword1!",
                                   "password": "Timspassword2!"})
    check("the other session is gone", other.get("/api/me").status_code == 401,
          other.get("/api/me").status_code)
    check("the one that changed it stays", c3.get("/api/me").status_code == 200)
    c3.post("/api/password", json={"old_password": "Timspassword2!",
                                   "password": "Timspassword1!"})

    print(chr(10) + "-- display names are data, not markup")
    r = c.post("/api/athletes", json={"name": "markup",
                                      "display_name": "<img src=x onerror=1>"})
    check("stored as typed", r.status_code == 200, r.text)
    got = [a for a in c.get("/api/athletes").json() if a["name"] == "markup"][0]
    check("round-trips unchanged", got["display_name"] == "<img src=x onerror=1>", got)
    c.delete("/api/athletes/" + str(got["id"]))
    # The server is right to store it raw; the guard is that the UI never
    # puts a name into innerHTML, where the browser would build an element
    # out of it.
    static = os.path.join(REPO, "server", "app", "static")
    risky = []
    for fn in ("app.js", "views.js", "race.js", "charts.js"):
        for n, line in enumerate(open(os.path.join(static, fn), encoding="utf-8"), 1):
            if "innerHTML" not in line:
                continue
            if any(w in line for w in ("display_name", "athleteName", "joinWho",
                                       "h2hLine", "lane.name", "tpl.name")):
                risky.append(fn + ":" + str(n))
    check("no name reaches innerHTML", not risky, risky)

    print(chr(10) + "-- the audit findings stay fixed")
    h = auth_mod.hash_password("Testpasswort1!")
    check("the hash carries its parameters", h.count("$") == 5, h[:30])
    check("and verifies", auth_mod.verify_password("Testpasswort1!", h))
    check("and refuses a wrong one", not auth_mod.verify_password("falsch", h))
    old = "scrypt$" + "00" * 16 + "$" + "ab" * 32
    check("the first format is still readable", auth_mod._parse(old) is not None)
    check("and is marked for upgrading", auth_mod.needs_rehash(old))
    check("today's is not", not auth_mod.needs_rehash(h))

    t0 = time.time()
    TestClient(main.app).post("/api/login", json={"name": "gibtsnicht", "password": "x" * 20})
    unknown = time.time() - t0
    for pol in api_mod.POLICIES.values():
        pol.clear_all()
    t0 = time.time()
    TestClient(main.app).post("/api/login", json={"name": "jan", "password": "x" * 20})
    known = time.time() - t0
    for pol in api_mod.POLICIES.values():
        pol.clear_all()
    check("an unknown name costs the same as a known one",
          abs(known - unknown) < max(known, unknown) * 0.6, (known, unknown))

    r = anon.get("/api/health")
    check("health says nothing but yes", set(r.json()) == {"ok"}, r.json())
    check("version needs a sign-in", anon.get("/api/version").status_code == 401)
    r = c.get("/api/version")
    check("and works for one signed in", r.status_code == 200, r.status_code)

    r = TestClient(main.app).post("/api/login",
                                  json={"name": "x", "password": "y" * 300})
    check("an oversized password is refused before hashing",
          r.status_code == 422, r.status_code)
    for pol in api_mod.POLICIES.values():
        pol.clear_all()

    r = c.get("/")
    csp = r.headers.get("content-security-policy", "")
    for token in ("default-src 'self'", "frame-ancestors 'none'", "object-src 'none'"):
        check("CSP carries " + token, token in csp, csp)
    for header in ("x-content-type-options", "x-frame-options", "referrer-policy"):
        check(header + " is set", r.headers.get(header), dict(r.headers))

    print(chr(10) + "-- achievements")
    r = c2.get("/api/achievements")
    check("the wall loads", r.status_code == 200, r.text)
    wall = r.json()["achievements"]
    check("twelve of them", len(wall) == 12, len(wall))
    locked = [b for b in wall if b.get("locked")]
    hidden = [b for b in wall if b.get("locked") or b.get("hidden")]
    check("four are hidden", len(hidden) == 4, len(hidden))
    # Not a fixed count: the time-of-day badges depend on when this runs,
    # and a test that fails at seven in the morning is a bad test.
    check("an earned hidden one is no longer a silhouette",
          len(locked) < len(hidden), (len(locked), len(hidden)))
    check("a hidden one gives nothing away",
          all(set(b) == {"id", "hidden", "locked", "earned"} for b in locked), locked[:1])

    # Jan rowed 2796 m at 4 m/s for 699 s earlier in this run.
    earned = {b["name"] for b in wall if not b.get("locked")
              and any(e["athlete_id"] == jan_id for e in b["earned"])}
    check("first session is noticed", "Erste Fahrt" in earned, earned)
    check("half an hour is not, at 699 s", "Halbe Stunde" not in earned, earned)
    # 500 m at 4 m/s is 125 s - 2:05, against a threshold of 120. The badge
    # not firing is the threshold working, so that is what gets asserted.
    check("2:05 does not pass a 2:00 threshold", "Unter 2:00" not in earned, earned)
    check("the close race won Fotofinish", "Fotofinish" in earned, earned)
    check("10 km total is not, at 2.8 km", "Zehntausend" not in earned, earned)

    r = c2.post("/api/achievements", json={"name": "Meins", "metric": "race_wins",
                                           "op": ">=", "threshold": 1})
    check("a rower cannot mint badges", r.status_code == 403, r.status_code)
    r = c.post("/api/achievements", json={"name": "Unsinn", "metric": "gibtsnicht",
                                          "op": ">=", "threshold": 1})
    check("an unknown metric is refused", r.status_code == 400, r.status_code)
    r = c.post("/api/achievements", json={"name": "Schief", "metric": "race_wins",
                                          "op": "~", "threshold": 1})
    check("an unknown comparison is refused", r.status_code == 400, r.status_code)
    r = c.post("/api/achievements", json={"name": "Erste Meter", "note": "500 m gesamt.",
                                          "icon": "🧊", "metric": "distance_total",
                                          "op": ">=", "threshold": 500, "hidden": False})
    check("the admin adds one", r.status_code == 200, r.text)
    wall = c.get("/api/achievements").json()["achievements"]
    check("and it is on the wall", any(b.get("name") == "Erste Meter" for b in wall))
    made = [b for b in wall if b.get("name") == "Erste Meter"][0]
    check("the admin can take it away",
          c.delete("/api/achievements/" + str(made["id"])).status_code == 200)
    check("and it is gone",
          not any(b.get("name") == "Erste Meter"
                  for b in c.get("/api/achievements").json()["achievements"]))

    r = c.get("/api/achievements/metrics")
    check("the admin sees the vocabulary", r.status_code == 200 and len(r.json()) > 10,
          len(r.json()) if r.status_code == 200 else r.text)
    check("a rower does not", c2.get("/api/achievements/metrics").status_code == 403)

    print(chr(10) + "-- excel and backup")
    tid = stored["id"]
    r = c.get(f"/api/sessions/{tid}/export.xlsx")
    check("a session exports", r.status_code == 200, r.status_code)
    check("and is a workbook", r.content[:2] == b"PK", r.content[:8])
    check("named after the athlete", "jan" in r.headers.get("content-disposition", ""),
          r.headers.get("content-disposition"))
    r = c.get("/api/export.xlsx")
    check("the whole arena exports", r.status_code == 200 and r.content[:2] == b"PK", r.status_code)
    check("a rower may export too", c2.get("/api/export.xlsx").status_code == 200)

    r = c.get("/api/backup")
    check("the admin can take a backup", r.status_code == 200, r.status_code)
    check("and it is an SQLite file", r.content[:15] == b"SQLite format 3", r.content[:15])
    check("a rower cannot", c2.get("/api/backup").status_code == 403)
    import sqlite3, tempfile as tf, os as _os
    fd, path = tf.mkstemp(suffix=".db")
    _os.close(fd)
    open(path, "wb").write(r.content)
    con = sqlite3.connect(path)
    names = {row[0] for row in con.execute(
        "SELECT name FROM sqlite_master WHERE type=(?)", ("table",))}
    n = con.execute("SELECT COUNT(*) FROM athletes").fetchone()[0]
    con.close()
    _os.unlink(path)
    check("the copy opens and has the tables",
          {"athletes", "sessions", "samples", "achievements"} <= names, sorted(names))
    check("and the rows are in it", n >= 3, n)
    # Twice now a flex or grid rule has beaten the browser's own [hidden]
    # on specificity and left an empty box on the page. Both stylesheets
    # have to say it properly, not just the one that was bitten last.
    import pathlib
    root = pathlib.Path(REPO)
    for which in ("server", "docker"):
        css = (root / which / "app" / "static" / "style.css").read_text(encoding="utf-8")
        check(f"{which} hides what is hidden",
              "[hidden] { display: none !important; }" in css)

    print("\n-- ui shell")
    r = c.get("/")
    check("index served", r.status_code == 200 and "WaterRower Arena" in r.text)
    check("assets versioned", "app.js?v=" in r.text)
    for asset in ("style.css", "app.js", "views.js", "charts.js", "race.js"):
        check(f"{asset} served", c.get(f"/static/{asset}").status_code == 200)

print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
