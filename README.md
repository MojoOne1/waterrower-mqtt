# waterrower-mqtt

Reads out a WaterRower Series IV Performance Monitor over USB and makes the
values available in Home Assistant, via MQTT, and through a local web UI.
No computer needed at the rowing machine – an ESP32-S3 for under €10 takes
on the role of USB host.

```
WaterRower S4 ──USB──► ESP32-S3 (ESPHome) ──MQTT──► broker ──► Tracker (Docker, web UI)
                            │                                   ──► Home Assistant (native API)
                            └── local web UI                     ──► Telegraf/InfluxDB (optional)
```

Two parts, usable independently:

- **Firmware** (`esphome-waterrower.yaml`) – ESPHome config for the ESP32-S3.
  Talks the S4's serial protocol, detects sessions, publishes to MQTT and
  exposes everything as Home Assistant entities.
- **Tracker** (`docker/`) – a single container that records every session
  from MQTT into SQLite and serves a web UI: live display, per-session
  charts, session comparison, CSV export.

| Live | History & comparison |
|---|---|
| ![Live view](docs/screenshots/live.png) | ![Session history](docs/screenshots/history.png) |

## Hardware

| Part | Note |
|---|---|
| ESP32-S3-DevKitC-1 (clone, N16R8) | Two USB-C ports: **COM** (UART, flashing/power) and **USB** (native OTG port) |
| WaterRower S4 Performance Monitor | Battery-powered (self-powered), USB Mini port |
| USB-C-to-USB-A adapter | Between the ESP32's "USB" port and the S4 cable |
| USB power supply | On the **COM** port |

### The USB-OTG solder bridge

On the underside of the DevKitC-1 clone there's a solder bridge labeled
**USB-OTG**. It's open by default and must be **closed**. It ties the VBUS
lines of both USB-C ports together: only then does the "USB" port carry the
5V the S4 needs to detect a host at all. The S4 draws virtually no power
through it – it runs off its own batteries.

**Important:** Once the bridge is closed, never connect both ports to
separate power sources at the same time.

### Wiring

```
USB power supply ──► [COM]  ESP32-S3  [USB] ──► USB-C/A adapter ──► S4 cable ──► S4
                                       ▲
                              (USB-OTG solder bridge closed)
```

## Firmware

ESPHome ≥ 2026.4 with the ESP-IDF framework. ESPHome's `usb_uart` component
exposes the S4 as a generic CDC-ACM device on a `uart:` interface; the USB
host stack comes from ESPHome, and the protocol parsing lives in lambdas in
the YAML.

### Initial setup

1. Copy `secrets.yaml.example` to `secrets.yaml` and fill it in.
2. In `esphome-waterrower.yaml`, under `web_server.allowed_origins`, enter
   the address of your Home Assistant instance.
3. First flash over the **COM** port (web flasher at web.esphome.io or the
   ESPHome dashboard). If no serial port shows up: hold BOOT, plug in the
   cable, release BOOT.
4. After that everything runs over OTA – no cable needed anymore.

### What the firmware does

- Sends the `USB` command on boot (without it the S4 stays silent) and
  repeats it automatically if no data arrives for 10 s.
- Polls the S4's memory addresses every second during a workout. While
  idle it sends nothing at all – every packet the S4 receives resets its
  auto power-off timer, so the monitor still switches itself off as usual.
- Detects session start on the first stroke. A session ends when the
  tracker's "End session" button sends `waterrower/cmd/end_session`, or as
  a safety net after a configurable time without stroke or paddle packets
  from the S4 (default 5 min, "WaterRower Session Timeout" in Home
  Assistant – the speed register isn't used for this, it keeps its last
  value after you stop). Each session gets an ID that's a local timestamp
  (SNTP).
- Shows 0 for speed, stroke rate and watts as soon as the S4 reports no
  rowing (its `PING`) – the monitor itself keeps displaying the last
  stroke's values.
