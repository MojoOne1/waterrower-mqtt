/* WaterRower Arena - shell: language, theme, sign-in, routing, live socket.
   No dependencies; charts.js, views.js and race.js hang off the globals
   defined here. */

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

const STATE = {
  me: null,
  athletes: [],
  live: new Map(),      // athlete_id -> live state
  race: null,
  view: "arena",
  socket: null,
};

// --- Language -------------------------------------------------------------

const I18N = {
  de: {
    locale: "de-DE",
    appName: "WaterRower Arena",
    loginHint: "Melde dich mit deinem Namen und Passwort an.",
    labelName: "Name", labelPassword: "Passwort", labelNewPassword: "Neues Passwort",
    labelDisplayName: "Anzeigename",
    btnLogin: "Anmelden", loginFailed: "Name oder Passwort stimmt nicht",
    joinTitle: "Willkommen in der Arena", btnJoin: "Loslegen",
    joinWho: (n) => `Die Einladung gilt für ${n}. Vergib ein Passwort.`,
    joinInvalid: "Diese Einladung gilt nicht mehr. Frag nach einer neuen.",
    pwShort: (n) => `Das Passwort braucht mindestens ${n} Zeichen.`,
    pwKinds: "Drei von vier: Kleinbuchstaben, Großbuchstaben, Ziffern, Sonderzeichen.",
    themeAuto: "Auto", themeLight: "Hell", themeDark: "Dunkel",
    navArena: "Arena", navRace: "Rennen", navSessions: "Einheiten",
    navRecords: "Bestenlisten", navBadges: "Abzeichen", navAccount: "Konto",
    badgesSummary: (got, all) => `${got} von ${all} Abzeichen.`,
    badgesHiddenLeft: (n) => n === 1 ? "Eines ist noch unentdeckt." : `${n} sind noch unentdeckt.`,
    badgesRecent: "Zuletzt vergeben", badgesNone: "Noch nichts vergeben.",
    badgeUndiscovered: "Unentdeckt",
    badgeUndiscoveredNote: "Ein verstecktes Abzeichen. Was es verlangt, steht hier erst, wenn du es hast.",
    badgeWasHidden: "versteckt", badgeHidden: "versteckt",
    badgeNobody: "Hat noch niemand.",
    badgeYouEarned: "Abzeichen freigeschaltet",
    badgesAdminHint: "Eine Regel ist immer: Kennzahl, Vergleich, Schwelle. Geprüft wird beim Beenden einer Einheit und am Rennende.",
    badgeNew: "Abzeichen anlegen", badgeAdd: "Anlegen",
    badgeName: "Name", badgeIcon: "Zeichen", badgeNote: "Beschreibung",
    badgeMetric: "Kennzahl", badgeOp: "Vergleich", badgeThreshold: "Schwelle",
    badgeHiddenLabel: "Versteckt – erst sichtbar, wenn jemand es hat",
    badgeConfirmDelete: (n) => `„${n}" löschen? Alle, die es haben, verlieren es.`,
    opAtLeast: "mindestens", opAtMost: "höchstens",
    metric_sessions_total: "Einheiten insgesamt", metric_distance_total: "Meter insgesamt",
    metric_session_distance: "Meter in einer Einheit", metric_session_duration: "Dauer einer Einheit",
    metric_session_start_hour: "Startstunde", metric_best_500: "Bestzeit 500 m",
    metric_best_1000: "Bestzeit 1000 m", metric_best_2000: "Bestzeit 2000 m",
    metric_best_5000: "Bestzeit 5000 m", metric_best_10000: "Bestzeit 10000 m",
    metric_furthest_1200: "Weiteste 20 Minuten", metric_furthest_3600: "Weiteste 60 Minuten",
    metric_race_wins: "Siege insgesamt", metric_race_win_streak: "Siege in Folge",
    metric_day_streak: "Tage in Folge", metric_race_margin_s: "Vorsprung im Ziel",
    connOn: "verbunden", connOff: "getrennt", connWait: "verbinde …",
    loadFailed: (why) => `Konnte nicht geladen werden${why ? ": " + why : "."}`,
    tryAgain: "Nochmal versuchen",

    arenaNow: "Gerade auf dem Wasser", arenaWeek: "Diese Woche",
    nobodyRowing: "Gerade rudert niemand.",
    endSession: "Einheit beenden",
    confirmEnd: "Deine Einheit jetzt beenden? Der Monitor behält seine Anzeige.",
    endSent: "Wird beendet …",
    endFailed: "Beenden fehlgeschlagen",
    offline: "offline", idle: "bereit", rowing: "rudert",
    lastSeen: (s) => `zuletzt ${s}`,

    raceRunning: "Rennen läuft", raceOpen: "Rennen offen – mitmachen?",
    raceGo: "Zum Rennen",
    raceHistory: "Vergangene Rennen", raceNone: "Noch kein Rennen gefahren.",
    newRace: "Neues Rennen", raceName: "Name", raceMode: "Modus",
    ownRace: "Eigenes Rennen",
    templates: "Vorlagen",
    templatesHint: "Antippen legt das Rennen sofort an.",
    templatesAdminHint: "Die Athleten wählen daraus, statt jedes Mal das Formular auszufüllen.",
    templatesNone: "Noch keine Vorlage.",
    templateNew: "Vorlage anlegen", templateAdd: "Anlegen",
    templateNote: "Notiz",
    modeDistance: "Distanz", modeTime: "Zeit", modeFree: "Frei rudern",
    raceTarget: "Ziel", targetMetres: "Meter", targetMinutes: "Minuten",
    btnCreate: "Rennen anlegen", btnJoinRace: "Mitfahren", btnLeave: "Verlassen",
    btnReady: "Bereit", btnNotReady: "Doch nicht", btnStart: "Start",
    btnAbort: "Abbrechen", btnEnd: "Rennen beenden", btnClear: "Ergebnis wegräumen",
    btnGhost: "Ghost hinzufügen",
    ghostPick: "Gegen welche Aufzeichnung?", ghostNone: "Keine Aufzeichnung mit genug Daten.",
    lobby: "Startaufstellung", waitingFor: "Warte auf den Host",
    readyCount: (r, n) => `${r} von ${n} bereit`,
    countdown: "Achtung …", go: "Los!",
    resetHint: "Alle Monitore werden auf null gesetzt. Nicht rudern, bis es losgeht.",
    elapsed: "Zeit", toGo: "noch", ahead: "vorn", behind: "zurück",
    finished: "im Ziel", dnf: "nicht beendet",
    place: "Platz", results: "Ergebnis",
    onlyHost: "Nur der Host kann das",
    raceBusy: "Es läuft schon ein Rennen",
    needOnline: (n) => `${n} ist offline – ohne Tracker keine Daten.`,

    filterAthlete: "Athlet", filterRange: "Zeitraum", allAthletes: "Alle",
    range7: "7 Tage", range30: "30 Tage", range90: "90 Tage", rangeAll: "Alles",
    sessionsEmpty: "Noch keine Einheit aufgezeichnet.",
    open: "offen", inCompare: "im Vergleich", compare: "vergleichen", delete: "löschen",
    confirmDelete: "Diese Einheit endgültig löschen?",
    maxCompare: "Höchstens vier Einheiten im Vergleich.",
    clearSelection: "Auswahl leeren", pickSession: "Wähle links eine Einheit.",
    exportCsv: "CSV",
    exportXlsx: "Excel", exportAll: "Alles als Excel",
    backupTitle: "Sicherung",
    backupHint: "Die ganze Arena als eine Datei – Athleten, Einheiten, Messpunkte, Rennen, Abzeichen. Sie enthält auch Passwort-Hashes und offene Einladungscodes, gehört also an einen privaten Ort.",
    backupDownload: "Datenbank herunterladen",
    chartSpeed: "Geschwindigkeit in m/s", chartSpm: "Schlagfrequenz",
    chartCmp: "Distanz ab Start der jeweiligen Einheit",
    compareTitle: "Vergleich", noSamples: "Keine Messpunkte", avg: "Ø",

    recordsDistance: "Beste Zeiten", recordsTime: "Weiteste Strecken",
    recordsTotals: "Summen", recordsH2h: "Direkter Vergleich",
    recordsEmpty: "Noch nichts aufgezeichnet, das lang genug wäre.",
    h2hEmpty: "Noch kein Rennen entschieden.",
    h2hLine: (a, b, n) => `${a} schlägt ${b} ${n}×`,
    colSessions: "Einheiten", colDistance: "Distanz", colTime: "Zeit", colStrokes: "Schläge",

    accProfile: "Profil", accTokens: "Tracker-Verbindung", accAdmin: "Athleten",
    accSecurity: "Sicherheit",
    secIntro: "So viele Fehlversuche sperren – und für so viele Minuten. Derselbe Zeitraum ist auch das Gedächtnis: wer aufhört, dessen Zähler läuft von allein ab.",
    secZero: "Eine 0 bei den Fehlversuchen schaltet die jeweilige Sperre ab.",
    secLimit: "Fehlversuche", secMinutes: "Sperre (Minuten)",
    secLoginIp: "Anmeldung je IP-Adresse",
    secLoginIpHint: "Eine Adresse, die an beliebigen Konten rät.",
    secLoginName: "Anmeldung je Konto",
    secLoginNameHint: "Ein Konto, an dem von überall geraten wird. Bewusst lockerer – damit lässt sich sonst jemand aussperren.",
    secInviteIp: "Einladungslinks je IP-Adresse",
    secInviteIpHint: "Falsche Codes von einer Adresse. Ein Code hat 96 Bit, ein falscher ist also Tippfehler oder Fischzug.",
    secUplinkIp: "Tracker-Anmeldung je IP-Adresse",
    secUplinkIpHint: "Tracker mit falschem Token. Ein Token hat 256 Bit – hier geht es nicht ums Raten, sondern um Verbindungen auf Vorrat.",
    kind_uplink: "Tracker",
    btnReset: "Passwort zurücksetzen",
    resetHelp: "Setzt das Passwort zurück, meldet das Konto überall ab und erzeugt einen einmaligen Link zum Neuvergeben.",
    secBlocked: "Aktive Sperren", secNoBlocks: "Zurzeit ist nichts gesperrt.",
    secFor: (d) => `noch ${d}`,
    secUnblock: "aufheben", secUnblockAll: "Alle Sperren aufheben",
    secRefresh: "Aktualisieren",
    secFailures: (h) => `Fehlversuche der letzten ${h} Stunden`,
    secNoFailures: "Keine Fehlversuche. Ruhig hier.",
    secFailureCount: (n) => `${n} Versuche abgewiesen.`,
    secTopIp: "Häufigste Adressen", secTopName: "Häufigste Konten",
    secWhat: "Art", secAddress: "Adresse",
    kind_login: "Anmeldung", kind_invite: "Einladung",
    pol_login_ip: "Anmeldung/IP", pol_login_name: "Anmeldung/Konto", pol_invite_ip: "Einladung/IP",
    btnSave: "Speichern", saved: "Gespeichert", saveFailed: "Speichern fehlgeschlagen",
    labelColor: "Farbe",
    changePassword: "Passwort ändern", labelOldPassword: "Aktuelles Passwort",
    tokenIntro: "Dein Tracker meldet sich mit einem Token an. Es wird nur einmal angezeigt.",
    btnNewToken: "Neues Token", tokenLabel: "Bezeichnung", tokenNone: "Noch kein Token.",
    tokenCreated: "Token angelegt – jetzt kopieren, danach ist es weg:",
    tokenNever: "nie benutzt", tokenRevoke: "widerrufen",
    confirmRevoke: "Dieses Token widerrufen? Der Tracker verliert die Verbindung.",
    trackerSetup: (url) => `Im Tracker unter <em>Arena</em> eintragen: Server <code>${url}</code> und das Token.`,
    btnCopy: "Kopieren", copied: "Kopiert",
    newAthlete: "Athlet anlegen", btnInvite: "Neue Einladung", btnDelete: "Löschen",
    btnCreateAthlete: "Athlet anlegen",
    roleAdmin: "Admin",
    adminNoRace: "Als Admin verwaltest du die Arena – mitrudern kannst du damit nicht.",
    confirmDeleteAthlete: (n) => `${n} mit allen Einheiten löschen?`,
    inviteReady: "Link zum Neuvergeben – einmal gültig:",
    invitePending: "Einladung offen",
    nameTaken: "Den Namen gibt es schon",
    logout: "Abmelden",
  },
  en: {
    locale: "en-GB",
    appName: "WaterRower Arena",
    loginHint: "Sign in with your name and password.",
    labelName: "Name", labelPassword: "Password", labelNewPassword: "New password",
    labelDisplayName: "Display name",
    btnLogin: "Sign in", loginFailed: "Wrong name or password",
    joinTitle: "Welcome to the arena", btnJoin: "Get started",
    joinWho: (n) => `This invitation is for ${n}. Pick a password.`,
    joinInvalid: "This invitation is no longer valid. Ask for a new one.",
    pwShort: (n) => `The password needs at least ${n} characters.`,
    pwKinds: "Three of four: lower case, upper case, digits, anything else.",
    themeAuto: "Auto", themeLight: "Light", themeDark: "Dark",
    navArena: "Arena", navRace: "Race", navSessions: "Sessions",
    navRecords: "Records", navBadges: "Badges", navAccount: "Account",
    badgesSummary: (got, all) => `${got} of ${all} badges.`,
    badgesHiddenLeft: (n) => n === 1 ? "One is still undiscovered." : `${n} are still undiscovered.`,
    badgesRecent: "Recently earned", badgesNone: "Nothing earned yet.",
    badgeUndiscovered: "Undiscovered",
    badgeUndiscoveredNote: "A hidden badge. What it takes is written here once you have it.",
    badgeWasHidden: "hidden", badgeHidden: "hidden",
    badgeNobody: "Nobody has this yet.",
    badgeYouEarned: "Badge unlocked",
    badgesAdminHint: "A rule is always a metric, a comparison and a threshold. Checked when a session closes and when a race ends.",
    badgeNew: "New badge", badgeAdd: "Add",
    badgeName: "Name", badgeIcon: "Mark", badgeNote: "Description",
    badgeMetric: "Metric", badgeOp: "Comparison", badgeThreshold: "Threshold",
    badgeHiddenLabel: "Hidden - shown only once somebody has it",
    badgeConfirmDelete: (n) => `Delete "${n}"? Everyone who has it loses it.`,
    opAtLeast: "at least", opAtMost: "at most",
    metric_sessions_total: "Sessions in total", metric_distance_total: "Metres in total",
    metric_session_distance: "Metres in one session", metric_session_duration: "Length of a session",
    metric_session_start_hour: "Hour it started", metric_best_500: "Best 500 m",
    metric_best_1000: "Best 1000 m", metric_best_2000: "Best 2000 m",
    metric_best_5000: "Best 5000 m", metric_best_10000: "Best 10000 m",
    metric_furthest_1200: "Furthest in 20 minutes", metric_furthest_3600: "Furthest in 60 minutes",
    metric_race_wins: "Wins in total", metric_race_win_streak: "Wins in a row",
    metric_day_streak: "Days in a row", metric_race_margin_s: "Winning margin",
    connOn: "connected", connOff: "disconnected", connWait: "connecting …",
    loadFailed: (why) => `Could not be loaded${why ? ": " + why : "."}`,
    tryAgain: "Try again",

    arenaNow: "On the water now", arenaWeek: "This week",
    nobodyRowing: "Nobody is rowing right now.",
    endSession: "End session",
    confirmEnd: "End your session now? The monitor keeps its display.",
    endSent: "Ending …",
    endFailed: "Could not end the session",
    offline: "offline", idle: "ready", rowing: "rowing",
    lastSeen: (s) => `last seen ${s}`,

    raceRunning: "Race in progress", raceOpen: "Race open – join in?",
    raceGo: "Go to the race",
    raceHistory: "Past races", raceNone: "No race rowed yet.",
    newRace: "New race", raceName: "Name", raceMode: "Mode",
    ownRace: "Your own race",
    templates: "Templates",
    templatesHint: "Tap one and the race is set up.",
    templatesAdminHint: "The athletes pick from these instead of filling the form every time.",
    templatesNone: "No template yet.",
    templateNew: "New template", templateAdd: "Add",
    templateNote: "Note",
    modeDistance: "Distance", modeTime: "Time", modeFree: "Just row",
    raceTarget: "Target", targetMetres: "metres", targetMinutes: "minutes",
    btnCreate: "Create race", btnJoinRace: "Join", btnLeave: "Leave",
    btnReady: "Ready", btnNotReady: "Not ready", btnStart: "Start",
    btnAbort: "Cancel", btnEnd: "End race", btnClear: "Clear result",
    btnGhost: "Add ghost",
    ghostPick: "Race against which recording?", ghostNone: "No recording with enough data.",
    lobby: "Starting order", waitingFor: "Waiting for the host",
    readyCount: (r, n) => `${r} of ${n} ready`,
    countdown: "Get ready …", go: "Go!",
    resetHint: "Every monitor is being zeroed. Do not row until the gun.",
    elapsed: "Time", toGo: "to go", ahead: "ahead", behind: "behind",
    finished: "finished", dnf: "did not finish",
    place: "Place", results: "Result",
    onlyHost: "Only the host can do that",
    raceBusy: "A race is already running",
    needOnline: (n) => `${n} is offline – no tracker, no data.`,

    filterAthlete: "Athlete", filterRange: "Range", allAthletes: "All",
    range7: "7 days", range30: "30 days", range90: "90 days", rangeAll: "Everything",
    sessionsEmpty: "No session recorded yet.",
    open: "open", inCompare: "in comparison", compare: "compare", delete: "delete",
    confirmDelete: "Delete this session permanently?",
    maxCompare: "At most four sessions can be compared.",
    clearSelection: "Clear selection", pickSession: "Pick a session on the left.",
    exportCsv: "CSV",
    exportXlsx: "Excel", exportAll: "Everything as Excel",
    backupTitle: "Backup",
    backupHint: "The whole arena in one file - athletes, sessions, samples, races, badges. It also holds password hashes and open invitation codes, so it belongs somewhere private.",
    backupDownload: "Download the database",
    chartSpeed: "Speed in m/s", chartSpm: "Stroke rate",
    chartCmp: "Distance from the start of each session",
    compareTitle: "Comparison", noSamples: "No samples", avg: "avg",

    recordsDistance: "Best times", recordsTime: "Furthest distances",
    recordsTotals: "Totals", recordsH2h: "Head to head",
    recordsEmpty: "Nothing recorded yet that runs long enough.",
    h2hEmpty: "No race decided yet.",
    h2hLine: (a, b, n) => `${a} beats ${b} ${n}×`,
    colSessions: "Sessions", colDistance: "Distance", colTime: "Time", colStrokes: "Strokes",

    accProfile: "Profile", accTokens: "Tracker connection", accAdmin: "Athletes",
    accSecurity: "Security",
    secIntro: "That many failures lock out, for that many minutes. The same span is the memory: stop trying and the counter runs out on its own.",
    secZero: "A 0 in the failures column switches that lockout off.",
    secLimit: "Failures", secMinutes: "Lockout (minutes)",
    secLoginIp: "Sign-in per address",
    secLoginIpHint: "One address guessing at any account.",
    secLoginName: "Sign-in per account",
    secLoginNameHint: "One account guessed at from anywhere. Looser on purpose - this one can be used to lock somebody out.",
    secInviteIp: "Invitations per address",
    secInviteIpHint: "Wrong codes from one address. A code is 96 bits, so a wrong one is a typo or somebody fishing.",
    secUplinkIp: "Tracker sign-in per address",
    secUplinkIpHint: "Trackers offering a token that is not one. A token is 256 bits - this is not about guessing, but about sockets opened for free.",
    kind_uplink: "tracker",
    btnReset: "Reset password",
    resetHelp: "Clears the password, signs the account out everywhere and hands you a one-time link to set a new one.",
    secBlocked: "Active lockouts", secNoBlocks: "Nothing is locked out right now.",
    secFor: (d) => `${d} left`,
    secUnblock: "lift", secUnblockAll: "Lift all lockouts",
    secRefresh: "Refresh",
    secFailures: (h) => `Failed attempts, last ${h} hours`,
    secNoFailures: "No failed attempts. Quiet here.",
    secFailureCount: (n) => `${n} attempts refused.`,
    secTopIp: "Busiest addresses", secTopName: "Busiest accounts",
    secWhat: "Kind", secAddress: "Address",
    kind_login: "sign-in", kind_invite: "invitation",
    pol_login_ip: "sign-in/IP", pol_login_name: "sign-in/account", pol_invite_ip: "invite/IP",
    btnSave: "Save", saved: "Saved", saveFailed: "Saving failed",
    labelColor: "Colour",
    changePassword: "Change password", labelOldPassword: "Current password",
    tokenIntro: "Your tracker signs in with a token. It is shown once and never again.",
    btnNewToken: "New token", tokenLabel: "Label", tokenNone: "No token yet.",
    tokenCreated: "Token created – copy it now, it will not be shown again:",
    tokenNever: "never used", tokenRevoke: "revoke",
    confirmRevoke: "Revoke this token? The tracker loses its connection.",
    trackerSetup: (url) => `In the tracker under <em>Arena</em>: server <code>${url}</code> and the token.`,
    btnCopy: "Copy", copied: "Copied",
    newAthlete: "Add athlete", btnInvite: "New invitation", btnDelete: "Delete",
    btnCreateAthlete: "Add athlete",
    roleAdmin: "Admin",
    adminNoRace: "As an admin you run the arena – rowing in it is not part of the job.",
    confirmDeleteAthlete: (n) => `Delete ${n} and every session?`,
    inviteReady: "Link to set a new password – valid once:",
    invitePending: "invitation pending",
    nameTaken: "That name is taken",
    logout: "Sign out",
  },
};

