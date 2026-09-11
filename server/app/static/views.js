/* The four calm views. The race lives in race.js. */

STATE.sessions = [];
STATE.selected = null;
STATE.compare = new Set();
STATE.filter = { athlete_id: 0, days: 30 };
STATE.cache = new Map();

// --- Arena ----------------------------------------------------------------

VIEWS.arena = async function arena() {
  paintRaceBanner();
  paintLiveCards();
  onLive = paintLiveCards;
  onRace = () => { paintRaceBanner(); paintLiveCards(); };

  const totals = await api("/api/totals?days=7").catch(() => []);
  const host = $("totals");
  if (!host) return;
  host.innerHTML = "";
  const table = el("table", "table");
  const head = el("tr");
  [" ", t("colSessions"), t("colDistance"), t("colTime"), t("colStrokes")]
    .forEach((h) => head.appendChild(el("th", null, h)));
  table.appendChild(el("thead")).appendChild(head);
  const body = el("tbody");
  for (const row of totals) {
    const tr = el("tr");
    const who = el("td", "who");
    who.appendChild(el("span", "sw")).style.background = row.color;
    who.appendChild(document.createTextNode(row.display_name));
    tr.appendChild(who);
    tr.appendChild(el("td", null, fmtInt(row.sessions)));
    tr.appendChild(el("td", null, fmtMetres(row.distance_m)));
    tr.appendChild(el("td", null, fmtDur(row.duration_s)));
    tr.appendChild(el("td", null, fmtInt(row.strokes)));
    body.appendChild(tr);
  }
  table.appendChild(body);
  host.appendChild(table);
};

function paintRaceBanner() {
  const host = $("race-banner");
  if (!host) return;
  host.innerHTML = "";
  const r = STATE.race;
  if (!r || r.state === "finished" || r.state === "aborted") return;
  const box = el("div", "banner");
  const running = r.state === "running" || r.state === "countdown";
  box.appendChild(el("strong", null, running ? t("raceRunning") : t("raceOpen")));
  box.appendChild(el("span", "sub", raceLabel(r)));
  const go = el("button", "primary", t("raceGo"));
  go.onclick = () => setView("race");
  box.appendChild(go);
  host.appendChild(box);
}

function paintLiveCards() {
  const host = $("live-cards");
  if (!host) return;
  host.innerHTML = "";
  const rowing = [];
  for (const a of STATE.athletes) {
    const live = STATE.live.get(a.id) || {};
    host.appendChild(liveCard(a, live));
    if (live.rowing) rowing.push(a);
  }
  if (!rowing.length) host.appendChild(el("p", "empty", t("nobodyRowing")));
}

function liveCard(athlete, live) {
  const v = live.values || {};
  const card = el("div", "card athlete" + (live.rowing ? " live" : live.online ? "" : " off"));
  card.style.setProperty("--lane", athlete.color);

  const head = el("div", "athlete-head");
  head.appendChild(el("span", "dot"));
  head.appendChild(el("strong", null, athlete.display_name));
  const status = live.rowing ? t("rowing") : live.online ? t("idle") : t("offline");
  head.appendChild(el("span", "status", status));
  card.appendChild(head);

  if (live.rowing) {
    const grid = el("div", "mini");
    const cell = (label, value) => {
      const d = el("div");
      d.appendChild(el("span", "lbl", label));
      d.appendChild(el("span", "val", value));
      grid.appendChild(d);
    };
    cell(t("colDistance"), fmtMetres(v.distance_m));
    cell("500 m", fmtSplit(v.speed_ms));
    cell("s/min", fmtInt(v.stroke_rate));
    cell("W", fmtInt(v.watts));
    cell(t("colTime"), fmtDur(v.t));
    card.appendChild(grid);
  } else if (live.updated_at) {
    card.appendChild(el("p", "empty", t("lastSeen", fmtAgo(live.updated_at))));
  }
  return card;
}

// --- Sessions -------------------------------------------------------------