- Publishes every value individually over MQTT, plus bundled as JSON on
  `waterrower/live` (with the session ID in the payload). At session end a
  retained summary goes out on `waterrower/session/last`.
- Serves a local web UI at `http://esphome-waterrower.local/`.

## Protocol

Based on WaterRower's document **"Water Rower S4 & S5 USB Protocol, Issue
1.04"**. It isn't included here because its redistribution terms are unclear,
but searching for the exact title finds it quickly. Summary:

- Serial CDC connection, 19200 baud, ASCII, lines end with `\r\n`
- `USB` opens the connection, response `_WR_`
- `IRS xxx` / `IRD xxx` / `IRT xxx` read 1 / 2 / 3 bytes starting at address
  `xxx`
- Responses `IDS` / `IDD` / `IDT` return the bytes **high byte first**
- `SS` / `SE` = stroke start / end, `Pxx` = paddle pulses per 25 ms, `PING`
  every second while idle
- Send at most one packet per 25 ms

### Addresses used

| Address | Register per spec | Meaning | Status |
|---|---|---|---|
| `057`/`058` | distance_low/hi | Displayed distance (m) | confirmed |
| `14A`/`14B` | m_s_low/hi_average | Speed (cm/s), matches the display | confirmed |
| `1A9` | zone_sr_val | Stroke rate | confirmed |
| `1E1`–`1E3` | display_sec/min/hr | Time, **BCD-encoded** | confirmed |
| `140`/`141` | strokes_cnt_low/hi | Stroke count | plausible |
| `142`/`143` | stroke_average / stroke_pull | Stroke timings in 25 ms steps | unverified |
| `081`/`082` | total_dis_low/hi | Lifetime distance | unverified |
| `088`/`089` | kcal_watts_low/hi | Watts | **scaling unverified** |
| `1A0` | zone_hr_val | Heart rate (chest strap only) | commented out |

Pitfalls that cost us time:

- `148`/`149` (`m_s_*_total`) doesn't return the display value, `14A`/`14B`
  does.
- `14C` is a counter, not a speed.
- The time registers are BCD: `0x13` means 13, not 19.

## MQTT topics

| Topic | Content |
|---|---|
| `waterrower/distance` | Distance in m |
| `waterrower/speed` | Speed in m/s |
| `waterrower/stroke_rate` | Stroke rate |
| `waterrower/strokes` | Stroke count |
| `waterrower/ratio` | Pull/recovery ratio |
| `waterrower/duration` | Duration in s |
| `waterrower/watts` | Watts |
| `waterrower/total_distance` | Lifetime distance in m |
| `waterrower/split_500m` | 500m split as `m:ss` |
| `waterrower/session_active` | `ON` / `OFF` |
| `waterrower/session_id` | Current session ID |
| `waterrower/live` | All values as JSON, 1×/s during a workout |
| `waterrower/session/last` | Summary of the last session (retained) |
| `waterrower/firmware_version` | Firmware version (retained) |
| `waterrower/cmd/end_session` | **To** the ESP: end the running session; payload `reset` also resets the monitor |

## Tracker (Docker)

Standalone recording and analysis, no InfluxDB or Grafana required. One
container, SQLite for storage, a web UI with no external dependencies. The
only requirement is a reachable MQTT broker.

### Deploy

The image is published to GitHub Container Registry for `linux/amd64` and
`linux/arm64` (Raspberry Pi 4/5 etc.) by `.github/workflows/docker-publish.yml`
on every push to `master`.

The `docker-compose.yml` at the repo root pulls that image – it's the only
file a host needs (e.g. as a Dockge or Portainer stack), no checkout, no
build:

```bash
docker compose up -d
```

Then open `http://<host>:8080/`. On first visit, a form for the broker
connection (address, port, login, topic prefix) opens; settings are saved to
`./data/settings.json` and can be changed anytime via the status indicator
in the top right. Alternatively pre-fill the `MQTT_*` variables in the
compose file. The database lives at `./data/waterrower.db`.