let lang = "en";
try { lang = localStorage.getItem("lang") || (navigator.language.startsWith("de") ? "de" : "en"); } catch {}
if (!I18N[lang]) lang = "en";
const t = (key, ...args) => { const v = I18N[lang][key]; return typeof v === "function" ? v(...args) : v; };
const locale = () => I18N[lang].locale;

function applyLang() {
  document.documentElement.lang = lang;
  document.querySelectorAll("[data-i18n]").forEach((n) => { n.textContent = t(n.dataset.i18n); });
  document.querySelectorAll("[data-i18n-html]").forEach((n) => { n.innerHTML = t(n.dataset.i18nHtml); });
  document.querySelectorAll(".lang button").forEach((b) => {
    const on = b.dataset.lang === lang;
    b.classList.toggle("active", on);
    b.setAttribute("aria-pressed", String(on));
  });
}

function setLang(next) {
  if (!I18N[next] || next === lang) return;
  lang = next;
  try { localStorage.setItem("lang", lang); } catch {}
  applyLang();
  render();
}

// --- Theme ----------------------------------------------------------------

const THEME = { series: [] };
function readTheme() {
  const s = getComputedStyle(document.documentElement);
  const v = (name, fallback) => s.getPropertyValue(name).trim() || fallback;
  THEME.series = [v("--series-1", "#2a78d6"), v("--series-2", "#eb6834"),
                  v("--series-3", "#1baf7a"), v("--series-4", "#eda100")];
  THEME.grid = v("--grid", "#e4e6dc");
  THEME.muted = v("--muted", "#7c8076");
  THEME.ink = v("--ink", "#1c1f22");
  THEME.accent = v("--accent", "#a9601f");
}

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
  readTheme();
}

