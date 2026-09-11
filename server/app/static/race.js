/* The race view: lobby, countdown, lanes, result.

   The server ticks twice a second, which is plenty for the lanes. Only the
   countdown runs on a local clock - a number counting down in half-second
   jumps would look broken. */

let countdownTimer = null;
let countdownEnd = 0;

VIEWS.race = async function raceView() {
  onLive = () => {};
  onData = () => {};
  onRace = () => { paintRace(); };
  paintRace();
  await paintHistory();
};

function raceLabel(r) {
  if (!r) return "";
  if (r.mode === "distance") return `${fmtInt(r.target)} m`;
  if (r.mode === "time") return fmtDur(r.target);
  return t("modeFree");
}

function isHost(r) {
  return STATE.me && (r.created_by === STATE.me.id || STATE.me.is_admin);
}

function myLane(r) {
  return r.lanes.find((l) => l.kind === "live" && l.athlete_id === STATE.me.id);
}

async function raceAction(path, body) {
  try {
    await api(path, { method: "POST", body: body || {} });
  } catch (err) {
    alert(err.message);
  }
}

function paintRace() {
  const host = $("race-live");
  if (!host) return;
  const r = STATE.race;
  stopCountdown();
  host.innerHTML = "";
  const newHost = $("race-new");
  if (newHost) newHost.innerHTML = "";

  if (!r || r.state === "aborted") {
    paintNewRaceForm();
    paintTemplates();
    return;
  }
  if (r.state === "lobby") return paintLobby(host, r);
  if (r.state === "countdown") return paintCountdown(host, r);
  if (r.state === "running") return paintRunning(host, r);
  if (r.state === "finished") return paintResult(host, r);
}

// --- Create ---------------------------------------------------------------

async function paintTemplates() {
  const host = $("race-new");
  if (!host) return;
  const templates = await api("/api/templates").catch(() => []);
  if (!templates.length || $("race-live").children.length) return;
  const box = el("section", "card");
  box.appendChild(el("h2", null, t("templates")));
  box.appendChild(el("p", "hint", t("templatesHint")));
  const list = el("div", "template-list");
  for (const tpl of templates) {
    const b = el("button", "template");
    b.type = "button";
    b.appendChild(el("strong", null, tpl.name));
    b.appendChild(el("span", "sub", raceLabel(tpl)));
    if (tpl.note) b.appendChild(el("span", "note", tpl.note));
    b.onclick = async () => {
      try {
        STATE.race = await api("/api/race", { method: "POST", body: { template_id: tpl.id } });
        paintRace();
      } catch (err) {
        alert(err.status === 409 ? t("raceBusy") : err.message);
      }
    };
    list.appendChild(b);
  }
  box.appendChild(list);
  host.insertBefore(box, host.firstChild);
}

function paintNewRaceForm() {
  const host = $("race-new");
  if (!host) return;
  const form = el("form", "card");
  form.appendChild(el("h2", null, t("ownRace")));

  const name = field(form, t("raceName"), "text");
  name.placeholder = lang === "de" ? "Dienstagabend" : "Tuesday night";

  const modeLabel = el("label");
  modeLabel.appendChild(el("span", null, t("raceMode")));
  const mode = el("select");
  [["distance", "modeDistance"], ["time", "modeTime"], ["free", "modeFree"]]
    .forEach(([v, key]) => mode.appendChild(new Option(t(key), v)));
  modeLabel.appendChild(mode);
  form.appendChild(modeLabel);

  const targetLabel = el("label");
  const targetUnit = el("span", null, `${t("raceTarget")} (${t("targetMetres")})`);
  targetLabel.appendChild(targetUnit);
  const target = el("input");
  target.type = "number";
  target.value = "2000";
  target.min = "100";
  targetLabel.appendChild(target);
  form.appendChild(targetLabel);

  const presets = el("div", "presets");
  const setPreset = (v) => () => { target.value = String(v); };
  const showPresets = () => {
    presets.innerHTML = "";
    if (mode.value === "free") return;
    const values = mode.value === "distance" ? [500, 1000, 2000, 5000] : [5, 10, 20, 30];
    values.forEach((v) => {
      const b = el("button", null, mode.value === "distance" ? `${fmtInt(v)} m` : `${v} min`);
      b.type = "button";
      b.onclick = setPreset(v);
      presets.appendChild(b);
    });
  };
  form.appendChild(presets);

  mode.onchange = () => {
    const free = mode.value === "free";
    targetLabel.hidden = free;
    targetUnit.textContent = `${t("raceTarget")} (${mode.value === "distance" ? t("targetMetres") : t("targetMinutes")})`;
    target.value = mode.value === "distance" ? "2000" : "10";
    showPresets();
  };
  showPresets();

  const foot = el("div", "form-foot");
  const msg = el("span", "form-msg");
  foot.appendChild(msg);
  const btn = el("button", "primary", t("btnCreate"));
  btn.type = "submit";
  foot.appendChild(btn);
  form.appendChild(foot);

  form.onsubmit = async (e) => {
    e.preventDefault();
    const value = Number(target.value) * (mode.value === "time" ? 60 : 1);
    try {
      STATE.race = await api("/api/race", {
        method: "POST",
        body: { name: name.value.trim(), mode: mode.value, target: mode.value === "free" ? 0 : value },
      });
      paintRace();
    } catch (err) {
      msg.className = "form-msg err";
      msg.textContent = err.status === 409 ? t("raceBusy") : err.message;
    }
  };
  host.appendChild(form);
}

