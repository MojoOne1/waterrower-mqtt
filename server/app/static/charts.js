/* Canvas charts. Same approach as the tracker's: the palette is read out of
   the document (a canvas cannot use CSS variables) and the base layer is
   redrawn whenever the crosshair moves. */

function setupCanvas(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.clientWidth;
  if (!canvas.dataset.baseHeight) canvas.dataset.baseHeight = canvas.getAttribute("height");
  const maxH = Number(canvas.dataset.baseHeight);
  const aspect = Number(canvas.dataset.aspect || 0);
  const H = aspect
    ? Math.round(Math.min(maxH, Math.max(Number(canvas.dataset.minHeight || 120), W / aspect)))
    : maxH;
  canvas.width = W * dpr;
  canvas.height = H * dpr;
  canvas.style.height = H + "px";
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, W, H);
  return { ctx, W, H };
}

/* series: [{x:[], y:[], color, width, fill, label}] */
function drawLine(canvas, series, opts = {}) {
  const { ctx, W, H } = setupCanvas(canvas);
  const pad = { l: 46, r: 12, t: 12, b: 24 };
  const allX = series.flatMap((s) => s.x);
  const allY = series.flatMap((s) => s.y).filter((v) => v != null);
  if (!allX.length || !allY.length) {
    ctx.fillStyle = THEME.muted;
    ctx.font = "13px system-ui";
    ctx.fillText(t("noSamples"), pad.l, H / 2);
    canvas.onmousemove = canvas.onmouseleave = null;
    return;
  }
  const xMax = Math.max(...allX, 1);
  const yMin = opts.yMin ?? 0;
  const yMax = Math.max(...allY) * 1.08 || 1;
  const sx = (x) => pad.l + (x / xMax) * (W - pad.l - pad.r);
  const sy = (y) => H - pad.b - ((y - yMin) / (yMax - yMin)) * (H - pad.t - pad.b);

  const base = () => {
    ctx.clearRect(0, 0, W, H);
    ctx.strokeStyle = THEME.grid;
    ctx.lineWidth = 1;
    ctx.fillStyle = THEME.muted;
    ctx.font = "11px system-ui";
    ctx.textAlign = "right";
    const rows = H < 150 ? 3 : 4;
    for (let i = 0; i <= rows; i++) {
      const y = yMin + ((yMax - yMin) / rows) * i;
      ctx.beginPath();
      ctx.moveTo(pad.l, sy(y));
      ctx.lineTo(W - pad.r, sy(y));
      ctx.stroke();
      ctx.fillText(opts.yFmt ? opts.yFmt(y) : Math.round(y), pad.l - 6, sy(y) + 4);
    }
    ctx.textAlign = "center";
    const maxLabels = Math.max(2, Math.floor((W - pad.l - pad.r) / 58));
    const steps = [15, 30, 60, 120, 300, 600, 900, 1800, 3600];
    const step = steps.find((s) => xMax / s <= maxLabels) || 3600;
    for (let x = 0; x <= xMax; x += step) ctx.fillText(fmtDur(x), sx(x), H - 6);

    for (const s of series) {
      ctx.save();
      if (s.dashed) ctx.setLineDash([5, 4]);
      if (s.fill) {
        ctx.fillStyle = s.color + "2e";
        ctx.beginPath();
        ctx.moveTo(sx(s.x[0]), sy(yMin));
        s.x.forEach((x, i) => { if (s.y[i] != null) ctx.lineTo(sx(x), sy(s.y[i])); });
        ctx.lineTo(sx(s.x[s.x.length - 1]), sy(yMin));
        ctx.closePath();
        ctx.fill();
      }
      ctx.strokeStyle = s.color;
      ctx.lineWidth = s.width || 1.8;
      ctx.lineJoin = "round";
      ctx.beginPath();
      let prev = null;
      s.x.forEach((x, i) => {
        const y = s.y[i];
        if (y == null) { prev = null; return; }
        if (prev == null) ctx.moveTo(sx(x), sy(y));
        else ctx.lineTo(sx(x), sy(y));
        prev = y;
      });
      ctx.stroke();
      ctx.restore();
    }
  };
  base();

  const top = series[0];
  canvas.onmousemove = (e) => {
    const rect = canvas.getBoundingClientRect();
    const at = ((e.clientX - rect.left - pad.l) / (W - pad.l - pad.r)) * xMax;
    if (at < 0 || at > xMax) return;
    base();
    ctx.strokeStyle = THEME.ink;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(sx(at), pad.t);
    ctx.lineTo(sx(at), H - pad.b);
    ctx.stroke();
    const parts = [];
    for (const s of series) {
      let i = 0;
      while (i < s.x.length - 1 && s.x[i + 1] < at) i++;
      const v = s.y[i];
      if (v == null) continue;
      ctx.fillStyle = s.color;
      ctx.beginPath();
      ctx.arc(sx(s.x[i]), sy(v), 4, 0, Math.PI * 2);
      ctx.fill();
      parts.push(`${s.label ? s.label + " " : ""}${opts.fmt ? opts.fmt(v) : v}`);
    }
    if (opts.readout) opts.readout.textContent = `${fmtDur(at)} · ${parts.join("  ·  ")}`;
  };
  canvas.onmouseleave = () => { base(); if (opts.readout) opts.readout.textContent = ""; };
  if (top) void top;
}

function drawSpark(canvas, vals, color) {
  const { ctx, W, H } = setupCanvas(canvas);
  if (!vals || vals.length < 2) return;
  const max = Math.max(...vals) || 1;
  ctx.strokeStyle = color || THEME.series[0];
  ctx.lineWidth = 1.4;
  ctx.beginPath();
  vals.forEach((v, i) => {
    const x = (i / (vals.length - 1)) * W;
    const y = H - 2 - ((v || 0) / max) * (H - 4);
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.stroke();
}

/* Thin the samples down to `points` values of `field`, for a list sparkline. */
function reduce(samples, field, points = 40) {
  const vals = samples.map((s) => s[field] || 0);
  if (vals.length <= points) return vals;
  const step = vals.length / points;
  return Array.from({ length: points }, (_, i) => {
    const a = Math.floor(i * step), b = Math.max(a + 1, Math.floor((i + 1) * step));
    return vals.slice(a, b).reduce((x, y) => x + y, 0) / (b - a);
  });
}
