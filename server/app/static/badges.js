/* The badge wall, and the admin's side of it.

   A hidden badge the viewer has not earned arrives from the server as a
   silhouette with no name and no rule - the redaction happens there, not
   here, so reading the response tells you nothing either. */

VIEWS.badges = async function badges() {
  onLive = () => {};
  onRace = () => {};
  onData = () => {};

  let data;
  try {
    data = await api("/api/achievements");
  } catch (err) {
    viewFailed($("badge-summary"), err);
    return;
  }
  const all = data.achievements;
  const mine = new Set(data.mine);

  const summary = $("badge-summary");
  const got = all.filter((b) => !b.locked && b.earned.some((e) => e.athlete_id === STATE.me.id));
  const locked = all.filter((b) => b.locked);
  summary.innerHTML = "";
  const line = el("p", "hint");
  line.textContent = t("badgesSummary", got.length, all.length);
  summary.appendChild(line);
  if (locked.length) {
    summary.appendChild(el("p", "hint", t("badgesHiddenLeft", locked.length)));
  }

  const grid = $("badge-grid");
  grid.innerHTML = "";
  for (const badge of all) grid.appendChild(badgeCard(badge, mine));

  const recent = $("badge-recent");
  recent.innerHTML = "";
  const events = [];
  for (const badge of all) {
    if (badge.locked) continue;
    for (const e of badge.earned) events.push({ badge, e });
  }
  events.sort((a, b) => b.e.earned_at - a.e.earned_at);
  if (!events.length) {
    recent.appendChild(el("p", "empty", t("badgesNone")));
  } else {
    const list = el("ul", "badge-feed");
    for (const { badge, e } of events.slice(0, 12)) {
      const li = el("li");
      li.appendChild(el("span", "badge-mark", badge.icon || "•"));
      const who = el("span", "who");
      who.appendChild(el("span", "sw")).style.background = e.color;
      who.appendChild(document.createTextNode(e.display_name));
      li.appendChild(who);
      li.appendChild(el("strong", null, badge.name));
      li.appendChild(el("span", "sub", fmtDate(e.earned_at)));
      list.appendChild(li);
    }
    recent.appendChild(list);
  }
};

function badgeCard(badge, mine) {
  if (badge.locked) {
    const card = el("div", "card badge locked");
    card.appendChild(el("div", "badge-mark", "?"));
    card.appendChild(el("strong", null, t("badgeUndiscovered")));
    card.appendChild(el("p", "sub", t("badgeUndiscoveredNote")));
    return card;
  }
  const isMine = badge.earned.some((e) => e.athlete_id === STATE.me.id);
  const card = el("div", "card badge" + (isMine ? " mine" : ""));
  card.appendChild(el("div", "badge-mark", badge.icon || "•"));
  const head = el("div", "badge-head");
  head.appendChild(el("strong", null, badge.name));
  if (badge.hidden) head.appendChild(el("span", "tag", t("badgeWasHidden")));
  card.appendChild(head);
  card.appendChild(el("p", "sub", badge.note));

  const holders = el("div", "badge-holders");
  if (!badge.earned.length) {
    holders.appendChild(el("span", "sub", t("badgeNobody")));
  } else {
    for (const e of badge.earned) {
      const chip = el("span", "holder");
      chip.appendChild(el("span", "sw")).style.background = e.color;
      chip.appendChild(document.createTextNode(e.display_name));
      chip.title = fmtDate(e.earned_at);
      holders.appendChild(chip);
    }
  }
  card.appendChild(holders);
  return card;
}

// --- Admin ---------------------------------------------------------------

