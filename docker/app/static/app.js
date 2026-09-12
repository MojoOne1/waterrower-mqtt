/* WaterRower Tracker - UI (no dependencies) */

const $ = (id) => document.getElementById(id);

// Canvas can't use CSS variables, so the palette is read from the document
// once per theme and the charts are redrawn when the colour scheme flips.
const THEME = { series: [] };
function readTheme() {
  const s = getComputedStyle(document.documentElement);
  const v = (name, fallback) => s.getPropertyValue(name).trim() || fallback;
  THEME.series = [
    v("--series-1", "#2a78d6"), v("--series-2", "#eb6834"),
    v("--series-3", "#1baf7a"), v("--series-4", "#eda100"),
  ];
  THEME.grid = v("--grid", "#e4e6dc");
  THEME.muted = v("--muted", "#7c8076");
  THEME.ink = v("--ink", "#1c1f22");
  THEME.accent = v("--accent", "#a9601f");
}
readTheme();

let sessions = [];
let selected = null;
let compareSet = new Set();
let lastSnap = null;
const cache = new Map();   // session_id -> {session, samples}

// --- Language ------------------------------------------------------------

const I18N = {
  de: {
    locale: "de-DE",
    connecting: "MQTT: verbinde …", connOff: "MQTT nicht verbunden", connOn: "MQTT verbunden", connLive: "Aufzeichnung läuft",
    connLost: "MQTT-Verbindung verloren, versuche erneut …",
    s4Unknown: "Ergometer: unbekannt", s4Off: "Ergometer aus", s4On: "Ergometer an", s4Usb: "Ergometer verbunden",
    themeGroup: "Darstellung", themeAuto: "Auto", themeLight: "Hell", themeDark: "Dunkel",
    settingsTitle: "Verbindung zum MQTT-Broker",
    labelHost: "Adresse", labelPort: "Port", labelUser: "Benutzer", labelPassword: "Passwort", labelPrefix: "Topic-Präfix",
    phHost: "10.0.0.5 oder broker.local", phOptional: "optional",
    settingsHint: "Der Präfix muss zu <code>topic_prefix</code> in der ESPHome-Konfiguration passen.",
    btnConnect: "Verbinden", formConnecting: "Verbinde …", formConnected: "Verbunden",
    formSaved: "Gespeichert",
    saveFailed: "Speichern fehlgeschlagen", noConnection: "Keine Verbindung – Adresse, Port und Login prüfen",
    waiting: "Warten auf Ruderschlag …",
    waitingTotal: (m) => `Warten auf Ruderschlag. Gesamt gerudert: ${m} m`,
    running: (when) => `Einheit <strong>${when}</strong> läuft`,
    split500: (split) => ` · 500 m in <strong>${split}</strong>`,
    sessionsTitle: "Einheiten",
    sessionsEmpty: "Noch keine Einheit aufgezeichnet. Die erste erscheint hier, sobald du losruderst.",
    open: "offen", inCompare: "im Vergleich",
    compare: "vergleichen", delete: "löschen", confirmDelete: "Diese Einheit endgültig löschen?",
    maxCompare: "Maximal vier Einheiten im Vergleich.",
    chartSpeed: "Geschwindigkeit in m/s", chartSpm: "Schlagfrequenz",
    compareTitle: "Vergleich", clearSelection: "Auswahl leeren",
    chartCmp: "Geschwindigkeit ab Start der jeweiligen Einheit",
    allSessions: "Alle Einheiten", chartTrend: "Distanz je Einheit", exportAll: "Alle als Excel",
    trendSum: (n, m, dur) => `${n} Einheiten · ${m} m · ${dur} gesamt`,
    noSamples: "Keine Messpunkte", avg: "Ø",
    endSession: "Einheit beenden", confirmEnd: "Diese Einheit jetzt beenden? Der Monitor behält seine Anzeige.",
    zeroMonitor: "Beenden & nullen", confirmZero: "Einheit beenden und den Monitor auf null setzen?",
    endFailed: "Beenden fehlgeschlagen",
    raceFree: "Frei rudern", raceGo: "LOS",
    raceHold: "Monitor wird genullt – noch nicht rudern",
    racePlace: (p, n) => `Platz ${p} von ${n}`,
    raceLead: "in Führung", raceDone: (t) => `im Ziel ${t}`,
    raceOver: "Rennen beendet",
    fDistance: "Distanz", fDuration: "Dauer", fSplit: "Ø 500 m", fAvgSpeed: "Ø Geschwindigkeit", fPeak: "Spitze",
    fAvgSpm: "Ø Schlagfrequenz", fStrokes: "Schläge", fMeterPerStroke: "Meter je Schlag",
    arenaTitle: "Arena – gemeinsam rudern",
    arenaUrl: "Server", arenaUrlPh: "arena.example.com", arenaToken: "Token",
    arenaEnabled: "Daten an die Arena senden",
    arenaHint: "Der Token kommt aus der Arena unter <em>Konto → Tracker-Verbindung</em>. " +
      "Aufgezeichnet wird weiterhin lokal; die Arena bekommt eine Kopie und kann vor einem Rennen den Monitor zurücksetzen.",
    btnSave: "Speichern",
    arenaOn: (who) => `Arena: ${who || "verbunden"}`,
    arenaOff: "Arena getrennt", arenaIdle: "Arena aus",
    fwTitle: "Firmware auf dem ESP",
    fwRunning: "Läuft gerade", fwExpected: "Zu diesem Tracker gehört",
    fwUrl: "ESPHome-Dashboard", fwUrlPh: "http://10.0.0.5:6052",
    fwOpen: "ESPHome öffnen",
    fwUnknown: "unbekannt – erst wenn MQTT fließt",
    fwMatch: "Passt zusammen.",
    fwDiffer: "Andere Version als dieser Tracker. Das ist erlaubt, kann aber " +
      "erklären, warum ein neues Feld fehlt.",
    fwUnreachable: "Vom Tracker aus nicht erreichbar. Der Link geht trotzdem – " +
      "dein Browser kommt oft dorthin, wo dieser Container nicht hinkommt.",
    fwConfig: "Konfiguration",
    fwDownload: "Herunterladen", fwInstall: "Ins ESPHome-Verzeichnis",
    fwUpload: "Eigene YAML …",
    fwShipped: (v) => `mitgeliefert (${v})`,
    fwNoDir: (d) => `${d} ist nicht eingebunden – teile den Ordner mit dem ` +
      "ESPHome-Container, dann landet die YAML direkt dort. Herunterladen geht immer.",
    fwWrote: (n) => `${n} liegt jetzt im ESPHome-Verzeichnis.`,
    fwExists: (n) => `${n} ist schon da. Überschreiben?`,
    fwHint: "Kompiliert und geflasht wird im ESPHome-Dashboard: YAML bearbeiten, " +
      "<em>Install → Wirelessly</em>, fertig. Der Tracker baut nichts selbst – dafür " +
      "bräuchte er eine ganze Toolchain, und er soll vor allem eines: weiter aufzeichnen. " +
      "Den Container gibt es auskommentiert in der Compose-Datei.",
  },
  en: {
    locale: "en-GB",
    connecting: "MQTT: connecting …", connOff: "MQTT not connected", connOn: "MQTT connected", connLive: "recording",
    connLost: "MQTT connection lost, retrying …",
    s4Unknown: "Ergometer: unknown", s4Off: "Ergometer off", s4On: "Ergometer on", s4Usb: "Ergometer connected",
    themeGroup: "Appearance", themeAuto: "Auto", themeLight: "Light", themeDark: "Dark",
    settingsTitle: "MQTT broker connection",
    labelHost: "Address", labelPort: "Port", labelUser: "Username", labelPassword: "Password", labelPrefix: "Topic prefix",
    phHost: "10.0.0.5 or broker.local", phOptional: "optional",
    settingsHint: "The prefix must match <code>topic_prefix</code> in the ESPHome configuration.",
    btnConnect: "Connect", formConnecting: "Connecting …", formConnected: "Connected",
    formSaved: "Saved",
    saveFailed: "Saving failed", noConnection: "No connection – check address, port and login",
    waiting: "Waiting for a stroke …",
    waitingTotal: (m) => `Waiting for a stroke. Total rowed: ${m} m`,
    running: (when) => `Session <strong>${when}</strong> in progress`,
    split500: (split) => ` · 500 m in <strong>${split}</strong>`,
    sessionsTitle: "Sessions",
    sessionsEmpty: "No session recorded yet. The first one shows up here as soon as you start rowing.",
    open: "open", inCompare: "in comparison",
    compare: "compare", delete: "delete", confirmDelete: "Delete this session permanently?",
    maxCompare: "At most four sessions can be compared.",
    chartSpeed: "Speed in m/s", chartSpm: "Stroke rate",
    compareTitle: "Comparison", clearSelection: "Clear selection",
    chartCmp: "Speed from the start of each session",
    allSessions: "All sessions", chartTrend: "Distance per session", exportAll: "All as Excel",
    trendSum: (n, m, dur) => `${n} sessions · ${m} m · ${dur} total`,
    noSamples: "No samples", avg: "avg",
    endSession: "End session", confirmEnd: "End your session now? The monitor keeps its display.",
    zeroMonitor: "End & zero", confirmZero: "End the session and set the monitor back to zero?",
    endFailed: "Could not end the session",
    raceFree: "Just row", raceGo: "GO",
    raceHold: "Monitor being zeroed - do not row yet",
    racePlace: (p, n) => `Place ${p} of ${n}`,
    raceLead: "in the lead", raceDone: (t) => `finished ${t}`,
    raceOver: "Race over",
    fDistance: "Distance", fDuration: "Duration", fSplit: "Avg 500 m", fAvgSpeed: "Avg speed", fPeak: "Peak",
    fAvgSpm: "Avg stroke rate", fStrokes: "Strokes", fMeterPerStroke: "Metres per stroke",
    arenaTitle: "Arena – rowing together",
    arenaUrl: "Server", arenaUrlPh: "arena.example.com", arenaToken: "Token",
    arenaEnabled: "Send data to the arena",
    arenaHint: "The token comes from the arena under <em>Account → Tracker connection</em>. " +
      "Recording stays local; the arena gets a copy and may reset the monitor before a race.",
    btnSave: "Save",
    arenaOn: (who) => `Arena: ${who || "connected"}`,
    arenaOff: "Arena disconnected", arenaIdle: "Arena off",
    fwTitle: "Firmware on the ESP",
    fwRunning: "Running now", fwExpected: "Ships with this tracker",
    fwUrl: "ESPHome dashboard", fwUrlPh: "http://10.0.0.5:6052",
    fwOpen: "Open ESPHome",
    fwUnknown: "unknown - only once MQTT is flowing",
    fwMatch: "These match.",
    fwDiffer: "A different version from this tracker. That is allowed, but it " +
      "can explain a missing field.",
    fwUnreachable: "Not reachable from the tracker. The link still works - your " +
      "browser often gets where this container cannot.",
    fwConfig: "Configuration",
    fwDownload: "Download", fwInstall: "Into the ESPHome folder",
    fwUpload: "Your own YAML …",
    fwShipped: (v) => `shipped (${v})`,
    fwNoDir: (d) => `${d} is not mounted - share the folder with the ESPHome ` +
      "container and the YAML lands there directly. Downloading always works.",
    fwWrote: (n) => `${n} is now in the ESPHome folder.`,
    fwExists: (n) => `${n} is already there. Overwrite?`,
    fwHint: "Compiling and flashing happen in the ESPHome dashboard: edit the YAML, " +
      "<em>Install → Wirelessly</em>, done. The tracker builds nothing itself - that " +
      "would need a whole toolchain, and its one job is to keep recording. The " +
      "container is in the compose file, commented out.",
  },
};

