"""Hört auf die MQTT-Topics der ESPHome-Bridge und schreibt in die Datenbank."""

import json
import logging
import threading
import time

import paho.mqtt.client as mqtt

from db import Database

log = logging.getLogger("mqtt")


class LiveState:
    """Letzter bekannter Zustand, für die Live-Ansicht."""

    def __init__(self):
        self._lock = threading.Lock()
        self.values: dict = {}
        self.session_id: str = ""
        self.session_active: bool = False
        self.updated_at: float = 0
        self.connected: bool = False
        self._listeners: list = []

    def update(self, **kwargs):
        with self._lock:
            self.values.update({k: v for k, v in kwargs.items() if v is not None})
            self.updated_at = time.time()
        self._notify()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "values": dict(self.values),
                "session_id": self.session_id,
                "session_active": self.session_active,
                "updated_at": self.updated_at,
                "connected": self.connected,
            }

    def subscribe(self, cb):
        self._listeners.append(cb)

    def unsubscribe(self, cb):
        if cb in self._listeners:
            self._listeners.remove(cb)

    def _notify(self):
        snap = self.snapshot()
        for cb in list(self._listeners):
            try:
                cb(snap)
            except Exception:
                self._listeners.remove(cb)


class MqttIngest:
    def __init__(self, db: Database, state: LiveState, settings: dict):
        self.db = db
        self.state = state
        self.client = None
        self.settings = {}
        self.last_error = ""
        self.configure(settings)

    def configure(self, settings: dict):
        """Verbindung (neu) aufbauen. Wird auch vom Einstellungsformular genutzt."""
        self.stop()
        self.settings = dict(settings)
        self.prefix = settings.get("prefix", "waterrower").rstrip("/")
        self.last_error = ""
        self.state.connected = False

        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id="waterrower-tracker"
        )
        if settings.get("username"):
            client.username_pw_set(settings["username"], settings.get("password") or None)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        self.client = client

    def start(self):
        if not self.settings.get("host"):
            self.last_error = "Keine Broker-Adresse konfiguriert"
            return
        try:
            self.client.connect_async(self.settings["host"], int(self.settings.get("port", 1883)), keepalive=60)
            self.client.loop_start()
        except (OSError, ValueError) as e:
            self.last_error = str(e)
            log.warning("MQTT-Verbindung fehlgeschlagen: %s", e)

    def stop(self):
        if self.client is not None:
            try:
                self.client.loop_stop()
                self.client.disconnect()
            except Exception:
                pass
            self.client = None

    # --- Callbacks -------------------------------------------------------

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code.is_failure:
            self.last_error = str(reason_code)
            log.warning("MQTT abgelehnt: %s", reason_code)
            self.state.connected = False
            self.state.update()
            return
        log.info("MQTT verbunden")
        self.last_error = ""
        self.state.connected = True
        client.subscribe(f"{self.prefix}/#")
        self.state.update()

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        log.warning("MQTT getrennt (%s)", reason_code)
        self.state.connected = False
        self.state.update()

    def _on_message(self, client, userdata, msg):
        topic = msg.topic[len(self.prefix) + 1:]
        payload = msg.payload.decode(errors="replace").strip()

        try:
            if topic == "live":
                self._handle_live(json.loads(payload))
            elif topic == "session/last":
                self._handle_summary(json.loads(payload))
            elif topic == "session_active":
                self.state.session_active = payload == "ON"
                self.state.update()
            elif topic == "session_id":
                self.state.session_id = payload
            elif topic in ("distance", "speed", "stroke_rate", "strokes",
                           "duration", "watts", "total_distance", "ratio"):
                self.state.update(**{topic: _num(payload)})
            elif topic == "split_500m":
                self.state.update(split_500m=payload)
        except (ValueError, json.JSONDecodeError) as e:
            log.debug("Ignoriere %s: %s (%s)", topic, payload[:60], e)

    def _handle_live(self, data: dict):
        sid = data.get("session_id")
        if not sid:
            return
        self.db.add_sample(sid, time.time(), data)
        self.state.session_id = sid
        self.state.session_active = True
        self.state.update(
            distance=data.get("distance_m"), speed=data.get("speed_ms"),
            stroke_rate=data.get("stroke_rate"), strokes=data.get("strokes"),
            duration=data.get("duration_s"), watts=data.get("watts"),
        )

    def _handle_summary(self, data: dict):
        sid = data.get("session_id")
        if not sid:
            return
        self.db.close_session(sid, time.time(), data)
        self.state.session_active = False
        self.state.update()
        log.info("Session abgeschlossen: %s", sid)


def _num(s: str):
    try:
        return float(s)
    except ValueError:
        return None