async function paintBadgesAdmin() {
  const host = $("acc-badges");
  if (!host) return;
  const [data, metrics] = await Promise.all([
    api("/api/achievements").catch(() => ({ achievements: [] })),
    api("/api/achievements/metrics").catch(() => []),
  ]);
  host.innerHTML = "";
  host.appendChild(el("h2", null, t("navBadges")));
  host.appendChild(el("p", "hint", t("badgesAdminHint")));

  const list = el("ul", "tokens");
  for (const badge of data.achievements) {
    const li = el("li");
    li.appendChild(el("span", "badge-mark small", badge.icon || "•"));
    li.appendChild(el("strong", null, badge.name));
    if (badge.hidden) li.appendChild(el("span", "tag", t("badgeHidden")));
    li.appendChild(el("span", "sub",
      `${badge.metric} ${badge.op} ${fmtInt(badge.threshold)} · ${badge.earned.length}×`));
    const del = el("a", null, t("btnDelete"));
    del.href = "#";
    del.onclick = async (e) => {
      e.preventDefault();
      if (!confirm(t("badgeConfirmDelete", badge.name))) return;
      await api(`/api/achievements/${badge.id}`, { method: "DELETE" });
      paintBadgesAdmin();
    };
    li.appendChild(del);
    list.appendChild(li);
  }
  host.appendChild(list);

  const form = el("form", "card");
  form.appendChild(el("h3", null, t("badgeNew")));
  const name = field(form, t("badgeName"), "text");
  name.placeholder = "Eisberg";
  const icon = field(form, t("badgeIcon"), "text");
  icon.placeholder = "🧊";
  icon.maxLength = 8;
  const note = field(form, t("badgeNote"), "text");
  note.placeholder = "Eine Einheit unter 10 Grad Wassertemperatur.";

  const rule = el("div", "sec-row");
  const metricLabel = el("label");
  metricLabel.appendChild(el("span", null, t("badgeMetric")));
  const metric = el("select");
  metrics.forEach((m) => metric.appendChild(new Option(
    `${t("metric_" + m.metric) || m.metric}${m.unit ? ` (${m.unit})` : ""}`, m.metric)));
  metricLabel.appendChild(metric);
  rule.appendChild(metricLabel);

  const opLabel = el("label");
  opLabel.appendChild(el("span", null, t("badgeOp")));
  const op = el("select");
  op.appendChild(new Option(t("opAtLeast"), ">="));
  op.appendChild(new Option(t("opAtMost"), "<="));
  opLabel.appendChild(op);
  rule.appendChild(opLabel);

  const thLabel = el("label");
  thLabel.appendChild(el("span", null, t("badgeThreshold")));
  const threshold = el("input");
  threshold.type = "number";
  threshold.step = "any";
  threshold.value = "1";
  thLabel.appendChild(threshold);
  rule.appendChild(thLabel);
  form.appendChild(rule);

  const hiddenLabel = el("label", "check");
  const hidden = el("input");
  hidden.type = "checkbox";
  hiddenLabel.appendChild(hidden);
  hiddenLabel.appendChild(el("span", null, t("badgeHiddenLabel")));
  form.appendChild(hiddenLabel);

  const foot = el("div", "form-foot");
  const msg = el("span", "form-msg");
  foot.appendChild(msg);
  const btn = el("button", "primary", t("badgeAdd"));
  btn.type = "submit";
  foot.appendChild(btn);
  form.appendChild(foot);

  form.onsubmit = async (e) => {
    e.preventDefault();
    try {
      await api("/api/achievements", {
        method: "POST",
        body: { name: name.value.trim(), note: note.value.trim(), icon: icon.value.trim(),
                metric: metric.value, op: op.value,
                threshold: Number(threshold.value), hidden: hidden.checked },
      });
      paintBadgesAdmin();
    } catch (err) {
      msg.className = "form-msg err";
      msg.textContent = err.message;
    }
  };
  host.appendChild(form);
}

/* A badge landing while somebody is looking at the page is worth a word.
   Not an alert - it interrupts a race. */
function badgeToast(msg) {
  const box = el("div", "toast");
  box.appendChild(el("span", "badge-mark small", msg.icon || "•"));
  const text = el("div");
  text.appendChild(el("strong", null,
    msg.athlete_id === STATE.me.id ? t("badgeYouEarned") : msg.display_name));
  text.appendChild(el("span", "sub", msg.name));
  box.appendChild(text);
  document.body.appendChild(box);
  setTimeout(() => box.classList.add("gone"), 6000);
  setTimeout(() => box.remove(), 6600);
}