let lang = "en";
try { lang = localStorage.getItem("lang") || (navigator.language.startsWith("de") ? "de" : "en"); } catch {}
if (!I18N[lang]) lang = "en";
const t = (key, ...args) => { const v = I18N[lang][key]; return typeof v === "function" ? v(...args) : v; };
const locale = () => I18N[lang].locale;

function applyLang() {
  document.documentElement.lang = lang;
  document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll("[data-i18n-html]").forEach((el) => { el.innerHTML = t(el.dataset.i18nHtml); });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => { el.placeholder = t(el.dataset.i18nPlaceholder); });
  document.querySelectorAll("[data-i18n-title]").forEach((el) => { el.title = t(el.dataset.i18nTitle); });
  document.querySelectorAll("[data-i18n-aria]").forEach((el) => { el.setAttribute("aria-label", t(el.dataset.i18nAria)); });
  document.querySelectorAll(".lang button").forEach((b) => {
    const on = b.dataset.lang === lang;
    b.classList.toggle("active", on);
    b.setAttribute("aria-pressed", String(on));
  });
}

async function setLang(next) {
  if (!I18N[next] || next === lang) return;
  lang = next;
  try { localStorage.setItem("lang", lang); } catch {}
  applyLang();
  if (lastSnap) renderLive(lastSnap);
  pollArena();
  await loadSessions();
  if (selected) await selectSession(selected);
  renderCompare();
}
document.querySelectorAll(".lang button").forEach((b) => { b.onclick = () => setLang(b.dataset.lang); });