function setTheme(next) {
  theme = next;
  try { localStorage.setItem("theme", theme); } catch {}
  applyTheme();
  render();
}

// --- Formatting -----------------------------------------------------------

const fmtDur = (s) => {
  s = Math.max(0, Math.round(s || 0));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`
           : `${m}:${String(sec).padStart(2, "0")}`;
};
const fmtTime = (s) => {
  if (s == null) return "–";
  const whole = Math.floor(s), frac = Math.round((s - whole) * 10);
  return `${fmtDur(whole)}.${frac}`;
};
const fmtSplit = (ms) => (!ms || ms <= 0.1 ? "--:--" : fmtDur(500 / ms));
const fmtInt = (n) => Math.round(n || 0).toLocaleString(locale());
const fmtMetres = (m) => `${fmtInt(m)} m`;
const fmtDate = (ts) => new Date(ts * 1000).toLocaleString(locale(),
  { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
const fmtDay = (ts) => new Date(ts * 1000).toLocaleDateString(locale(), { day: "2-digit", month: "2-digit" });
const fmtAgo = (ts) => {
  const d = Math.max(0, Date.now() / 1000 - ts);
  if (d < 90) return lang === "de" ? "gerade eben" : "just now";
  if (d < 5400) return `${Math.round(d / 60)} min`;
  if (d < 172800) return `${Math.round(d / 3600)} h`;
  return fmtDay(ts);
};
const MIN_PASSWORD = 12;
function passwordProblem(pw) {
  if (pw.length < MIN_PASSWORD) return t('pwShort', MIN_PASSWORD);
  const kinds = [/[a-zäöüß]/.test(pw), /[A-ZÄÖÜ]/.test(pw), /[0-9]/.test(pw),
                 /[^\p{L}\p{N}]/u.test(pw)].filter(Boolean).length;
  return kinds < 3 ? t('pwKinds') : null;
}

const athleteName = (id) => (STATE.athletes.find((a) => a.id === id) || {}).display_name || "?";
const athleteColor = (id) => (STATE.athletes.find((a) => a.id === id) || {}).color || THEME.series[0];

// --- API ------------------------------------------------------------------

async function api(path, opts = {}) {
  const res = await fetch(path, {
    credentials: "same-origin",
    headers: opts.body ? { "Content-Type": "application/json" } : {},
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 401 && STATE.me) { STATE.me = null; showGate(); throw new Error("unauthorised"); }
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch {}
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return res.status === 204 ? null : res.json();
}

/* A view whose data does not arrive used to leave an empty page and no
   word about why - a blank tab reads as a broken app, which is worse than
   the error it is hiding. */
function viewFailed(host, err) {
  if (!host) return;
  host.innerHTML = "";
  const box = el("p", "empty");
  box.appendChild(document.createTextNode(t("loadFailed", (err && err.message) || "")));
  const again = el("a", null, t("tryAgain"));
  again.href = "#";
  again.onclick = (e) => { e.preventDefault(); render(); };
  box.appendChild(document.createTextNode(" "));
  box.appendChild(again);
  host.appendChild(box);
}

// --- Sign in --------------------------------------------------------------

function showGate() {
  $("app").hidden = true;
  $("gate").hidden = false;
  if (STATE.socket) { STATE.socket.close(); STATE.socket = null; }
  const code = new URLSearchParams(location.hash.slice(1).replace(/^join\?/, "")).get("code")
    || new URLSearchParams(location.search).get("invite");
  if (code) startJoin(code);
}

async function startJoin(code) {
  $("login-form").hidden = true;
  const form = $("join-form");
  form.hidden = false;
  try {
    const who = await api(`/api/invite/${encodeURIComponent(code)}`);
    $("join-who").textContent = t("joinWho", who.display_name || who.name);
    $("join-display").value = who.display_name || "";
  } catch {
    $("join-who").textContent = t("joinInvalid");
    form.querySelector("button").disabled = true;
    return;
  }
  form.onsubmit = async (e) => {
    e.preventDefault();
    const msg = $("join-msg");
    const weak = passwordProblem($("join-pass").value);
    if (weak) { msg.className = "form-msg err"; msg.textContent = weak; return; }
    msg.className = "form-msg"; msg.textContent = "";
    try {
      STATE.me = await api("/api/join", {
        method: "POST",
        body: { code, password: $("join-pass").value, display_name: $("join-display").value.trim() },
      });
      history.replaceState(null, "", location.pathname);
      await enterApp();
    } catch (err) {
      msg.className = "form-msg err";
      msg.textContent = err.message || t("joinInvalid");
    }
  };
}

$("login-form").onsubmit = async (e) => {
  e.preventDefault();
  const msg = $("login-msg");
  msg.className = "form-msg"; msg.textContent = "";
  try {
    STATE.me = await api("/api/login", {
      method: "POST",
      body: { name: $("login-name").value.trim(), password: $("login-pass").value },
    });
    await enterApp();
  } catch (err) {
    msg.className = "form-msg err";
    // Being throttled is worth saying out loud - otherwise it reads as a
    // wrong password and they keep typing.
    msg.textContent = err.status === 429 ? err.message : t("loginFailed");
  }
};

async function logout() {
  await api("/api/logout", { method: "POST" }).catch(() => {});
  STATE.me = null;
  location.reload();
}

// --- Live socket ----------------------------------------------------------

function setConn(cls, key) {
  const n = $("conn");
  if (!n) return;
  n.className = "conn " + cls;
  $("conn-text").textContent = t(key);
}

function connect() {
  if (STATE.socket) STATE.socket.close();
  setConn("", "connWait");
  const url = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/live`;
  const ws = new WebSocket(url);
  STATE.socket = ws;

  ws.onopen = () => setConn("on", "connOn");
  ws.onclose = () => {
    setConn("off", "connOff");
    if (STATE.me) setTimeout(connect, 3000);   // Cloudflare recycles idle tunnels
  };
  ws.onmessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }
    switch (msg.type) {
      case "hello":
        msg.athletes.forEach((a) => STATE.live.set(a.athlete_id, a));
        STATE.race = msg.race;
        paintMySession();
        render();
        break;
      case "live":
        msg.athletes.forEach((a) => STATE.live.set(a.athlete_id, a));
        // Outside the view hooks on purpose: the bar belongs to every tab,
        // and each view resets those hooks when it renders.
        paintMySession();
        onLive();
        break;
      case "race":
        STATE.race = msg.race;
        onRace();
        break;
      case "achievement":
        badgeToast(msg);
        if (STATE.view === "badges") render();
        break;
      case "race_result":
      case "session":
      case "session_deleted":
        onData(msg);
        break;
    }
  };
}