// --- Lobby ----------------------------------------------------------------

function paintLobby(host, r) {
  const card = el("section", "card race-card");
  card.appendChild(el("h2", null, `${r.name || t("newRace")} · ${raceLabel(r)}`));
  card.appendChild(el("p", "hint", t("lobby")));

  const list = el("ul", "lanes lobby-lanes");
  for (const lane of r.lanes) {
    const li = el("li");
    li.style.setProperty("--lane", lane.color);
    li.appendChild(el("span", "sw"));
    li.appendChild(el("strong", null, lane.name));
    const live = STATE.live.get(lane.athlete_id) || {};
    if (lane.kind === "ghost") {
      li.appendChild(el("span", "tag", "ghost"));
    } else if (!live.online) {
      li.appendChild(el("span", "tag warn", t("offline")));
    }
    li.appendChild(el("span", lane.ready ? "tag ok" : "tag", lane.ready ? t("btnReady") : "…"));
    if (lane.athlete_id === STATE.me.id || isHost(r)) {
      const out = el("a", null, t("btnLeave"));
      out.href = "#";
      out.onclick = (e) => { e.preventDefault(); raceAction("/api/race/leave", { entry_id: lane.entry_id }); };
      li.appendChild(out);
    }
    list.appendChild(li);
  }
  card.appendChild(list);

  const live = r.lanes.filter((l) => l.kind === "live");
  card.appendChild(el("p", "hint",
    t("readyCount", live.filter((l) => l.ready).length, live.length)));

  const bar = el("div", "actions-bar");
  const mine = myLane(r);
  if (!mine && STATE.me.is_admin) {
    card.appendChild(el("p", "hint", t("adminNoRace")));
  } else if (!mine) {
    const join = el("button", "primary", t("btnJoinRace"));
    join.onclick = () => raceAction("/api/race/join");
    bar.appendChild(join);
  } else {
    const ready = el("button", mine.ready ? "" : "primary", mine.ready ? t("btnNotReady") : t("btnReady"));
    ready.onclick = () => raceAction("/api/race/ready", { ready: !mine.ready });
    bar.appendChild(ready);
  }

  const ghost = el("button", null, t("btnGhost"));
  ghost.onclick = () => pickGhost(card);
  bar.appendChild(ghost);

  if (isHost(r)) {
    const start = el("button", "primary", t("btnStart"));
    start.disabled = !live.length;
    start.onclick = () => raceAction("/api/race/start");
    bar.appendChild(start);
    const abort = el("button", null, t("btnAbort"));
    abort.onclick = () => raceAction("/api/race/abort");
    bar.appendChild(abort);
  }
  card.appendChild(bar);

  const offline = live.filter((l) => !(STATE.live.get(l.athlete_id) || {}).online);
  offline.forEach((l) => card.appendChild(el("p", "warn-line", t("needOnline", l.name))));

  host.appendChild(card);
}

async function pickGhost(card) {
  const old = card.querySelector(".ghost-pick");
  if (old) { old.remove(); return; }
  const box = el("div", "ghost-pick");
  box.appendChild(el("p", "hint", t("ghostPick")));
  const sessions = await api("/api/sessions?limit=60").catch(() => []);
  const usable = sessions.filter((s) => s.duration_s > 60 && s.distance_m > 200);
  if (!usable.length) {
    box.appendChild(el("p", "empty", t("ghostNone")));
  } else {
    const select = el("select");
    usable.forEach((s) => select.appendChild(new Option(
      `${s.display_name} · ${fmtDate(s.started_at)} · ${fmtMetres(s.distance_m)} · ${fmtDur(s.duration_s)}`,
      String(s.id))));
    box.appendChild(select);
    const add = el("button", "primary", t("btnGhost"));
    add.onclick = () => raceAction("/api/race/ghost", { session_id: Number(select.value) });
    box.appendChild(add);
  }
  card.appendChild(box);
}

// --- Countdown ------------------------------------------------------------

