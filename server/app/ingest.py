"""The uplink endpoint: one WebSocket per tracker.

A tracker authenticates once with its device token, then streams the same
samples it writes into its own database. Nothing here trusts the client's
clock beyond the session's own elapsed seconds; the race clock is the
server's (see race.py).

Messages from the tracker

    hello     {token, agent, firmware}
    sample    {session, started_at, t, distance_m, speed_ms, stroke_rate,
               strokes, watts}
    summary   {session, distance_m, duration_s, strokes, avg_speed_ms, avg_spm}
    backfill  {session, started_at, ended_at, summary, samples: [...]}
    sync      {}                      asks which sessions the arena already has
    pong      {}

Messages to the tracker

    welcome   {athlete, server_time, known}
    cmd       {cmd: "reset", race_id}  zero the monitor before the gun
    ack       {session, stored}
    ping      {}
"""

import asyncio
import logging
import time

from fastapi import WebSocket, WebSocketDisconnect

import auth
import records
from hub import Uplink

log = logging.getLogger("ingest")

PING_S = 20          # Cloudflare drops an idle tunnel; this keeps it warm
MAX_BACKFILL_ROWS = 20000


async def uplink_endpoint(websocket: WebSocket, db, hub) -> None:
    await websocket.accept()
    athlete = None
    uplink = None
    pinger = None
    try:
        hello = await asyncio.wait_for(websocket.receive_json(), timeout=15)
        if hello.get("type") != "hello" or not hello.get("token"):
            await websocket.close(code=4401, reason="hello expected")
            return
        owner = await asyncio.to_thread(db.token_owner, auth.token_hash(hello["token"]))
        if not owner:
            await websocket.close(code=4403, reason="unknown token")
            log.warning("Uplink rejected: unknown token")
            return

        athlete = owner
        await asyncio.to_thread(db.touch_token, owner["token_id"])
        uplink = Uplink(athlete["id"], websocket, str(hello.get("agent", ""))[:80])
        hub.uplinks[athlete["id"]] = uplink
        hub.set_online(athlete["id"], True, uplink.agent)
        known = await asyncio.to_thread(db.known_remote_ids, athlete["id"])
        await websocket.send_json({
            "type": "welcome",
            "athlete": auth.public_athlete(athlete),
            "server_time": time.time(),
            "known": known,
        })
        log.info("Uplink up: %s (%s)", athlete["name"], uplink.agent)

        pinger = asyncio.create_task(_ping(websocket))
        # remote session ID -> surrogate key. Without this every single
        # sample would cost a database round trip just to learn the id it
        # had a second ago.
        seen: dict[str, int] = {}
        while True:
            msg = await websocket.receive_json()
            uplink.last_seen = time.time()
            await _handle(msg, athlete, db, hub, websocket, seen)

    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    except Exception as e:
        log.info("Uplink error (%s): %s", athlete["name"] if athlete else "?", e)
    finally:
        if pinger:
            pinger.cancel()
        if athlete:
            if hub.uplinks.get(athlete["id"]) is uplink:
                hub.uplinks.pop(athlete["id"], None)
                hub.set_online(athlete["id"], False)
            log.info("Uplink down: %s", athlete["name"])


async def _ping(websocket: WebSocket) -> None:
    try:
        while True:
            await asyncio.sleep(PING_S)
            await websocket.send_json({"type": "ping"})
    except (asyncio.CancelledError, Exception):
        return


async def _session_key(db, athlete: dict, remote_id: str, started_at: float,
                       seen: dict[str, int]) -> int:
    if remote_id not in seen:
        seen[remote_id] = await asyncio.to_thread(
            db.session_id_for, athlete["id"], remote_id, started_at)
    return seen[remote_id]


async def _handle(msg: dict, athlete: dict, db, hub, websocket: WebSocket,
                  seen: dict[str, int]) -> None:
    kind = msg.get("type")

    if kind == "sample":
        remote_id = str(msg.get("session") or "")
        if not remote_id:
            return
        t = int(msg.get("t") or 0)
        started_at = float(msg.get("started_at") or (time.time() - t))
        session_id = await _session_key(db, athlete, remote_id, started_at, seen)
        await asyncio.to_thread(db.add_sample, session_id, t, time.time(), msg)
        hub.on_sample(athlete["id"], remote_id, session_id, t, msg)

    elif kind == "summary":
        remote_id = str(msg.get("session") or "")
        if not remote_id:
            return
        started_at = float(msg.get("started_at") or time.time())
        session_id = await _session_key(db, athlete, remote_id, started_at, seen)
        await asyncio.to_thread(db.close_session, session_id, time.time(), msg)
        await asyncio.to_thread(records.index_session, db, session_id)
        hub.on_session_end(athlete["id"], session_id)
        hub.broadcast({"type": "session", "session": await asyncio.to_thread(db.session, session_id)})
        log.info("Session closed: %s / %s", athlete["name"], remote_id)

    elif kind == "backfill":
        remote_id = str(msg.get("session") or "")
        rows = msg.get("samples") or []
        if not remote_id or len(rows) > MAX_BACKFILL_ROWS:
            await websocket.send_json({"type": "ack", "session": remote_id, "stored": False})
            return
        started_at = float(msg.get("started_at") or time.time())
        session_id = await _session_key(db, athlete, remote_id, started_at, seen)
        await asyncio.to_thread(db.add_samples, session_id, rows)
        summary = msg.get("summary") or {}
        ended_at = float(msg.get("ended_at") or started_at + float(summary.get("duration_s") or 0))
        await asyncio.to_thread(db.close_session, session_id, ended_at, summary)
        await asyncio.to_thread(records.index_session, db, session_id)
        await websocket.send_json({"type": "ack", "session": remote_id, "stored": True})
        hub.broadcast({"type": "session", "session": await asyncio.to_thread(db.session, session_id)})
        log.info("Backfilled %s / %s (%d samples)", athlete["name"], remote_id, len(rows))

    elif kind == "sync":
        known = await asyncio.to_thread(db.known_remote_ids, athlete["id"])
        await websocket.send_json({"type": "known", "known": known})

    elif kind == "ping":
        await websocket.send_json({"type": "pong"})