// --- Routing --------------------------------------------------------------

const VIEWS = {};       // filled in by views.js and race.js

/* An admin administers: no tiles, no races, no sessions, no leaderboards.
   With one tab left the tab strip is noise, so it goes too. */
const ADMIN_VIEWS = ["account"];
const allowedView = (name) =>
  STATE.me && STATE.me.is_admin && !ADMIN_VIEWS.includes(name) ? "account" : name;

function applyNav() {
  const adminOnly = STATE.me && STATE.me.is_admin;
  document.querySelectorAll("#nav button").forEach((b) => {
    b.hidden = adminOnly && !ADMIN_VIEWS.includes(b.dataset.view);
  });
  const nav = $("nav");
  if (nav) nav.hidden = adminOnly && ADMIN_VIEWS.length < 2;
}

function setView(name) {
  name = allowedView(name);
  if (!VIEWS[name]) name = allowedView("arena");
  STATE.view = name;
  try { localStorage.setItem("view", name); } catch {}
  document.querySelectorAll("#nav button").forEach((b) => {
    const on = b.dataset.view === name;
    b.classList.toggle("active", on);
    b.setAttribute("aria-selected", String(on));
  });
  render();
}

/* Several things can ask for a redraw at once - the socket's first frame,
   the view switch, a resize. Collapse them into one paint per frame rather
   than rebuilding the page (and refetching its data) three times. */
