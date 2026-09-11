# WaterRower S4 → ESPHome Bridge

Liest den WaterRower Series IV Performance Monitor über USB aus und stellt
die Werte in Home Assistant, per MQTT und über eine lokale Weboberfläche
bereit. Kein Rechner am Rudergerät nötig – ein ESP32-S3 für unter 10 €
übernimmt die Rolle des USB-Hosts.

## Hardware

| Teil | Hinweis |
|---|---|
| ESP32-S3-DevKitC-1 (Klon, N16R8) | Zwei USB-C-Ports: **COM** (UART, Flashen/Strom) und **USB** (nativer OTG-Port) |
| WaterRower S4 Performance Monitor | Batteriebetrieben (self-powered), USB-Mini-Port |
| USB-C-auf-USB-A-Adapter | Zwischen ESP32-„USB"-Port und dem S4-Kabel |
| USB-Netzteil | Am **COM**-Port |

### Die USB-OTG-Lötbrücke

Auf der Unterseite des DevKitC-1-Klons befindet sich eine Lötbrücke mit
der Beschriftung **USB-OTG**. Sie ist ab Werk offen und muss **geschlossen**
werden. Sie verbindet die VBUS-Leitungen beider USB-C-Ports miteinander:
Erst dadurch liegt am „USB"-Port die 5V-Spannung an, die der S4 braucht,
um überhaupt einen Host zu erkennen. Der S4 zieht darüber praktisch keinen
Strom, er läuft aus seinen eigenen Batterien.

**Wichtig:** Nach dem Schließen der Brücke niemals beide Ports gleichzeitig
an separate Stromquellen hängen.

### Verkabelung

```
USB-Netzteil ──► [COM]  ESP32-S3  [USB] ──► USB-C/A-Adapter ──► S4-Kabel ──► S4
                                   ▲
                          (Lötbrücke USB-OTG geschlossen)
```

## Firmware

ESPHome ≥ 2026.4 mit ESP-IDF-Framework. Die `usb_uart`-Komponente von
ESPHome bildet den S4 als generisches CDC-ACM-Gerät auf ein `uart:`-
Interface ab; der USB-Host-Stack kommt von ESPHome, das Protokoll-Parsing
sitzt in Lambdas in der YAML.

### Ersteinrichtung

1. `secrets.yaml.example` nach `secrets.yaml` kopieren und ausfüllen.
2. Erstes Flashen über den **COM**-Port (Web-Flasher unter web.esphome.io
   oder ESPHome-Dashboard). Falls kein serieller Port erscheint: BOOT-Taste
   gedrückt halten, Kabel einstecken, BOOT loslassen.
3. Danach läuft alles per OTA – kein Kabel mehr nötig.
4. In `esphome-waterrower.yaml` unter `web_server.allowed_origins` die
   Adresse der eigenen Home-Assistant-Instanz eintragen.

### Was die Firmware macht

- Sendet beim Start das `USB`-Kommando (ohne das bleibt der S4 stumm) und
  wiederholt es automatisch, wenn 10 s lang keine Daten kommen.
- Pollt die Speicheradressen des S4 jede Sekunde während des Trainings,
  alle 5 s im Leerlauf.
- Erkennt Session-Start am ersten Ruderschlag und Session-Ende nach 30 s
  ohne Aktivität. Jede Session bekommt eine ID als Zeitstempel (SNTP).
- Published alle Werte einzeln per MQTT sowie gebündelt als JSON auf
  `waterrower/live` (mit Session-ID im Datensatz). Bei Session-Ende geht
  eine Zusammenfassung retained auf `waterrower/session/last`.
- Bietet eine lokale Weboberfläche unter `http://esphome-waterrower.local/`.

## Protokoll

Grundlage ist das Dokument **„Water Rower S4 & S5 USB Protocol, Issue 1.04"**
(im Repo unter `docs/`). Kurzfassung:

- Serielle CDC-Verbindung, 19200 Baud, ASCII, Zeilen enden mit `\r\n`
- `USB` öffnet die Kommunikation, Antwort `_WR_`
- `IRS xxx` / `IRD xxx` / `IRT xxx` lesen 1 / 2 / 3 Bytes ab Adresse `xxx`
- Antworten `IDS` / `IDD` / `IDT` liefern die Bytes **High zuerst**
- `SS` / `SE` = Schlagbeginn / -ende, `Pxx` = Paddel-Pulse pro 25 ms,
  `PING` jede Sekunde im Leerlauf
- Max. ein Paket pro 25 ms senden

### Verwendete Adressen

| Adresse | Register laut Spec | Bedeutung | Status |
|---|---|---|---|
| `057`/`058` | distance_low/hi | Angezeigte Distanz (m) | bestätigt |
| `14A`/`14B` | m_s_low/hi_average | Geschwindigkeit (cm/s), entspricht Display | bestätigt |
| `1A9` | zone_sr_val | Schlagfrequenz | bestätigt |
| `1E1`–`1E3` | display_sec/min/hr | Zeit, **BCD-kodiert** | bestätigt |
| `140`/`141` | strokes_cnt_low/hi | Schlagzahl | plausibel |
| `142`/`143` | stroke_average / stroke_pull | Schlagzeiten in 25-ms-Schritten | ungeprüft |
| `081`/`082` | total_dis_low/hi | Lebenszeit-Distanz | ungeprüft |
| `088`/`089` | kcal_watts_low/hi | Watt | **Skalierung ungeprüft** |
| `1A0` | zone_hr_val | Puls (nur mit Brustgurt) | auskommentiert |

