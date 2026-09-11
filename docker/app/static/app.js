/* WaterRower Tracker - UI (no dependencies) */

const $ = (id) => document.getElementById(id);
const COLORS = ["#2a2d31", "#c8a878", "#5f8a4e", "#6b7a99"];
const OLIVE = "#a6ad84";

let sessions = [];
let selected = null;
let compareSet = new Set();
let lastSnap = null;
const cache = new Map();   // session_id -> {session, samples}

// --- Language ------------------------------------------------------------

const I18N = {
  de: {
    locale: "de-DE",
    connecting: "verbinde …", connOff: "nicht verbunden", connOn: "verbunden", connLive: "Aufzeichnung läuft",
    connLost: "Verbindung verloren, versuche erneut …",
    s4Unknown: "Ergometer: unbekannt", s4Off: "Ergometer aus", s4On: "Ergometer an", s4Usb: "Ergometer verbunden",
    settingsTitle: "Verbindung zum MQTT-Broker",
    labelHost: "Adresse", labelPort: "Port", labelUser: "Benutzer", labelPassword: "Passwort", labelPrefix: "Topic-Präfix",
    phHost: "10.0.0.5 oder broker.local", phOptional: "optional",
    settingsHint: "Der Präfix muss zu <code>topic_prefix</code> in der ESPHome-Konfiguration passen.",
    btnConnect: "Verbinden", formConnecting: "Verbinde …", formConnected: "Verbunden",
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
    allSessions: "Alle Einheiten", chartTrend: "Distanz je Einheit",
    trendSum: (n, m, dur) => `${n} Einheiten · ${m} m · ${dur} gesamt`,
    noSamples: "Keine Messpunkte", avg: "Ø",
    endSession: "Einheit beenden", confirmEnd: "Diese Einheit jetzt beenden und den Monitor zurücksetzen?", endFailed: "Beenden fehlgeschlagen",
    fDistance: "Distanz", fDuration: "Dauer", fSplit: "Ø 500 m", fAvgSpeed: "Ø Geschwindigkeit", fPeak: "Spitze",
    fAvgSpm: "Ø Schlagfrequenz", fStrokes: "Schläge", fMeterPerStroke: "Meter je Schlag",
  },
  en: {
    locale: "en-GB",
    connecting: "connecting …", connOff: "not connected", connOn: "connected", connLive: "recording",
    connLost: "Connection lost, retrying …",
    s4Unknown: "Ergometer: unknown", s4Off: "Ergometer off", s4On: "Ergometer on", s4Usb: "Ergometer connected",
    settingsTitle: "MQTT broker connection",
    labelHost: "Address", labelPort: "Port", labelUser: "Username", labelPassword: "Password", labelPrefix: "Topic prefix",
    phHost: "10.0.0.5 or broker.local", phOptional: "optional",
    settingsHint: "The prefix must match <code>topic_prefix</code> in the ESPHome configuration.",
    btnConnect: "Connect", formConnecting: "Connecting …", formConnected: "Connected",
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
    allSessions: "All sessions", chartTrend: "Distance per session",
    trendSum: (n, m, dur) => `${n} sessions · ${m} m · ${dur} total`,
    noSamples: "No samples", avg: "avg",
    endSession: "End session", confirmEnd: "End this session now and reset the monitor?", endFailed: "Could not end the session",
    fDistance: "Distance", fDuration: "Duration", fSplit: "Avg 500 m", fAvgSpeed: "Avg speed", fPeak: "Peak",
    fAvgSpm: "Avg stroke rate", fStrokes: "Strokes", fMeterPerStroke: "Metres per stroke",
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
  await loadSessions();
  if (selected) await selectSession(selected);
  renderCompare();
}
document.querySelectorAll(".lang button").forEach((b) => { b.onclick = () => setLang(b.dataset.lang); });

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

function renderLive(snap) {
  lastSnap = snap;
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

$("end").onclick = async () => {
  if (!confirm(t("confirmEnd"))) return;
  const r = await fetch("/api/session/end", { method: "POST" });
  if (!r.ok) alert((await r.json()).detail || t("endFailed"));
};

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
  ctx.strokeStyle = OLIVE; ctx.lineWidth = 1.5; ctx.beginPath();
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
    { x: rel, y: speeds, color: OLIVE, width: 1, fill: true },
    { x: rel, y: smooth(speeds), color: COLORS[0], width: 2 },
  ], { yFmt: (v) => v.toFixed(1), avg: avg(speeds), readout: $("ro-speed"),
       fmt: (t, v) => `${fmtDur(t)} · ${v.toFixed(2)} m/s · ${fmtSplit(v)} /500 m` });
  drawLine($("ch-spm"), [
    { x: rel, y: spms, color: COLORS[2], width: 1.5, step: true },
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
    return { x: d.samples.map((s) => s.ts - t0), y: smooth(d.samples.map((s) => s.speed_ms)), color: COLORS[i], width: 2 };
  });
  $("legend").innerHTML = rows.map((d, i) =>
    `<li><i style="background:${COLORS[i]}"></i>${fmtWhen(d.session.session_id, d.session.started_at)}</li>`).join("");
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
  const head = `<thead><tr><th></th>${rows.map((d, i) => `<th><i class="sw" style="background:${COLORS[i]}"></i>${fmtWhen(d.session.session_id, d.session.started_at)}</th>`).join("")}</tr></thead>`;
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
  const H = Number(canvas.getAttribute("height"));
  const W = canvas.clientWidth;
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
    ctx.fillStyle = "#70746b"; ctx.font = "13px system-ui"; ctx.fillText(t("noSamples"), pad.l, H / 2);
    canvas.onmousemove = canvas.onmouseleave = null; return;
  }
  const xMax = Math.max(...allX, 1);
  const yMin = opts.yMin ?? 0, yMax = Math.max(...allY) * 1.08 || 1;
  const sx = (x) => pad.l + (x / xMax) * (W - pad.l - pad.r);
  const sy = (y) => H - pad.b - ((y - yMin) / (yMax - yMin)) * (H - pad.t - pad.b);

  const base = () => {
    ctx.clearRect(0, 0, W, H);
    ctx.strokeStyle = "#e0e2da"; ctx.lineWidth = 1;
    ctx.fillStyle = "#70746b"; ctx.font = "11px system-ui"; ctx.textAlign = "right";
    for (let i = 0; i <= 4; i++) {
      const y = yMin + ((yMax - yMin) / 4) * i;
      ctx.beginPath(); ctx.moveTo(pad.l, sy(y)); ctx.lineTo(W - pad.r, sy(y)); ctx.stroke();
      ctx.fillText(opts.yFmt ? opts.yFmt(y) : y, pad.l - 6, sy(y) + 4);
    }
    ctx.textAlign = "center";
    const step = xMax > 1800 ? 600 : xMax > 600 ? 300 : xMax > 120 ? 60 : 30;
    for (let x = 0; x <= xMax; x += step) ctx.fillText(fmtDur(x), sx(x), H - 6);

    for (const s of series) {
      if (s.fill) {
        ctx.fillStyle = s.color + "55"; ctx.beginPath(); ctx.moveTo(sx(s.x[0]), sy(yMin));
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
    }
    if (opts.avg) {
      ctx.strokeStyle = "#2a2d31"; ctx.setLineDash([4, 4]); ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(pad.l, sy(opts.avg)); ctx.lineTo(W - pad.r, sy(opts.avg)); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "#2a2d31"; ctx.textAlign = "left"; ctx.font = "10px system-ui";
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
    ctx.strokeStyle = "#2a2d31"; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(sx(t), pad.t); ctx.lineTo(sx(t), H - pad.b); ctx.stroke();
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
    ctx.strokeStyle = "#e0e2da"; ctx.lineWidth = 1; ctx.fillStyle = "#70746b"; ctx.font = "11px system-ui"; ctx.textAlign = "right";
    for (let i = 0; i <= 3; i++) {
      const v = (max / 3) * i;
      ctx.beginPath(); ctx.moveTo(pad.l, sy(v)); ctx.lineTo(W - pad.r, sy(v)); ctx.stroke();
      ctx.fillText(Math.round(v), pad.l - 6, sy(v) + 4);
    }
    ctx.textAlign = "center";
    const every = Math.ceil(n / Math.max(1, Math.floor((W - pad.l) / 50)));
    items.forEach((it, i) => {
      const x = pad.l + slot * i + slot / 2;
      ctx.fillStyle = i === hi ? "#2a2d31" : it.id === selected ? "#c8a878" : OLIVE;
      ctx.fillRect(x - bw / 2, sy(it.v), bw, H - pad.b - sy(it.v));
      if (i % every === 0) { ctx.fillStyle = "#70746b"; ctx.fillText(it.label, x, H - 6); }
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

window.addEventListener("resize", () => { if (selected) selectSession(selected); renderCompare(); });

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
applyLang();
connectStream();
loadSessions();
loadSettings();
loadVersion();