let renderPending = false;
function render() {
  if (renderPending) return;
  renderPending = true;
  requestAnimationFrame(() => {
    renderPending = false;
    renderNow();
  });
}

/* Who is signed in, in the header. With an admin account and a rowing
   account in the same browser this is the difference between them. */
function paintWhoami() {
  const n = $("whoami");
  if (!n || !STATE.me) return;
  n.textContent = STATE.me.display_name + (STATE.me.is_admin ? " · Admin" : "");
}

function renderNow() {
  applyLang();
  paintWhoami();
  const host = $("view");
  if (!host || !STATE.me) return;
  host.innerHTML = "";
  const tpl = $(`tpl-${STATE.view}`);
  if (tpl) host.appendChild(tpl.content.cloneNode(true));
  applyLang();
  VIEWS[STATE.view]();
  renderFooter();
}

/* The three hooks the live socket calls. A view that wants live updates
   overrides them in its render; the default is a full redraw, which is
   cheap enough for pages this small. */
let onLive = () => {};
let onRace = () => { if (STATE.view === "arena" || STATE.view === "race") render(); };
let onData = () => { if (STATE.view !== "race") render(); };

function renderFooter() {
  const n = $("foot-version");
  if (n && STATE.version) {
    n.textContent = `WaterRower Arena ${STATE.version.version} · ${STATE.version.commit}`;
  }
}

// --- Boot -----------------------------------------------------------------

async function enterApp() {
  $("gate").hidden = true;
  $("app").hidden = false;
  STATE.athletes = await api("/api/athletes").catch(() => []);
  STATE.version = await api("/api/version").catch(() => null);
  applyNav();
  let saved = "arena";
  try { saved = localStorage.getItem("view") || "arena"; } catch {}
  connect();
  setView(saved);
}

async function boot() {
  applyTheme();
  applyLang();
  document.querySelectorAll(".lang button").forEach((b) => { b.onclick = () => setLang(b.dataset.lang); });
  document.querySelectorAll("#theme button").forEach((b) => { b.onclick = () => setTheme(b.dataset.theme); });
  document.querySelectorAll("#nav button").forEach((b) => { b.onclick = () => setView(b.dataset.view); });
  $("logout").onclick = logout;

  try {
    STATE.me = await api("/api/me");
    await enterApp();
  } catch {
    showGate();
  }
}

window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (theme === "auto") { readTheme(); render(); }
});

let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { if (STATE.me) render(); }, 250);
});

document.addEventListener("DOMContentLoaded", boot);