VIEWS.sessions = async function sessions() {
  onLive = () => {};
  onRace = () => {};
  onData = () => VIEWS.sessions();

  const who = $("f-athlete");
  who.innerHTML = "";
  who.appendChild(new Option(t("allAthletes"), "0"));
  STATE.athletes.forEach((a) => who.appendChild(new Option(a.display_name, String(a.id))));
  who.value = String(STATE.filter.athlete_id);
  who.onchange = () => { STATE.filter.athlete_id = Number(who.value); VIEWS.sessions(); };

  const days = $("f-days");
  days.innerHTML = "";
  [[7, "range7"], [30, "range30"], [90, "range90"], [0, "rangeAll"]]
    .forEach(([d, key]) => days.appendChild(new Option(t(key), String(d))));
  days.value = String(STATE.filter.days);
  days.onchange = () => { STATE.filter.days = Number(days.value); VIEWS.sessions(); };

  $("cmp-clear").onclick = () => { STATE.compare.clear(); VIEWS.sessions(); };

  const params = new URLSearchParams();
  if (STATE.filter.athlete_id) params.set("athlete_id", STATE.filter.athlete_id);
  if (STATE.filter.days) params.set("days", STATE.filter.days);
  STATE.sessions = await api(`/api/sessions?${params}`).catch(() => []);

  const list = $("session-list");
  list.innerHTML = "";
  if (!STATE.sessions.length) {
    list.appendChild(el("li", "empty", t("sessionsEmpty")));
  }
  for (const s of STATE.sessions) {
    const li = el("li");
    li.className = (s.id === STATE.selected ? "sel " : "") + (STATE.compare.has(s.id) ? "cmp" : "");
    li.style.setProperty("--lane", s.color);
    li.onclick = () => selectSession(s.id);
    const when = el("span", "when", fmtDate(s.started_at));
    li.appendChild(when);
    li.appendChild(el("span", "dist", fmtMetres(s.distance_m)));
    const sub = el("span", "sub");
    sub.textContent = `${s.display_name} · ${fmtDur(s.duration_s)} · ${fmtSplit(s.avg_speed_ms)}/500 m`
      + (s.ended_at ? "" : ` · ${t("open")}`)
      + (s.race_id ? " · 🏁" : "");
    li.appendChild(sub);
    list.appendChild(li);
  }
  if (STATE.selected) await paintDetail(STATE.selected);
  else $("session-detail").appendChild(el("p", "empty", t("pickSession")));
  await paintCompare();
};

async function getSession(id) {
  if (!STATE.cache.has(id)) STATE.cache.set(id, await api(`/api/sessions/${id}`));
  return STATE.cache.get(id);
}

async function selectSession(id) {
  STATE.selected = STATE.selected === id ? null : id;
  await VIEWS.sessions();
}