Set `TZ` in the compose file to the ESP's time zone – session IDs are local
timestamps, and the tracker uses `TZ` to turn them into the start times
shown in the UI.

### Develop

`docker/docker-compose.yml` builds the image from source instead:

```bash
cd docker
docker compose up -d --build
```

### What the tracker does

- Shows live values laid out like the S4 display
- Stores every session from `waterrower/live` (1 sample per second) and
  picks up the summary from `waterrower/session/last`
- Lists all sessions, shows speed and stroke-rate history, compares up to
  four sessions overlaid
- "End session" button that closes the running session on the ESP and
  resets the monitor (like its power button)
- CSV export and per-session delete

If the tracker is started after the ESP, the samples from before are
missing – but the session ID carries the start time, so ordering stays
correct.

### API

For your own analysis:

| Path | Content |
|---|---|
| `GET` / `POST /api/settings` | Read / set broker settings (reconnects) |
| `GET /api/version` | Tracker version and git commit |
| `GET /api/live` | Current state |
| `GET /api/stream` | Live updates as Server-Sent Events |
| `POST /api/session/end` | End the running session and reset the monitor (publishes `cmd/end_session` = `reset`) |
| `GET /api/sessions` | List of all sessions |
| `GET /api/sessions/{id}` | Session with all samples |
| `GET /api/sessions/{id}/export.csv` | Samples as CSV |
| `DELETE /api/sessions/{id}` | Delete a session |

The UI is available in English and German – the DE/EN toggle in the header
switches it; the default follows the browser language.

## Versioning

One version number for the whole project, kept in two places that must
match: the `VERSION` file at the repo root and `substitutions.version` in
`esphome-waterrower.yaml`. Releases are tagged `v<version>` in git.

- **Tracker**: the workflow stamps the image with the version and the
  short commit hash (`APP_VERSION`, `GIT_COMMIT`); the image is tagged
  `latest`, `<version>` and `sha-<commit>`. Both show in the web UI's
  footer (the commit links to GitHub) and at `/api/version`.
- **Firmware**: the version appears in Home Assistant's device info, as
  the "Firmware Version" entity in the ESPHome web UI, and is published
  on `waterrower/firmware_version` so the tracker's footer can show it.
  The "ESPHome Version" entity adds the compile timestamp. The firmware is
  compiled in the ESPHome dashboard, where git isn't available – the
  version tag is the link to the commit.

## Troubleshooting

- **Sensors stay at 0, log shows no USB message:** The ESP32 doesn't see a
  device. Check the solder bridge (multimeter: ~5V on the VBUS pin of the
  "USB" port), check the adapter's data lines.
- **Device is detected but no responses:** Handshake is missing. The log
  should show a `_WR_` after `USB`.
- **Inspect raw data:** Set `usb_uart.channels.debug: true` in the YAML,
  then every packet shows up in the log as a byte sequence. The
  "WaterRower S4 Raw Data" sensor shows the last parsed line.
- **OTA rollback detected:** The new firmware crashed on boot, ESPHome
  rolled back to the old one. Test the last change in isolation.
- **Session start times are off by a few hours:** `TZ` in the compose file
  doesn't match the ESP's time zone.
- **The monitor never switches itself off:** something is sending it
  packets while idle. The firmware deliberately stays silent outside a
  session for this reason – check for other clients on the USB link or
  a modified polling interval.

## Open items

- Verify the ratio and watts registers against the display
- Workout presets from Home Assistant (`WSI`/`WSU` commands)
- Switching the display unit (`DI` commands)
- HTML recreation of the S4 display for Home Assistant
- Telegraf connection to InfluxDB (`telegraf-waterrower.conf` is a draft,
  optional alongside the Docker tracker)
- Workout overview in HA (e.g. embed the tracker via iframe)
- Heart-rate sensing once a chest strap is acquired

## License

[MIT](LICENSE)