// --- Theme ---------------------------------------------------------------

let theme = "auto";
try { theme = localStorage.getItem("theme") || "auto"; } catch {}
if (!["auto", "light", "dark"].includes(theme)) theme = "auto";

function applyTheme() {
  if (theme === "auto") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
  document.querySelectorAll("#theme button").forEach((b) => {
    const on = b.dataset.theme === theme;
    b.classList.toggle("active", on);
    b.setAttribute("aria-pressed", String(on));
  });
  readTheme();   // canvas colours come from the CSS variables
}

async function redrawCharts() {
  await loadSessions();
  if (selected) await selectSession(selected);
  renderCompare();
}

async function setTheme(next) {
  if (theme === next) return;
  theme = next;
  try { localStorage.setItem("theme", theme); } catch {}
  applyTheme();
  await redrawCharts();
}
document.querySelectorAll("#theme button").forEach((b) => { b.onclick = () => setTheme(b.dataset.theme); });

// --- Helpers -----------------------------------------------------------

const fmtDur = (s) => {
  s = Math.max(0, Math.round(s || 0));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`
           : `${m}:${String(sec).padStart(2, "0")}`;
};
const fmtSplit = (ms) => {
  if (!ms || ms <= 0) return "--:--";
  const t = Math.round(500 / ms);
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
};
const parseSid = (sid) => {
  const m = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})$/.exec(sid || "");
  return m ? new Date(+m[1], m[2] - 1, +m[3], +m[4], +m[5], +m[6]) : null;
};
const fmtWhen = (sid, ts) => {
  const d = ts ? new Date(ts * 1000) : parseSid(sid);
  if (!d) return sid;
  return d.toLocaleString(locale(), { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
};
const fmtDay = (ts) => new Date(ts * 1000).toLocaleDateString(locale(), { day: "2-digit", month: "2-digit" });
const fmtInt = (n) => Math.round(n).toLocaleString(locale());
const smooth = (arr, w = 7) => arr.map((_, i) => {
  const a = arr.slice(Math.max(0, i - w), i + w + 1).filter((v) => v != null);
  return a.length ? a.reduce((x, y) => x + y, 0) / a.length : null;
});
const avg = (arr) => { const a = arr.filter((v) => v != null); return a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0; };

async function getSession(id) {
  if (!cache.has(id)) cache.set(id, await (await fetch(`/api/sessions/${id}`)).json());
  return cache.get(id);
}

// --- Live display --------------------------------------------------------

/* The arena pushes each racer their own slice down the uplink, so the
   screen at the machine can show the countdown and where they stand
   without a phone propped up next to it. Their lane only - the whole field
   is what the arena itself is for. */
function renderRace(race) {
  const strip = $("race-strip");
  if (!strip) return;
  strip.hidden = !race;
  strip.className = "race-strip";
  if (!race) return;
  strip.textContent = "";

  const label = race.mode === "distance" ? `${fmtInt(race.target)} m`
    : race.mode === "time" ? fmtDur(race.target) : t("raceFree");
  const head = document.createElement("span");
  head.className = "race-name";
  head.textContent = [race.name, label].filter(Boolean).join(" · ");
  strip.appendChild(head);

  const big = document.createElement("span");
  big.className = "race-big";
  const rest = document.createElement("span");
  rest.className = "race-rest";

  if (race.state === "countdown") {
    strip.classList.add("countdown");
    const left = Math.max(0, Math.ceil(race.countdown_in || 0));
    big.textContent = left > 0 ? String(left) : t("raceGo");
    rest.textContent = t("raceHold");
  } else if (race.state === "running") {
    big.textContent = fmtInt(race.progress) + " m";
    const bits = [];
    if (race.place) bits.push(t("racePlace", race.place, race.lanes));
    if (race.finished) bits.push(t("raceDone", fmtDur(race.time_s)));
    else if (race.gap_m > 0) bits.push(`−${fmtInt(race.gap_m)} m`);
    else bits.push(t("raceLead"));
    rest.textContent = bits.join("  ·  ");
  } else {
    strip.classList.add("done");
    big.textContent = race.time_s != null ? fmtDur(race.time_s) : fmtInt(race.progress) + " m";
    rest.textContent = race.place ? t("racePlace", race.place, race.lanes) : t("raceOver");
  }
  strip.appendChild(big);
  strip.appendChild(rest);
}

function renderLive(snap) {
  lastSnap = snap;
  renderRace(snap.race);
  const v = snap.values || {};
  const active = snap.session_active;

  $("lcd-sr").textContent    = v.stroke_rate != null ? Math.round(v.stroke_rate) : "--";
  $("lcd-speed").textContent = v.speed != null ? Number(v.speed).toFixed(2) : "-.--";
  $("lcd-dur").textContent   = v.duration != null ? fmtDur(v.duration) : "--:--";
  $("lcd-dist").textContent  = v.distance != null ? Math.round(v.distance) : "---";
  document.querySelectorAll(".cell").forEach((c) => c.classList.toggle("idle", !active));

  const conn = $("conn");
  conn.classList.toggle("on", snap.connected);
  conn.classList.toggle("live", snap.connected && active);
  $("conn-text").textContent = !snap.connected ? t("connOff") : active ? t("connLive") : t("connOn");

  // Ergometer link, as reported by the ESP (retained MQTT topics).
  const s4 = $("s4"), present = v.s4_connected, usb = v.usb_mode;
  s4.classList.toggle("on", present === true);
  s4.classList.toggle("usb", present === true && usb === true);
  $("s4-text").textContent = present == null ? t("s4Unknown") : !present ? t("s4Off") : usb ? t("s4Usb") : t("s4On");

  $("end").hidden = !(active && snap.session_id);
  $("zero").hidden = $("end").hidden;
  renderFooter();

  const line = $("session-line");
  if (active && snap.session_id) {
    line.innerHTML = t("running", fmtWhen(snap.session_id)) + (v.speed ? t("split500", fmtSplit(v.speed)) : "");
  } else if (v.total_distance) {
    line.textContent = t("waitingTotal", fmtInt(v.total_distance));
  } else {
    line.textContent = t("waiting");
  }
}

/* End leaves the numbers on the monitor to be read while rowing out;
   zero clears them for the next piece. The arena shows the same pair with
   the same words, so it does not matter which screen you reach for. */
function endWith(path, confirmKey) {
  return async () => {
    if (!confirm(t(confirmKey))) return;
    const r = await fetch(path, { method: "POST" });
    if (!r.ok) alert((await r.json()).detail || t("endFailed"));
  };
}

$("end").onclick = endWith("/api/session/end", "confirmEnd");
$("zero").onclick = endWith("/api/session/reset", "confirmZero");

function connectStream() {
  const es = new EventSource("/api/stream");
  let wasActive = false;
  es.onmessage = (e) => {
    const snap = JSON.parse(e.data);
    renderLive(snap);
    if (wasActive && !snap.session_active) { cache.clear(); loadSessions(); }
    wasActive = snap.session_active;
  };
  es.onerror = () => {
    $("conn").classList.remove("on", "live");
    $("conn-text").textContent = t("connLost");
  };
}

// --- Session list --------------------------------------------------------

async function loadSessions() {
  sessions = await (await fetch("/api/sessions")).json();
  const ul = $("sessions");
  ul.innerHTML = "";
  $("sessions-empty").hidden = sessions.length > 0;
  for (const s of sessions) {
    const li = document.createElement("li");
    li.dataset.id = s.session_id;
    li.dataset.cmpLabel = t("inCompare");
    li.classList.toggle("sel", s.session_id === selected);
    li.classList.toggle("cmp", compareSet.has(s.session_id));
    li.innerHTML = `
      <span class="when">${fmtWhen(s.session_id, s.started_at)}</span>
      <span class="dist">${Math.round(s.distance_m)} m</span>
      <span class="sub">${fmtDur(s.duration_s)} · ${fmtSplit(s.avg_speed_ms)} /500 m · ${Math.round(s.avg_spm)} spm${s.ended_at ? "" : " · " + t("open")}</span>
      <canvas class="spark" height="22"></canvas>`;
    li.onclick = () => selectSession(s.session_id);
    ul.appendChild(li);
    drawSpark(li.querySelector(".spark"), s.sparkline || []);
  }
  renderTrend();
  if (!selected && sessions.length) selectSession(sessions[0].session_id);
}

function drawSpark(canvas, vals) {
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.clientWidth || 200, H = 22;
  canvas.width = W * dpr; canvas.height = H * dpr;
  const ctx = canvas.getContext("2d"); ctx.scale(dpr, dpr);
  if (vals.length < 2) return;
  const max = Math.max(...vals) || 1;
  ctx.strokeStyle = THEME.series[0]; ctx.globalAlpha = 0.55; ctx.lineWidth = 1.5; ctx.beginPath();
  vals.forEach((v, i) => {
    const x = (i / (vals.length - 1)) * W, y = H - 2 - (v / max) * (H - 4);
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.stroke();
}

async function selectSession(id) {
  selected = id;
  document.querySelectorAll("#sessions li").forEach((li) => li.classList.toggle("sel", li.dataset.id === id));

  const { session: s, samples } = await getSession(id);
  $("detail").hidden = false;
  $("detail-title").textContent = fmtWhen(s.session_id, s.started_at);
  $("csv").href = `/api/sessions/${id}/export.csv`;
  $("xlsx").href = `/api/sessions/${id}/export.xlsx`;
  $("cmp-toggle").checked = compareSet.has(id);

  const speeds = samples.map((x) => x.speed_ms), spms = samples.map((x) => x.stroke_rate);
  const maxSpeed = Math.max(0, ...speeds.filter((v) => v != null));
  $("facts").innerHTML = [
    [t("fDistance"), `${Math.round(s.distance_m)} m`, true],
    [t("fDuration"), fmtDur(s.duration_s), true],
    [t("fSplit"), fmtSplit(s.avg_speed_ms), true],
    [t("fAvgSpeed"), `${Number(s.avg_speed_ms).toFixed(2)} m/s`],
    [t("fPeak"), `${maxSpeed.toFixed(2)} m/s`],
    [t("fAvgSpm"), `${Math.round(s.avg_spm)} spm`],
    [t("fStrokes"), s.strokes],
    [t("fMeterPerStroke"), s.strokes ? (s.distance_m / s.strokes).toFixed(1) : "–"],
  ].map(([k, v, lead]) => `<div${lead ? ' class="lead"' : ""}><dt>${k}</dt><dd>${v}</dd></div>`).join("");

  const t0 = samples.length ? samples[0].ts : 0;
  const rel = samples.map((x) => x.ts - t0);
  drawLine($("ch-speed"), [
    { x: rel, y: speeds, color: THEME.series[0], width: 1, fill: true, ghost: true },
    { x: rel, y: smooth(speeds), color: THEME.series[0], width: 2.5 },
  ], { yFmt: (v) => v.toFixed(1), avg: avg(speeds), readout: $("ro-speed"),
       fmt: (t, v) => `${fmtDur(t)} · ${v.toFixed(2)} m/s · ${fmtSplit(v)} /500 m` });
  drawLine($("ch-spm"), [
    { x: rel, y: spms, color: THEME.series[2], width: 2, step: true },
  ], { yFmt: (v) => Math.round(v), yMin: 0, readout: $("ro-spm"),
       fmt: (t, v) => `${fmtDur(t)} · ${Math.round(v)} spm` });
  renderTrend();
}

$("del").onclick = async () => {
  if (!selected || !confirm(t("confirmDelete"))) return;
  await fetch(`/api/sessions/${selected}`, { method: "DELETE" });
  compareSet.delete(selected); cache.delete(selected);
  selected = null;
  $("detail").hidden = true;
  await loadSessions();
  renderCompare();
};

// --- Comparison ----------------------------------------------------------

$("cmp-toggle").onchange = (e) => {
  if (!selected) return;
  if (e.target.checked && compareSet.size >= 4) { e.target.checked = false; alert(t("maxCompare")); return; }
  e.target.checked ? compareSet.add(selected) : compareSet.delete(selected);
  document.querySelectorAll("#sessions li").forEach((li) => li.classList.toggle("cmp", compareSet.has(li.dataset.id)));
  renderCompare();
};
$("cmp-clear").onclick = () => {
  compareSet.clear();
  $("cmp-toggle").checked = false;
  document.querySelectorAll("#sessions li").forEach((li) => li.classList.remove("cmp"));
  renderCompare();
};

async function renderCompare() {
  const box = $("compare");
  if (compareSet.size < 2) { box.hidden = true; return; }
  box.hidden = false;

  const rows = [];
  for (const id of compareSet) rows.push(await getSession(id));

  const series = rows.map((d, i) => {
    const t0 = d.samples.length ? d.samples[0].ts : 0;
    return { x: d.samples.map((s) => s.ts - t0), y: smooth(d.samples.map((s) => s.speed_ms)), color: THEME.series[i], width: 2 };
  });
  $("legend").innerHTML = rows.map((d, i) =>
    `<li><i style="background:${THEME.series[i]}"></i>${fmtWhen(d.session.session_id, d.session.started_at)}</li>`).join("");
  drawLine($("ch-cmp"), series, { yFmt: (v) => v.toFixed(1), readout: $("ro-cmp"),
    fmt: (t, v) => `${fmtDur(t)} · ${v.toFixed(2)} m/s` });

  const metrics = [
    [t("fDistance"), (s) => Math.round(s.distance_m), (v) => `${v} m`, "max"],
    [t("fDuration"), (s) => s.duration_s, fmtDur, "max"],
    [t("fSplit"), (s) => s.avg_speed_ms, fmtSplit, "max"],
    [t("fAvgSpeed"), (s) => s.avg_speed_ms, (v) => `${v.toFixed(2)} m/s`, "max"],
    [t("fAvgSpm"), (s) => s.avg_spm, (v) => `${Math.round(v)} spm`, null],
    [t("fStrokes"), (s) => s.strokes, (v) => v, "max"],
    [t("fMeterPerStroke"), (s) => (s.strokes ? s.distance_m / s.strokes : 0), (v) => v.toFixed(1), "max"],
  ];
  const head = `<thead><tr><th></th>${rows.map((d, i) => `<th><i class="sw" style="background:${THEME.series[i]}"></i>${fmtWhen(d.session.session_id, d.session.started_at)}</th>`).join("")}</tr></thead>`;
  const body = metrics.map(([label, get, fmt, best]) => {
    const vals = rows.map((d) => get(d.session));
    const bestVal = best === "max" ? Math.max(...vals) : null;
    return `<tr><td>${label}</td>${vals.map((v) => `<td${best && v === bestVal ? ' class="best"' : ""}>${fmt(v)}</td>`).join("")}</tr>`;
  }).join("");
  $("cmp-table").innerHTML = head + `<tbody>${body}</tbody>`;
}

// --- Trend across all sessions --------------------------------------------

function renderTrend() {
  const box = $("trend");
  if (sessions.length < 2) { box.hidden = true; return; }
  box.hidden = false;
  const chrono = [...sessions].reverse();
  const total = sessions.reduce((a, s) => a + s.distance_m, 0);
  const totalT = sessions.reduce((a, s) => a + s.duration_s, 0);
  $("trend-sum").textContent = t("trendSum", sessions.length, fmtInt(total), fmtDur(totalT));
  drawBars($("ch-trend"), chrono.map((s) => ({
    v: s.distance_m, label: fmtDay(s.started_at), id: s.session_id,
    tip: `${fmtWhen(s.session_id, s.started_at)} · ${Math.round(s.distance_m)} m · ${fmtSplit(s.avg_speed_ms)} /500 m`,
  })), { readout: $("ro-trend") });
}

// --- Drawing --------------------------------------------------------------

function setupCanvas(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.clientWidth;
  // The height attribute is the desktop maximum, but it gets overwritten
  // with device pixels below - so remember it on first use. Reading it
  // back instead multiplied the height by the pixel ratio on every
  // redraw, which is what stretched the charts on phones.
  if (!canvas.dataset.baseHeight) canvas.dataset.baseHeight = canvas.getAttribute("height");
  const maxH = Number(canvas.dataset.baseHeight);
  // On a narrow screen the chart keeps its aspect ratio instead of
  // turning into a tall box.
  const aspect = Number(canvas.dataset.aspect || 0);
  const H = aspect
    ? Math.round(Math.min(maxH, Math.max(Number(canvas.dataset.minHeight || maxH), W / aspect)))
    : maxH;
  canvas.width = W * dpr; canvas.height = H * dpr;
  canvas.style.height = H + "px";
  const ctx = canvas.getContext("2d"); ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, W, H);
  return { ctx, W, H };
}

function drawLine(canvas, series, opts = {}) {
  const { ctx, W, H } = setupCanvas(canvas);
  const pad = { l: 40, r: 12, t: 12, b: 24 };
  const allX = series.flatMap((s) => s.x), allY = series.flatMap((s) => s.y).filter((v) => v != null);
  if (!allX.length || !allY.length) {
    ctx.fillStyle = THEME.muted; ctx.font = "13px system-ui"; ctx.fillText(t("noSamples"), pad.l, H / 2);
    canvas.onmousemove = canvas.onmouseleave = null; return;
  }
  const xMax = Math.max(...allX, 1);
  const yMin = opts.yMin ?? 0, yMax = Math.max(...allY) * 1.08 || 1;
  const sx = (x) => pad.l + (x / xMax) * (W - pad.l - pad.r);
  const sy = (y) => H - pad.b - ((y - yMin) / (yMax - yMin)) * (H - pad.t - pad.b);

  const base = () => {
    ctx.clearRect(0, 0, W, H);
    ctx.strokeStyle = THEME.grid; ctx.lineWidth = 1;
    ctx.fillStyle = THEME.muted; ctx.font = "11px system-ui"; ctx.textAlign = "right";
    const rows = H < 150 ? 3 : 4;
    for (let i = 0; i <= rows; i++) {
      const y = yMin + ((yMax - yMin) / rows) * i;
      ctx.beginPath(); ctx.moveTo(pad.l, sy(y)); ctx.lineTo(W - pad.r, sy(y)); ctx.stroke();
      ctx.fillText(opts.yFmt ? opts.yFmt(y) : y, pad.l - 6, sy(y) + 4);
    }
    ctx.textAlign = "center";
    // As many time labels as fit without colliding, on a round step.
    const maxLabels = Math.max(2, Math.floor((W - pad.l - pad.r) / 58));
    const steps = [15, 30, 60, 120, 300, 600, 900, 1800, 3600];
    const step = steps.find((s) => xMax / s <= maxLabels) || 3600;
    for (let x = 0; x <= xMax; x += step) ctx.fillText(fmtDur(x), sx(x), H - 6);

    for (const s of series) {
      ctx.save();
      if (s.ghost) ctx.globalAlpha = 0.45;   // raw trace behind its smoothed line
      if (s.fill) {
        ctx.fillStyle = s.color + "33"; ctx.beginPath(); ctx.moveTo(sx(s.x[0]), sy(yMin));
        s.x.forEach((x, i) => { if (s.y[i] != null) ctx.lineTo(sx(x), sy(s.y[i])); });
        ctx.lineTo(sx(s.x[s.x.length - 1]), sy(yMin)); ctx.closePath(); ctx.fill();
      }
      ctx.strokeStyle = s.color; ctx.lineWidth = s.width || 1.8; ctx.lineJoin = "round"; ctx.beginPath();
      let prev = null;
      s.x.forEach((x, i) => {
        const y = s.y[i];
        if (y == null) { prev = null; return; }
        if (prev == null) ctx.moveTo(sx(x), sy(y));
        else if (s.step) { ctx.lineTo(sx(x), sy(prev)); ctx.lineTo(sx(x), sy(y)); }
        else ctx.lineTo(sx(x), sy(y));
        prev = y;
      });
      ctx.stroke();
      ctx.restore();
    }
    if (opts.avg) {
      ctx.strokeStyle = THEME.ink; ctx.setLineDash([4, 4]); ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(pad.l, sy(opts.avg)); ctx.lineTo(W - pad.r, sy(opts.avg)); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = THEME.ink; ctx.textAlign = "left"; ctx.font = "10px system-ui";
      ctx.fillText(`${t("avg")} ${opts.yFmt ? opts.yFmt(opts.avg) : opts.avg}`, pad.l + 4, sy(opts.avg) - 4);
    }
  };
  base();

  const top = series[series.length - 1];
  canvas.onmousemove = (e) => {
    const rect = canvas.getBoundingClientRect();
    const t = ((e.clientX - rect.left - pad.l) / (W - pad.l - pad.r)) * xMax;
    if (t < 0 || t > xMax) return;
    let idx = 0;
    while (idx < top.x.length - 1 && top.x[idx + 1] < t) idx++;
    const v = top.y[idx];
    base();
    ctx.strokeStyle = THEME.ink; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(sx(t), pad.t); ctx.lineTo(sx(t), H - pad.b); ctx.stroke();
    if (v != null) { ctx.fillStyle = top.color; ctx.beginPath(); ctx.arc(sx(top.x[idx]), sy(v), 4, 0, Math.PI * 2); ctx.fill(); }
    if (opts.readout) opts.readout.textContent = v != null && opts.fmt ? opts.fmt(top.x[idx], v) : "";
  };
  canvas.onmouseleave = () => { base(); if (opts.readout) opts.readout.textContent = ""; };
}

function drawBars(canvas, items, opts = {}) {
  const { ctx, W, H } = setupCanvas(canvas);
  const pad = { l: 40, r: 12, t: 12, b: 24 };
  const max = Math.max(...items.map((i) => i.v), 1) * 1.08;
  const n = items.length, slot = (W - pad.l - pad.r) / n, bw = Math.min(28, slot * 0.7);
  const sy = (v) => H - pad.b - (v / max) * (H - pad.t - pad.b);

  const base = (hi = -1) => {
    ctx.clearRect(0, 0, W, H);
    ctx.strokeStyle = THEME.grid; ctx.lineWidth = 1; ctx.fillStyle = THEME.muted; ctx.font = "11px system-ui"; ctx.textAlign = "right";
    const rows = H < 120 ? 2 : 3;
    for (let i = 0; i <= rows; i++) {
      const v = (max / rows) * i;
      ctx.beginPath(); ctx.moveTo(pad.l, sy(v)); ctx.lineTo(W - pad.r, sy(v)); ctx.stroke();
      ctx.fillText(Math.round(v), pad.l - 6, sy(v) + 4);
    }
    ctx.textAlign = "center";
    const every = Math.ceil(n / Math.max(1, Math.floor((W - pad.l) / 50)));
    items.forEach((it, i) => {
      const x = pad.l + slot * i + slot / 2;
      ctx.fillStyle = i === hi ? THEME.ink : it.id === selected ? THEME.accent : THEME.series[0];
      const top = sy(it.v), h = H - pad.b - top;
      ctx.beginPath();
      if (ctx.roundRect) ctx.roundRect(x - bw / 2, top, bw, h, [4, 4, 0, 0]);
      else ctx.rect(x - bw / 2, top, bw, h);
      ctx.fill();
      if (i % every === 0) { ctx.fillStyle = THEME.muted; ctx.fillText(it.label, x, H - 6); }
    });
  };
  base();
  canvas.onmousemove = (e) => {
    const rect = canvas.getBoundingClientRect();
    const i = Math.floor((e.clientX - rect.left - pad.l) / slot);
    if (i < 0 || i >= n) { base(); if (opts.readout) opts.readout.textContent = ""; return; }
    base(i);
    if (opts.readout) opts.readout.textContent = items[i].tip;
  };
  canvas.onmouseleave = () => { base(); if (opts.readout) opts.readout.textContent = ""; };
  canvas.onclick = (e) => {
    const rect = canvas.getBoundingClientRect();
    const i = Math.floor((e.clientX - rect.left - pad.l) / slot);
    if (i >= 0 && i < n) selectSession(items[i].id);
  };
}

let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);           // chart heights depend on width now
  resizeTimer = setTimeout(redrawCharts, 200);
});

window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", async () => {
  if (theme !== "auto") return;
  readTheme();
  await redrawCharts();
});

// --- Settings ------------------------------------------------------------

const settingsBox = $("settings"), settingsForm = $("settings-form"), settingsMsg = $("settings-msg");

function showSettings(open) {
  settingsBox.hidden = !open;
  $("conn").setAttribute("aria-expanded", String(open));
}
$("conn").onclick = () => showSettings(settingsBox.hidden);

async function loadSettings() {
  const s = await (await fetch("/api/settings")).json();
  for (const k of ["host", "port", "username", "password", "prefix"]) settingsForm.elements[k].value = s[k] ?? "";
  if (s.error) { settingsMsg.textContent = s.error; settingsMsg.className = "form-msg err"; }
  if (!s.host || (!s.connected && s.error)) showSettings(true);
}

settingsForm.onsubmit = async (e) => {
  e.preventDefault();
  const body = Object.fromEntries(new FormData(settingsForm));
  body.port = Number(body.port) || 1883;
  settingsMsg.textContent = t("formConnecting"); settingsMsg.className = "form-msg";
  const r = await fetch("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) { settingsMsg.textContent = (await r.json()).detail || t("saveFailed"); settingsMsg.className = "form-msg err"; return; }
  await new Promise((res) => setTimeout(res, 2500));
  const s = await (await fetch("/api/settings")).json();
  if (s.connected) { settingsMsg.textContent = t("formConnected"); settingsMsg.className = "form-msg ok"; setTimeout(() => showSettings(false), 1200); }
  else { settingsMsg.textContent = s.error || t("noConnection"); settingsMsg.className = "form-msg err"; }
};

// --- Arena uplink ----------------------------------------------------------

const arenaForm = $("arena-form"), arenaMsg = $("arena-msg");

function renderArena(s) {
  const pill = $("arena-pill");
  pill.hidden = !s.url;
  pill.classList.toggle("usb", s.connected);
  pill.classList.toggle("on", s.enabled && !s.connected);
  $("arena-text").textContent = !s.enabled ? t("arenaIdle")
    : s.connected ? t("arenaOn", s.athlete) : t("arenaOff");
  pill.title = s.error || "";
}

async function loadArena() {
  const s = await (await fetch("/api/arena")).json();
  arenaForm.elements.arena_url.value = s.url || "";
  // The token is write-only: the server never hands it back, so a set one
  // is shown as dots and left alone unless it is typed over.
  arenaForm.elements.arena_token.value = s.token_set ? "••••••" : "";
  arenaForm.elements.arena_enabled.checked = !!s.enabled;
  renderArena(s);
}

arenaForm.onsubmit = async (e) => {
  e.preventDefault();
  const f = arenaForm.elements;
  const body = {
    arena_url: f.arena_url.value.trim(),
    arena_token: f.arena_token.value,
    arena_enabled: f.arena_enabled.checked,
  };
  arenaMsg.className = "form-msg"; arenaMsg.textContent = "";
  const r = await fetch("/api/arena", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!r.ok) {
    arenaMsg.textContent = (await r.json()).detail || t("saveFailed");
    arenaMsg.className = "form-msg err";
    return;
  }
  arenaMsg.textContent = t("formConnecting");
  await new Promise((res) => setTimeout(res, 2500));
  const s = await (await fetch("/api/arena")).json();
  renderArena(s);
  arenaMsg.className = s.connected ? "form-msg ok" : "form-msg err";
  arenaMsg.textContent = s.connected ? t("formConnected") : (s.error || t("noConnection"));
};

// --- Firmware --------------------------------------------------------------

const fwForm = $("fw-form"), fwMsg = $("fw-msg");

function renderFirmware(f) {
  $("fw-running").textContent = f.running || t("fwUnknown");
  $("fw-expected").textContent = f.expected || "–";
  const open = $("fw-open");
  open.hidden = !f.url;
  if (f.url) open.href = f.url;

  /* One line, and only when it says something. A match is worth confirming
     once; a mismatch is not an error, because running last month's firmware
     on purpose is a normal thing to do. */
  const note = $("fw-note");
  let text = "", cls = "fw-note";
  if (f.url && f.reachable === false) {
    text = t("fwUnreachable"); cls += " warn";
  } else if (f.running && f.expected && f.running !== "dev" && f.expected !== "dev") {
    const same = f.running === f.expected;
    text = same ? t("fwMatch") : t("fwDiffer");
    cls += same ? " ok" : " warn";
  }
  note.className = cls;
  note.textContent = text;
  note.hidden = !text;

  renderConfigs(f);
}

/* The picker: whatever the tracker can offer, with the one that shipped
   with this release first. It is the one that matches - no checkout, no
   copying a file out of GitHub by hand. */
function renderConfigs(f) {
  const sel = $("fw-config");
  const had = sel.value;
  sel.textContent = "";
  (f.configs || []).forEach((c) => {
    const o = new Option(c.shipped ? `${c.name} · ${t("fwShipped", f.expected)}` : c.label,
                         c.source);
    sel.appendChild(o);
  });
  if (had && [...sel.options].some((o) => o.value === had)) sel.value = had;
  sel.disabled = !sel.options.length;

  const dl = $("fw-download");
  dl.href = `/api/firmware/yaml?source=${encodeURIComponent(sel.value || "shipped")}`;
  sel.onchange = () => {
    dl.href = `/api/firmware/yaml?source=${encodeURIComponent(sel.value)}`;
  };

  /* Writing needs the folder shared with the other container. Say so once,
     here, instead of letting the button fail with a shrug. */
  $("fw-install").disabled = !f.config_dir_ok;
  const msg = $("fw-yaml-msg");
  if (!f.config_dir_ok) {
    msg.className = "fw-note warn";
    msg.textContent = t("fwNoDir", f.config_dir || "/esphome");
    msg.hidden = false;
  } else if (!msg.dataset.sticky) {
    msg.hidden = true;
  }
}

async function installYaml(body) {
  const msg = $("fw-yaml-msg");
  const r = await fetch("/api/firmware/yaml", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (r.status === 409 && !body.overwrite) {
    if (confirm(t("fwExists", body.name))) return installYaml({ ...body, overwrite: true });
    return;
  }
  msg.dataset.sticky = "1";
  msg.hidden = false;
  if (!r.ok) {
    msg.className = "fw-note warn";
    msg.textContent = data.detail || t("saveFailed");
    return;
  }
  msg.className = "fw-note ok";
  msg.textContent = t("fwWrote", body.name);
  renderFirmware(data);
}

$("fw-install").onclick = () => {
  const source = $("fw-config").value || "shipped";
  installYaml({ source, name: source === "shipped" ? "waterrower.yaml" : source });
};

$("fw-file").onchange = async (e) => {
  const file = e.target.files && e.target.files[0];
  if (!file) return;
  const content = await file.text();
  e.target.value = "";                 // so the same file can be picked again
  await installYaml({ source: "upload", name: file.name, content });
};

async function loadFirmware() {
  try {
    const f = await (await fetch("/api/firmware")).json();
    fwForm.elements.esphome_url.value = f.url || "";
    renderFirmware(f);
  } catch {}
}

fwForm.onsubmit = async (e) => {
  e.preventDefault();
  fwMsg.className = "form-msg"; fwMsg.textContent = "";
  const r = await fetch("/api/firmware", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ esphome_url: fwForm.elements.esphome_url.value.trim() }),
  });
  if (!r.ok) {
    fwMsg.textContent = t("saveFailed");
    fwMsg.className = "form-msg err";
    return;
  }
  renderFirmware(await r.json());
  fwMsg.className = "form-msg ok";
  fwMsg.textContent = t("formSaved");
};

/* Status only - never the input fields, or it would overwrite what is being
   typed while the panel is open. */
async function pollArena() {
  try { renderArena(await (await fetch("/api/arena")).json()); } catch {}
}
setInterval(pollArena, 15000);

// --- Version footer --------------------------------------------------------

const REPO = "https://github.com/MojoOne1/waterrower-mqtt";
let appVersion = null;

function renderFooter() {
  if (!appVersion) return;
  const parts = [];
  const commit = /^[0-9a-f]{7,40}$/.test(appVersion.commit)
    ? `<a href="${REPO}/commit/${appVersion.commit}" target="_blank" rel="noopener">${appVersion.commit.slice(0, 7)}</a>`
    : appVersion.commit;
  parts.push(`Tracker v${appVersion.version} · ${commit}`);
  const fw = lastSnap?.values?.firmware_version;
  if (fw) parts.push(`Firmware v${fw}`);
  $("foot").innerHTML = parts.join(" &nbsp;·&nbsp; ");
}

async function loadVersion() {
  appVersion = await (await fetch("/api/version")).json();
  renderFooter();
}

// --- Start ---------------------------------------------------------------
applyTheme();
applyLang();
connectStream();
loadSessions();
loadSettings();
loadArena();
loadFirmware();
loadVersion();