function stopCountdown() {
  if (countdownTimer) { clearInterval(countdownTimer); countdownTimer = null; }
}

function paintCountdown(host, r) {
  const card = el("section", "card race-card countdown");
  card.appendChild(el("h2", null, `${r.name || ""} ${raceLabel(r)}`.trim()));
  const big = el("div", "count", "–");
  card.appendChild(big);
  card.appendChild(el("p", "hint", t("resetHint")));
  const bar = el("div", "actions-bar");
  if (isHost(r)) {
    const abort = el("button", null, t("btnAbort"));
    abort.onclick = () => raceAction("/api/race/abort");
    bar.appendChild(abort);
  }
  card.appendChild(bar);
  host.appendChild(card);

  countdownEnd = Date.now() + (r.countdown_in || 0) * 1000;
  const tick = () => {
    const left = (countdownEnd - Date.now()) / 1000;
    big.textContent = left > 0 ? String(Math.ceil(left)) : t("go");
    big.classList.toggle("go", left <= 0);
  };
  tick();
  stopCountdown();
  countdownTimer = setInterval(tick, 100);
}

// --- Running --------------------------------------------------------------

function paintRunning(host, r) {
  const card = el("section", "card race-card");
  const head = el("div", "race-head");
  head.appendChild(el("h2", null, `${r.name || t("navRace")} · ${raceLabel(r)}`));
  const clock = el("div", "clock");
  if (r.mode === "time") {
    clock.textContent = fmtDur(Math.max(0, r.target - r.elapsed));
    clock.appendChild(el("span", "sub", t("toGo")));
  } else {
    clock.textContent = fmtTime(r.elapsed);
  }
  head.appendChild(clock);
  card.appendChild(head);

  const lanes = el("div", "lanes");
  const ordered = [...r.lanes].sort((a, b) => (b.progress - a.progress));
  ordered.forEach((lane, i) => lanes.appendChild(laneRow(r, lane, i + 1)));
  card.appendChild(lanes);

  if (isHost(r)) {
    const bar = el("div", "actions-bar");
    const end = el("button", null, t("btnEnd"));
    end.onclick = () => raceAction("/api/race/finish");
    bar.appendChild(end);
    card.appendChild(bar);
  }
  host.appendChild(card);
}

function laneRow(r, lane, pos) {
  const row = el("div", "lane" + (lane.finished ? " done" : "")
    + (lane.athlete_id === STATE.me.id && lane.kind === "live" ? " mine" : ""));
  row.style.setProperty("--lane", lane.color);

  const head = el("div", "lane-head");
  head.appendChild(el("span", "pos", String(lane.place || pos)));
  head.appendChild(el("strong", null, lane.name));
  if (lane.finished) {
    head.appendChild(el("span", "tag ok",
      lane.time_s != null ? fmtTime(lane.time_s) : t("finished")));
  } else if (lane.gap_m > 0) {
    head.appendChild(el("span", "gap",
      `−${fmtInt(lane.gap_m)} m${lane.gap_s ? ` · ${lane.gap_s.toFixed(1)} s` : ""} ${t("behind")}`));
  } else {
    head.appendChild(el("span", "gap lead", t("ahead")));
  }
  row.appendChild(head);

  const track = el("div", "track");
  const fill = el("div", "fill");
  const pct = r.mode === "distance"
    ? Math.min(100, (lane.progress / (r.target || 1)) * 100)
    : Math.min(100, (lane.progress / Math.max(1, maxProgress(r))) * 100);
  fill.style.width = pct + "%";
  track.appendChild(fill);
  const boat = el("span", "boat", "🚣");
  boat.style.left = pct + "%";
  track.appendChild(boat);
  row.appendChild(track);

  const stats = el("div", "lane-stats");
  const stat = (v, l) => {
    const d = el("div");
    d.appendChild(el("span", "val", v));
    d.appendChild(el("span", "lbl", l));
    stats.appendChild(d);
  };
  if (lane.finished) {
    // Live values would stay frozen at whatever they were on the line,
    // which reads as if they were still pulling 1:52 while rowing it out.
    // What the race produced is the honest answer, and it is already here.
    // The time itself is already the badge next to the name.
    stat(fmtMetres(lane.progress), t("colDistance"));
    stat(raceSplit(r, lane), "Ø 500 m");
    stat(lane.avg_spm ? lane.avg_spm.toFixed(1) : "–", "Ø s/min");
    stat(lane.avg_watts ? Math.round(lane.avg_watts) : "–", "Ø W");
  } else {
    stat(fmtMetres(lane.progress), t("colDistance"));
    stat(lane.split_500, "/500 m");
    stat(fmtInt(lane.spm), "s/min");
    stat(fmtInt(lane.watts), "W");
    if (r.mode === "distance" && lane.eta_s != null) stat(fmtDur(lane.eta_s), t("toGo"));
  }
  row.appendChild(stats);
  return row;
}