async function paintDetail(id) {
  const host = $("session-detail");
  host.innerHTML = "";
  let data;
  try { data = await getSession(id); } catch { return; }
  const s = data.session, samples = data.samples;

  const head = el("div", "detail-head");
  head.appendChild(el("h2", null, `${s.display_name} · ${fmtDate(s.started_at)}`));
  const actions = el("div", "actions");

  const cmp = el("label", "cmp");
  const box = el("input");
  box.type = "checkbox";
  box.checked = STATE.compare.has(id);
  box.onchange = () => {
    if (box.checked) {
      if (STATE.compare.size >= 4) { box.checked = false; alert(t("maxCompare")); return; }
      STATE.compare.add(id);
    } else STATE.compare.delete(id);
    VIEWS.sessions();
  };
  cmp.appendChild(box);
  cmp.appendChild(el("span", null, t("compare")));
  actions.appendChild(cmp);

  const csv = el("a", null, t("exportCsv"));
  csv.href = `/api/sessions/${id}/export.csv`;
  actions.appendChild(csv);

  if (STATE.me.is_admin || STATE.me.id === s.athlete_id) {
    const del = el("a", null, t("delete"));
    del.href = "#";
    del.onclick = async (e) => {
      e.preventDefault();
      if (!confirm(t("confirmDelete"))) return;
      await api(`/api/sessions/${id}`, { method: "DELETE" });
      STATE.cache.delete(id);
      STATE.compare.delete(id);
      STATE.selected = null;
      VIEWS.sessions();
    };
    actions.appendChild(del);
  }
  head.appendChild(actions);
  host.appendChild(head);

  const facts = el("dl", "facts");
  const fact = (label, value, lead) => {
    const d = el("div", lead ? "lead" : null);
    d.appendChild(el("dt", null, label));
    d.appendChild(el("dd", null, value));
    facts.appendChild(d);
  };
  fact(t("colDistance"), fmtMetres(s.distance_m), true);
  fact(t("colTime"), fmtDur(s.duration_s), true);
  fact("Ø 500 m", fmtSplit(s.avg_speed_ms));
  fact("Ø s/min", s.avg_spm.toFixed(1));
  fact("Ø W", Math.round(s.avg_watts));
  fact(t("colStrokes"), fmtInt(s.strokes));
  host.appendChild(facts);

  host.appendChild(chartFigure(t("chartSpeed"), (canvas, readout) => drawLine(canvas,
    [{ x: samples.map((p) => p.t), y: samples.map((p) => p.speed_ms), color: s.color, fill: true }],
    { readout, yFmt: (v) => v.toFixed(1), fmt: (v) => `${v.toFixed(2)} m/s · ${fmtSplit(v)}/500 m` })));

  host.appendChild(chartFigure(t("chartSpm"), (canvas, readout) => drawLine(canvas,
    [{ x: samples.map((p) => p.t), y: samples.map((p) => p.stroke_rate), color: THEME.series[3] }],
    { readout, fmt: (v) => `${Math.round(v)} s/min` })));
}

function chartFigure(caption, draw) {
  const fig = el("figure");
  const cap = el("figcaption");
  cap.appendChild(el("span", null, caption));
  const readout = el("span", "readout");
  cap.appendChild(readout);
  fig.appendChild(cap);
  const canvas = el("canvas");
  canvas.height = 200;
  canvas.dataset.aspect = "3.2";
  canvas.dataset.minHeight = "130";
  fig.appendChild(canvas);
  // The canvas needs its layout width, which it only has once it is in the
  // document - so draw on the next frame, not now.
  requestAnimationFrame(() => draw(canvas, readout));
  return fig;
}

async function paintCompare() {
  const host = $("compare");
  if (!host) return;
  host.innerHTML = "";
  if (STATE.compare.size < 2) return;
  host.appendChild(el("h2", null, t("compareTitle")));

  const picked = [];
  for (const id of STATE.compare) {
    try { picked.push(await getSession(id)); } catch {}
  }

  const legend = el("ul", "legend");
  picked.forEach((d, i) => {
    const li = el("li");
    const bar = el("i");
    bar.style.background = d.session.color || THEME.series[i % 4];
    li.appendChild(bar);
    li.appendChild(el("span", null, `${d.session.display_name} · ${fmtDay(d.session.started_at)}`));
    legend.appendChild(li);
  });
  host.appendChild(legend);

  host.appendChild(chartFigure(t("chartCmp"), (canvas, readout) => drawLine(canvas,
    picked.map((d, i) => ({
      x: d.samples.map((p) => p.t),
      y: d.samples.map((p) => p.distance_m),
      color: d.session.color || THEME.series[i % 4],
      label: d.session.display_name,
    })),
    { readout, yFmt: (v) => fmtInt(v), fmt: (v) => fmtMetres(v) })));

  const table = el("table", "table");
  const head = el("tr");
  [" ", t("colDistance"), t("colTime"), "Ø 500 m", "Ø s/min", "Ø W"]
    .forEach((h) => head.appendChild(el("th", null, h)));
  table.appendChild(el("thead")).appendChild(head);
  const body = el("tbody");
  for (const d of picked) {
    const s = d.session;
    const tr = el("tr");
    const who = el("td", "who");
    who.appendChild(el("span", "sw")).style.background = s.color;
    who.appendChild(document.createTextNode(`${s.display_name} · ${fmtDay(s.started_at)}`));
    tr.appendChild(who);
    tr.appendChild(el("td", null, fmtMetres(s.distance_m)));
    tr.appendChild(el("td", null, fmtDur(s.duration_s)));
    tr.appendChild(el("td", null, fmtSplit(s.avg_speed_ms)));
    tr.appendChild(el("td", null, s.avg_spm.toFixed(1)));
    tr.appendChild(el("td", null, Math.round(s.avg_watts)));
    body.appendChild(tr);
  }
  table.appendChild(body);
  host.appendChild(table);
}