Stolperfallen, die uns Zeit gekostet haben:

- `148`/`149` (`m_s_*_total`) liefert nicht den Display-Wert, `14A`/`14B`
  schon.
- `14C` ist ein Zähler, keine Geschwindigkeit.
- Die Zeitregister sind BCD: `0x13` bedeutet 13, nicht 19.

## MQTT-Topics

| Topic | Inhalt |
|---|---|
| `waterrower/distance` | Distanz in m |
| `waterrower/speed` | Geschwindigkeit in m/s |
| `waterrower/stroke_rate` | Schlagfrequenz |
| `waterrower/strokes` | Schlagzahl |
| `waterrower/ratio` | Zug-/Erholungs-Ratio |
| `waterrower/duration` | Dauer in s |
| `waterrower/watts` | Watt |
| `waterrower/total_distance` | Lebenszeit-Distanz in m |
| `waterrower/split_500m` | 500m-Split als `m:ss` |
| `waterrower/session_active` | `ON` / `OFF` |
| `waterrower/session_id` | aktuelle Session-ID |
| `waterrower/live` | alle Werte als JSON, 1×/s im Training |
| `waterrower/session/last` | Zusammenfassung der letzten Session (retained) |

## Tracker (Docker)

Eigenständige Aufzeichnung und Auswertung, ohne InfluxDB oder Grafana.
Ein Container, SQLite als Speicher, Weboberfläche ohne externe
Abhängigkeiten. Einzige Voraussetzung: ein erreichbarer MQTT-Broker.

```bash
cd docker
docker compose up -d
```

Danach unter `http://<host>:8080/` erreichbar. Beim ersten Aufruf öffnet
sich das Formular für die Broker-Verbindung (Adresse, Port, Login,
Topic-Präfix); die Einstellungen werden in `docker/data/settings.json`
gespeichert und lassen sich jederzeit über den Status oben rechts ändern.
Alternativ können die Werte in `docker-compose.yml` vorbelegt werden.
Die Datenbank liegt in `docker/data/waterrower.db`.

Was der Tracker macht:

- Zeigt die Live-Werte in der Anordnung des S4-Displays
- Speichert jede Einheit aus `waterrower/live` (1 Messpunkt pro Sekunde)
  und übernimmt die Zusammenfassung aus `waterrower/session/last`
- Listet alle Einheiten, zeigt Verlauf von Geschwindigkeit und
  Schlagfrequenz, vergleicht bis zu vier Einheiten übereinander
- CSV-Export und Löschen pro Einheit

Schnittstelle (für eigene Auswertungen):

| Pfad | Inhalt |
|---|---|
| `GET` / `POST /api/settings` | Broker-Einstellungen lesen / setzen (verbindet neu) |
| `GET /api/live` | aktueller Zustand |
| `GET /api/stream` | Live-Updates als Server-Sent Events |
| `GET /api/sessions` | Liste aller Einheiten |
| `GET /api/sessions/{id}` | Einheit mit allen Messpunkten |
| `GET /api/sessions/{id}/export.csv` | Messpunkte als CSV |
| `DELETE /api/sessions/{id}` | Einheit löschen |

Wird der Tracker erst nach dem ESP gestartet, fehlen die Messpunkte
davor – die Session-ID trägt aber den Startzeitpunkt, die Sortierung
bleibt korrekt.

## Fehlersuche

- **Sensoren bleiben 0, Log zeigt keine USB-Meldung:** Der ESP32 sieht kein
  Gerät. Lötbrücke prüfen (Multimeter: ~5 V am VBUS-Pin des „USB"-Ports),
  Adapter auf Datenleitungen prüfen.
- **Gerät wird erkannt, aber keine Antworten:** Handshake fehlt. Im Log
  sollte nach `USB` ein `_WR_` kommen.
- **Rohdaten ansehen:** In der YAML `usb_uart.channels.debug: true` setzen,
  dann erscheint jedes Paket im Log als Byte-Folge. Der Sensor
  „WaterRower S4 Rohdaten" zeigt die letzte geparste Zeile.
- **OTA rollback detected:** Die neue Firmware ist beim Boot abgestürzt,
  ESPHome hat die alte zurückgespielt. Letzte Änderung isoliert testen.

## Offene Punkte

- Verifikation von Ratio- und Watt-Register am Display
- Workout-Vorgabe aus Home Assistant (`WSI`/`WSU`-Kommandos)
- Umschalten der Anzeigeeinheit (`DI`-Kommandos)
- HTML-Nachbau des S4-Displays für Home Assistant
- Telegraf-Anbindung an InfluxDB (`telegraf-waterrower.conf` ist ein Entwurf,
  optional neben dem Docker-Tracker)
- Workout-Übersicht in HA (z. B. Tracker per iframe einbinden)
- Puls-Sensorik bei Anschaffung eines Brustgurts
