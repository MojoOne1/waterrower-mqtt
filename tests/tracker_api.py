"""The tracker's own HTTP API, against a real server in a subprocess.

The uplink suite covers the road to the arena; this one covers what the
tracker answers on its own port. It exists because the Firmware card
writes files into a directory shared with another container, and that is
not something to leave on manual checks.

No broker is running, so anything that needs MQTT reports 503 - which is
itself worth asserting.
"""
import io
import json
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
PORT = 8821

ok = fail = 0


def check(label, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ok   {label}")
    else:
        fail += 1
        print(f"  FAIL {label} {extra}")


tmp = tempfile.mkdtemp()
esphome_dir = os.path.join(tmp, "esphome-data")
os.makedirs(esphome_dir)
env = dict(os.environ,
           DB_PATH=os.path.join(tmp, "tracker.db"),
           ESPHOME_CONFIG=esphome_dir,
           APP_VERSION="9.9.9-test",
           PYTHONUNBUFFERED="1")
LOG = open(os.path.join(tmp, "server.log"), "w+")
server = subprocess.Popen(
    [PY, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(PORT),
     "--log-level", "warning"],
    cwd=os.path.join(REPO, "docker", "app"), env=env,
    stdout=LOG, stderr=subprocess.STDOUT)

base = f"http://127.0.0.1:{PORT}"
c = httpx.Client(base_url=base, timeout=20)

try:
    up = False
    for _ in range(120):
        try:
            if c.get("/api/version").status_code == 200:
                up = True
                break
        except Exception:
            pass
        time.sleep(0.3)
    if not up:
        LOG.seek(0)
        print(LOG.read())
        raise SystemExit("tracker did not start")

    print("\n-- the tracker is up")
    check("version answers", c.get("/api/version").json()["version"] == "9.9.9-test")
    check("the page is served", c.get("/").status_code == 200)

    print("\n-- no broker, and it says so instead of pretending")
    check("ending a session needs one", c.post("/api/session/end").status_code == 503)
    check("zeroing the monitor too", c.post("/api/session/reset").status_code == 503)

    print("\n-- the firmware card")
    f = c.get("/api/firmware").json()
    check("it knows what this build ships", f["expected"] == "9.9.9-test", f)
    check("nothing is running yet", f["running"] == "", f)
    check("the folder is writable", f["config_dir_ok"] is True, f)
    kinds = [x["kind"] for x in f["configs"]]
    check("the shipped YAML is offered", "shipped" in kinds, kinds)
    check("and so is GitHub", "github" in kinds, kinds)
    check("listing costs no fetch", f["configs"][1]["version"] == "",
          f["configs"][1])

    check("the dashboard address is saved",
          c.post("/api/firmware", json={"esphome_url": "http://10.0.0.5:6052/"})
          .json()["url"] == "http://10.0.0.5:6052")

    r = c.get("/api/firmware/yaml?source=shipped")
    check("the shipped YAML downloads", r.status_code == 200, r.status_code)
    check("and it is the firmware", "esphome:" in r.text and "substitutions:" in r.text)

    print("\n-- installing into the shared folder")
    r = c.post("/api/firmware/yaml", json={"source": "shipped", "name": "waterrower.yaml"})
    check("the shipped one installs", r.status_code == 200, r.text[:120])
    check("the file is really there",
          os.path.isfile(os.path.join(esphome_dir, "waterrower.yaml")))
    check("it reports what it wrote", (r.json().get("wrote") or {}).get("name") == "waterrower.yaml",
          r.json().get("wrote"))
    names = [x["name"] for x in r.json()["configs"]]
    check("and the list picked it up", names.count("waterrower.yaml") >= 2, names)

    r = c.post("/api/firmware/yaml", json={"source": "shipped", "name": "waterrower.yaml"})
    check("an existing file is not clobbered", r.status_code == 409, r.status_code)
    r = c.post("/api/firmware/yaml",
               json={"source": "shipped", "name": "waterrower.yaml", "overwrite": True})
    check("unless you say so", r.status_code == 200, r.status_code)

    r = c.post("/api/firmware/yaml",
               json={"source": "upload", "name": "mine.yaml",
                     "content": "substitutions:\n  version: \"1.2.3\"\nesphome:\n  name: x\n"})
    check("an uploaded YAML lands", r.status_code == 200, r.text[:120])
    mine = [x for x in r.json()["configs"] if x["name"] == "mine.yaml"]
    check("with the version it declares", mine and mine[0]["version"] == "1.2.3", mine)

    print("\n-- names are names")
    # Everything here writes into a directory another container compiles
    # from, so a name may not be a path, a dot-file, a non-YAML, or the
    # dashboard's own secrets file.
    for label, name in [("a path upwards", "../escaped.yaml"),
                        ("an absolute path", "C:/Windows/evil.yaml"),
                        ("a backslash path", ".." + chr(92) + "evil.yaml"),
                        ("a nested path", "sub/dir.yaml"),
                        ("a dot-file", ".hidden.yaml"),
                        ("something that is not YAML", "payload.py"),
                        ("the dashboard's secrets", "secrets.yaml")]:
        r = c.post("/api/firmware/yaml", json={"source": "shipped", "name": name})
        check(f"refused: {label}", r.status_code == 400, f"{r.status_code} {r.text[:70]}")

    r = c.post("/api/firmware/yaml",
               json={"source": "upload", "name": "big.yaml", "content": "x" * 600000})
    check("refused: an oversized upload", r.status_code == 413, r.status_code)

    r = c.get("/api/firmware/yaml?source=../../../etc/passwd")
    check("refused: a path in a download", r.status_code == 400, r.status_code)

    leaked = sorted(n for n in os.listdir(tmp) if n.endswith((".yaml", ".yml")))
    check("nothing escaped the folder", leaked == [], leaked)
    left = sorted(os.listdir(esphome_dir))
    check("and only what was asked for is in it",
          left == ["mine.yaml", "waterrower.yaml"], left)

    print("\n-- fetching from GitHub is held to the same standard")
    # The live fetch is not exercised here on purpose: a test that needs
    # github.com to answer fails for reasons that have nothing to do with
    # the code. The guard that costs nothing to check is checked.
    server2 = subprocess.Popen(
        [PY, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(PORT + 1),
         "--log-level", "warning"],
        cwd=os.path.join(REPO, "docker", "app"),
        env=dict(env, DB_PATH=os.path.join(tmp, "t2.db"),
                 FIRMWARE_YAML_URL="http://example.com/waterrower.yaml"),
        stdout=LOG, stderr=subprocess.STDOUT)
    try:
        c2 = httpx.Client(base_url=f"http://127.0.0.1:{PORT + 1}", timeout=20)
        for _ in range(120):
            try:
                if c2.get("/api/version").status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.3)
        r = c2.get("/api/firmware/yaml?source=github")
        check("plain http is refused", r.status_code == 400, f"{r.status_code} {r.text[:70]}")
    finally:
        server2.terminate()

finally:
    server.terminate()

print(f"\n{ok} passed, {fail} failed")
raise SystemExit(1 if fail else 0)