// --- Records --------------------------------------------------------------

VIEWS.records = async function recordsView() {
  onLive = () => {};
  onRace = () => {};
  onData = () => {};

  const [recs, totals, h2h] = await Promise.all([
    api("/api/records").catch(() => []),
    api("/api/totals").catch(() => []),
    api("/api/h2h").catch(() => ({ pairs: [] })),
  ]);

  for (const [kind, hostId] of [["distance", "rec-distance"], ["time", "rec-time"]]) {
    const host = $(hostId);
    host.innerHTML = "";
    const boards = recs.filter((r) => r.kind === kind);
    if (!boards.length) { host.appendChild(el("p", "empty", t("recordsEmpty"))); continue; }
    for (const board of boards) {
      const card = el("div", "card rec");
      card.appendChild(el("h3", null,
        kind === "distance" ? `${fmtInt(board.key)} m` : fmtDur(board.key)));
      const ol = el("ol", "rec-list");
      board.entries.forEach((e, i) => {
        const li = el("li");
        li.appendChild(el("span", "rank", String(i + 1)));
        const who = el("span", "who");
        who.appendChild(el("span", "sw")).style.background = e.color;
        who.appendChild(document.createTextNode(e.display_name));
        li.appendChild(who);
        const val = el("a", "val",
          kind === "distance" ? fmtTime(e.value) : fmtMetres(e.value));
        val.href = "#";
        val.title = fmtDate(e.started_at);
        val.onclick = (ev) => {
          ev.preventDefault();
          STATE.selected = e.session_id;
          STATE.filter = { athlete_id: 0, days: 0 };
          setView("sessions");
        };
        li.appendChild(val);
        ol.appendChild(li);
      });
      card.appendChild(ol);
      host.appendChild(card);
    }
  }

  const tHost = $("rec-totals");
  tHost.innerHTML = "";
  const table = el("table", "table");
  const head = el("tr");
  [" ", t("colSessions"), t("colDistance"), t("colTime"), t("colStrokes")]
    .forEach((h) => head.appendChild(el("th", null, h)));
  table.appendChild(el("thead")).appendChild(head);
  const body = el("tbody");
  for (const row of totals) {
    const tr = el("tr");
    const who = el("td", "who");
    who.appendChild(el("span", "sw")).style.background = row.color;
    who.appendChild(document.createTextNode(row.display_name));
    tr.appendChild(who);
    tr.appendChild(el("td", null, fmtInt(row.sessions)));
    tr.appendChild(el("td", null, fmtMetres(row.distance_m)));
    tr.appendChild(el("td", null, fmtDur(row.duration_s)));
    tr.appendChild(el("td", null, fmtInt(row.strokes)));
    body.appendChild(tr);
  }
  table.appendChild(body);
  tHost.appendChild(table);

  const hHost = $("rec-h2h");
  hHost.innerHTML = "";
  if (!h2h.pairs || !h2h.pairs.length) {
    hHost.appendChild(el("p", "empty", t("h2hEmpty")));
  } else {
    const ul = el("ul", "h2h");
    h2h.pairs
      .sort((a, b) => b.wins - a.wins)
      .forEach((p) => {
        const li = el("li");
        li.innerHTML = t("h2hLine", athleteName(p.winner), athleteName(p.loser), p.wins);
        ul.appendChild(li);
      });
    hHost.appendChild(ul);
  }
};

