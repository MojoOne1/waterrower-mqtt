# Tests

Three suites, no framework. Each one prints a line per check and exits
non-zero if any failed, which is all a project this size needs.

```bash
python -m pip install -r ../server/requirements.txt -r ../docker/requirements.txt httpx pyyaml
python run_all.py
```

| Suite | What it covers | Needs |
|---|---|---|
| `smoke.py` | The arena, in-process through FastAPI's test client: sign-in and lockouts, uplink ingest, races and ghosts, records, badges, exports, backup, the admin panel | nothing outside the checkout |
| `integration.py` | The tracker's real uplink client against a real arena in a subprocess: backfill, live samples, the race reaching the machine, reconnects | a free port (8791) |
| `tracker_api.py` | The tracker's own HTTP API in a subprocess, mostly the Firmware card - what it offers, what it writes, and the names it refuses | free ports (8821-8822) |

Two things they deliberately do not do:

- **Reach the network.** `tracker_api.py` checks that a plain-http firmware
  URL is refused, but never fetches from GitHub: a test that needs
  github.com to answer fails for reasons that have nothing to do with the
  code.
- **Flash anything, or race two real people.** See the note at the top of
  the main README.