/* The average split over the race itself: what was rowed, over how long.
   A lane with no time of its own (did not finish a distance race) gets no
   split rather than one measured against the whole race. */
function raceSplit(r, lane) {
  const seconds = lane.time_s != null ? lane.time_s
    : (r.mode === "time" ? r.elapsed : null);
  const metres = lane.finished && r.mode === "distance" ? r.target : lane.progress;
  if (!metres || !seconds) return "--:--";
  return fmtSplit(metres / seconds);
}

function maxProgress(r) {
  return r.lanes.reduce((m, l) => Math.max(m, l.progress), 0);
}

// --- Result ---------------------------------------------------------------

function paintResult(host, r) {
  const card = el("section", "card race-card");
  card.appendChild(el("h2", null, `${t("results")} · ${r.name || ""} ${raceLabel(r)}`.trim()));

  const table = el("table", "table");
  const head = el("tr");
  [t("place"), " ", r.mode === "distance" ? t("colTime") : t("colDistance"),
   "Ø 500 m", "Ø s/min", "Ø W"]
    .forEach((h) => head.appendChild(el("th", null, h)));
  table.appendChild(el("thead")).appendChild(head);
  const body = el("tbody");
  const ordered = [...r.lanes].sort((a, b) => (a.place || 99) - (b.place || 99));
  for (const lane of ordered) {
    const tr = el("tr", lane.place === 1 ? "win" : null);
    tr.appendChild(el("td", null, lane.place ? `${lane.place}.` : "–"));
    const who = el("td", "who");
    who.appendChild(el("span", "sw")).style.background = lane.color;
    who.appendChild(document.createTextNode(lane.name));
    tr.appendChild(who);
    tr.appendChild(el("td", null, r.mode === "distance"
      ? (lane.time_s != null ? fmtTime(lane.time_s) : t("dnf"))
      : fmtMetres(lane.progress)));
    tr.appendChild(el("td", null, raceSplit(r, lane)));
    tr.appendChild(el("td", null, lane.avg_spm ? lane.avg_spm.toFixed(1) : "–"));
    tr.appendChild(el("td", null, lane.avg_watts ? Math.round(lane.avg_watts) : "–"));
    body.appendChild(tr);
  }
  table.appendChild(body);
  card.appendChild(table);

  const bar = el("div", "actions-bar");
  // Whoever rowed it is probably still rowing it out, so offer the button
  // here too rather than making them walk back to the Arena tab.
  if (myLane(r) && (STATE.live.get(STATE.me.id) || {}).rowing) {
    bar.appendChild(endSessionButton());
  }
  const clear = el("button", "primary", t("btnClear"));
  clear.onclick = async () => {
    await api("/api/race/clear", { method: "POST" }).catch(() => {});
    STATE.race = null;
    paintRace();
    await paintHistory();
  };
  bar.appendChild(clear);
  card.appendChild(bar);
  host.appendChild(card);
}

// --- History --------------------------------------------------------------

async function paintHistory() {
  const host = $("race-list");
  if (!host) return;
  host.innerHTML = "";
  const races = await api("/api/races?limit=40").catch(() => []);
  const done = races.filter((r) => r.state === "finished");
  if (!done.length) {
    host.appendChild(el("p", "empty", t("raceNone")));
    return;
  }
  const list = el("ul", "race-history");
  for (const r of done) {
    const li = el("li");
    const head = el("div", "rh-head");
    head.appendChild(el("strong", null, r.name || t("navRace")));
    head.appendChild(el("span", "sub",
      `${raceLabel(r)} · ${fmtDate(r.started_at || r.created_at)}`));
    li.appendChild(head);

    const podium = el("ol", "podium");
    r.entries.slice(0, 4).forEach((e) => {
      const item = el("li");
      const sw = el("span", "sw");
      sw.style.background = e.color;
      item.appendChild(sw);
      item.appendChild(el("span", "who", e.display_name + (e.kind === "ghost" ? " (ghost)" : "")));
      item.appendChild(el("span", "val", r.mode === "distance"
        ? (e.time_s != null ? fmtTime(e.time_s) : t("dnf"))
        : fmtMetres(e.distance_m)));
      podium.appendChild(item);
    });
    li.appendChild(podium);

    if (STATE.me.is_admin) {
      const del = el("a", null, t("delete"));
      del.href = "#";
      del.onclick = async (e) => {
        e.preventDefault();
        await api(`/api/races/${r.id}`, { method: "DELETE" }).catch(() => {});
        paintHistory();
      };
      li.appendChild(del);
    }
    list.appendChild(li);
  }
  host.appendChild(list);
}