// --- Account --------------------------------------------------------------

VIEWS.account = async function account() {
  onLive = () => {};
  onRace = () => {};
  onData = () => {};

  paintProfile();
  await paintTokens();
  if (STATE.me.is_admin) await paintAdmin();
};

function paintProfile() {
  const host = $("acc-profile");
  host.innerHTML = "";
  const form = el("form", "card");
  const name = field(form, t("labelDisplayName"), "text", STATE.me.display_name);
  const color = field(form, t("labelColor"), "color", STATE.me.color || "#2a78d6");
  const foot = el("div", "form-foot");
  const msg = el("span", "form-msg");
  foot.appendChild(msg);
  const save = el("button", "primary", t("btnSave"));
  save.type = "submit";
  foot.appendChild(save);
  form.appendChild(foot);
  form.onsubmit = async (e) => {
    e.preventDefault();
    try {
      STATE.me = await api(`/api/athletes/${STATE.me.id}`, {
        method: "PATCH",
        body: { display_name: name.value.trim(), color: color.value },
      });
      STATE.athletes = await api("/api/athletes");
      msg.className = "form-msg ok";
      msg.textContent = t("saved");
    } catch (err) {
      msg.className = "form-msg err";
      msg.textContent = err.message || t("saveFailed");
    }
  };
  host.appendChild(form);

  const pw = el("form", "card");
  pw.appendChild(el("h3", null, t("changePassword")));
  const oldPw = field(pw, t("labelOldPassword"), "password");
  const newPw = field(pw, t("labelNewPassword"), "password");
  newPw.minLength = 8;
  const pfoot = el("div", "form-foot");
  const pmsg = el("span", "form-msg");
  pfoot.appendChild(pmsg);
  const pbtn = el("button", "primary", t("btnSave"));
  pbtn.type = "submit";
  pfoot.appendChild(pbtn);
  pw.appendChild(pfoot);
  pw.onsubmit = async (e) => {
    e.preventDefault();
    try {
      await api("/api/password", {
        method: "POST",
        body: { old_password: oldPw.value, password: newPw.value },
      });
      pw.reset();
      pmsg.className = "form-msg ok";
      pmsg.textContent = t("saved");
    } catch (err) {
      pmsg.className = "form-msg err";
      pmsg.textContent = err.message || t("saveFailed");
    }
  };
  host.appendChild(pw);

  const out = el("button", null, t("logout"));
  out.onclick = logout;
  host.appendChild(out);
}

function field(form, label, type, value) {
  const lab = el("label");
  lab.appendChild(el("span", null, label));
  const input = el("input");
  input.type = type;
  if (value != null) input.value = value;
  lab.appendChild(input);
  form.appendChild(lab);
  return input;
}

async function paintTokens(athleteId = STATE.me.id, host = $("acc-tokens")) {
  host.innerHTML = "";
  host.appendChild(el("p", "hint", t("tokenIntro")));
  const hint = el("p", "hint");
  hint.innerHTML = t("trackerSetup", location.origin);
  host.appendChild(hint);

  const tokens = await api(`/api/athletes/${athleteId}/tokens`).catch(() => []);
  const list = el("ul", "tokens");
  if (!tokens.length) list.appendChild(el("li", "empty", t("tokenNone")));
  for (const tok of tokens) {
    const li = el("li");
    li.appendChild(el("strong", null, tok.label || `#${tok.id}`));
    li.appendChild(el("span", "sub", tok.last_seen_at
      ? t("lastSeen", fmtAgo(tok.last_seen_at)) : t("tokenNever")));
    const revoke = el("a", null, t("tokenRevoke"));
    revoke.href = "#";
    revoke.onclick = async (e) => {
      e.preventDefault();
      if (!confirm(t("confirmRevoke"))) return;
      await api(`/api/athletes/${athleteId}/tokens/${tok.id}`, { method: "DELETE" });
      paintTokens(athleteId, host);
    };
    li.appendChild(revoke);
    list.appendChild(li);
  }
  host.appendChild(list);

  const form = el("form", "inline");
  const label = el("input");
  label.placeholder = t("tokenLabel");
  form.appendChild(label);
  const btn = el("button", "primary", t("btnNewToken"));
  btn.type = "submit";
  form.appendChild(btn);
  form.onsubmit = async (e) => {
    e.preventDefault();
    const { token } = await api(`/api/athletes/${athleteId}/tokens`, {
      method: "POST", body: { label: label.value.trim() },
    });
    host.appendChild(secretBox(t("tokenCreated"), token));
    label.value = "";
    // Deliberately not re-rendering the list here: that would wipe the one
    // and only display of the token.
  };
  host.appendChild(form);
}

function secretBox(caption, secret) {
  const box = el("div", "secret");
  box.appendChild(el("p", null, caption));
  const code = el("code", null, secret);
  box.appendChild(code);
  const copy = el("button", null, t("btnCopy"));
  copy.onclick = async () => {
    try {
      await navigator.clipboard.writeText(secret);
      copy.textContent = t("copied");
    } catch {
      const r = document.createRange();
      r.selectNode(code);
      getSelection().removeAllRanges();
      getSelection().addRange(r);
    }
  };
  box.appendChild(copy);
  return box;
}

async function paintAdmin() {
  const host = $("acc-admin");
  host.innerHTML = "";
  host.appendChild(el("h2", null, t("accAdmin")));

  const athletes = await api("/api/athletes").catch(() => []);
  const full = await Promise.all(athletes.map(async (a) => a));
  const list = el("ul", "athlete-admin");
  for (const a of full) {
    const li = el("li");
    const sw = el("span", "sw");
    sw.style.background = a.color;
    li.appendChild(sw);
    li.appendChild(el("strong", null, a.display_name));
    li.appendChild(el("span", "sub", a.name + (a.is_admin ? " · admin" : "")));

    const invite = el("a", null, t("btnInvite"));
    invite.href = "#";
    invite.onclick = async (e) => {
      e.preventDefault();
      const { invite_code } = await api(`/api/athletes/${a.id}/invite`, { method: "POST" });
      li.appendChild(secretBox(t("inviteReady"), `${location.origin}/#join?code=${invite_code}`));
    };
    li.appendChild(invite);

    if (a.id !== STATE.me.id) {
      const del = el("a", null, t("btnDelete"));
      del.href = "#";
      del.onclick = async (e) => {
        e.preventDefault();
        if (!confirm(t("confirmDeleteAthlete", a.display_name))) return;
        await api(`/api/athletes/${a.id}`, { method: "DELETE" });
        STATE.athletes = await api("/api/athletes");
        paintAdmin();
      };
      li.appendChild(del);
    }
    list.appendChild(li);
  }
  host.appendChild(list);

  const form = el("form", "card");
  form.appendChild(el("h3", null, t("newAthlete")));
  const handle = field(form, t("labelName"), "text");
  handle.placeholder = "jan";
  const display = field(form, t("labelDisplayName"), "text");
  const foot = el("div", "form-foot");
  const msg = el("span", "form-msg");
  foot.appendChild(msg);
  const btn = el("button", "primary", t("btnCreate"));
  btn.type = "submit";
  foot.appendChild(btn);
  form.appendChild(foot);
  form.onsubmit = async (e) => {
    e.preventDefault();
    try {
      const res = await api("/api/athletes", {
        method: "POST",
        body: { name: handle.value.trim().toLowerCase(), display_name: display.value.trim() },
      });
      STATE.athletes = await api("/api/athletes");
      form.reset();
      host.appendChild(secretBox(t("inviteReady"),
        `${location.origin}/#join?code=${res.invite_code}`));
    } catch (err) {
      msg.className = "form-msg err";
      msg.textContent = err.status === 409 ? t("nameTaken") : err.message;
    }
  };
  host.appendChild(form);
}
