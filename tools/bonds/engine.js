// ===== Forte bond-pair engine: curves, spreads, pair premium, fair-value models, history stats =====
// Pure functions only (no DOM). Shared by the dashboard page and by the node test harness.
const ENG = (() => {
  'use strict';
  const BUCKET = r => {
    const s = String(r || '').replace(/^il/i, '').toUpperCase();
    if (!s || s === 'NR') return 'NR';
    if (s.startsWith('AAA')) return 'AAA';
    if (s.startsWith('AA')) return 'AA';
    if (s.startsWith('A')) return 'A';
    if (s.startsWith('BBB')) return 'BBB';
    return 'NR';
  };
  const DEFAULT_CFG = {
    // annual physical PD by issuer rating (local scale). Assumptions: ilAA sits several notches below on the global scale.
    pd: { 'ilAAA': 0.0003, 'ilAA+': 0.0008, 'ilAA': 0.0010, 'ilAA-': 0.0015, 'ilA+': 0.0025, 'ilA': 0.0035, 'ilA-': 0.0050, 'ilBBB+': 0.0090, 'ilBBB': 0.0140, 'ilBBB-': 0.0220, 'NR': 0.0400 },
    lambda: { AAA: 2.5, AA: 2.5, A: 2.0, BBB: 1.5, NR: 1.5 },          // risk-neutral / physical default intensity ratio
    cs: { AAA: 0.2, AA: 0.25, A: 0.40, BBB: 0.60, NR: 0.75 },            // share of the unsecured spread that is default compensation
    lgdBase: 0.45, lgdSlope: 1.0, lgdLo: 0.25, lgdHi: 0.80, lgdForeign: 0.05, // LGD_u = base + slope*(0.30 - E/A) (+ foreign add-on)
    lgdFloorSec: 0.08,                                                    // floor on secured shortfall share (time, legal cost)
    rf: 0.035, kmvLt: 0.5,                                                // Merton: risk-free and share of long-term liabilities in default point
    w: { el: 0.4, mi: 0.3, reg: 0.3, mer: 0 },                            // composite weights
    thr: 8,                                                               // bp: minimum "meat" to call a side
    uncBase: 4, uncStale: 6, uncDur: 3, staleHour: 14,                    // uncertainty band components (bp)
    minDur: 0.7,                                                          // pairs with a leg shorter than this are flagged
    uncSpr: 0.05,                                                         // extra band: share of the unsecured spread (model error grows with the spread level)
    hyS: 400,                                                             // bp: above this unsecured spread the pair is in the high-yield / distress regime
    csLo: 200, csHi: 800,                                                 // default share of the spread rises linearly to 100% between these spreads
    minTurn: 50,                                                          // K NIS/day (90-day average): below this a leg is illiquid and no call is made
    slopeMaxS: 300,                                                       // bp: bonds wider than this are left out of the credit-curve slope
    uncAuto: 6,                                                           // bp: extra band when the collateral card was classified automatically and not reviewed
  };
  const N = x => { // standard normal CDF (Abramowitz-Stegun 26.2.17)
    const t = 1 / (1 + 0.2316419 * Math.abs(x));
    const d = 0.3989422804014327 * Math.exp(-x * x / 2);
    const p = d * t * (0.319381530 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))));
    return x > 0 ? 1 - p : p;
  };
  const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
  const mean = a => a.length ? a.reduce((s, x) => s + x, 0) / a.length : NaN;
  const sd = a => { if (a.length < 2) return NaN; const m = mean(a); return Math.sqrt(a.reduce((s, x) => s + (x - m) ** 2, 0) / (a.length - 1)); };
  const median = a => { if (!a.length) return NaN; const s = [...a].sort((x, y) => x - y); const m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };

  // ---- linear algebra (small OLS) ----
  function solve(A, b) { // Gauss-Jordan, returns x or null
    const n = A.length; const M = A.map((r, i) => [...r, b[i]]);
    for (let c = 0; c < n; c++) {
      let p = c; for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r;
      if (Math.abs(M[p][c]) < 1e-12) return null; [M[c], M[p]] = [M[p], M[c]];
      for (let r = 0; r < n; r++) if (r !== c) { const f = M[r][c] / M[c][c]; for (let k = c; k <= n; k++) M[r][k] -= f * M[c][k]; }
    }
    return M.map((r, i) => r[n] / r[i]);
  }
  function inv(A) { const n = A.length; const cols = []; for (let j = 0; j < n; j++) { const e = Array(n).fill(0); e[j] = 1; const x = solve(A, e); if (!x) return null; cols.push(x); } return A.map((_, i) => cols.map(c => c[i])); }
  function ols(X, y) {
    if (!X || !X.length) return null; const n = X.length, k = X[0].length; if (n <= k) return null;
    const XtX = Array.from({ length: k }, (_, i) => Array.from({ length: k }, (_, j) => X.reduce((s, r) => s + r[i] * r[j], 0)));
    const Xty = Array.from({ length: k }, (_, i) => X.reduce((s, r, t) => s + r[i] * y[t], 0));
    const b = solve(XtX, Xty); if (!b) return null;
    const fit = X.map(r => r.reduce((s, x, i) => s + x * b[i], 0)); const res = y.map((v, i) => v - fit[i]);
    const sse = res.reduce((s, e) => s + e * e, 0); const my = mean(y); const sst = y.reduce((s, v) => s + (v - my) ** 2, 0);
    const s2 = sse / (n - k); const Vi = inv(XtX); const se = Vi ? Vi.map((r, i) => Math.sqrt(Math.max(0, r[i] * s2))) : b.map(() => NaN);
    return { b, se, t: b.map((x, i) => x / se[i]), fit, res, r2: sst > 0 ? 1 - sse / sst : NaN, r2adj: sst > 0 ? 1 - (sse / (n - k)) / (sst / (n - 1)) : NaN, n, k, rmse: Math.sqrt(sse / (n - k)) };
  }

  // ---- Nelson-Siegel government curve ----
  function nsBasis(t, tau) { const x = Math.max(t, 1e-4) / tau; const e = Math.exp(-x); const f1 = (1 - e) / x; return [1, f1, f1 - e]; }
  function fitNS(pts) { // pts: [{t, y}]
    let best = null;
    for (let tau = 0.4; tau <= 12; tau *= 1.08) {
      const X = pts.map(p => nsBasis(p.t, tau)); const r = ols(X, pts.map(p => p.y));
      if (r && (!best || r.rmse < best.rmse)) best = { tau, b: r.b, rmse: r.rmse, n: pts.length };
    }
    if (!best) return null;
    best.at = t => nsBasis(t, best.tau).reduce((s, x, i) => s + x * best.b[i], 0);
    return best;
  }

  // ---- snapshot -> curves + spreads ----
  function buildSnap(snapQ, bonds, gov) {
    const curves = {};
    for (const L of ['C', 'S']) {
      const pts = Object.entries(gov).filter(([id, g]) => g[1] === L && snapQ[id] && snapQ[id][1] >= 0.25).map(([id]) => ({ t: snapQ[id][1], y: snapQ[id][0] }));
      curves[L] = pts.length >= 4 ? fitNS(pts) : null;
      if (curves[L]) curves[L].pts = pts;
    }
    const sp = {};
    for (const [id, b] of Object.entries(bonds)) {
      const q = snapQ[id]; const c = curves[b.link]; if (!q || !c || !isFinite(q[0]) || !isFinite(q[1])) continue;
      const g = c.at(q[1]);
      sp[id] = { ytm: q[0], dur: q[1], px: q[2], tm: q[3] || '', gov: g, s: (q[0] - g) * 100 };
    }
    return { curves, sp };
  }

  // within-issuer credit-curve slope (bp per year of duration), pooled over (issuer, secured) groups
  function creditSlope(bonds, sp, minDur = 0.7, maxDur = 8, maxS = 300) {
    const groups = {};
    for (const [id, b] of Object.entries(bonds)) { const s = sp[id]; if (!s || s.dur < minDur || s.dur > maxDur || !(s.s < maxS)) continue; const k = b.iss + '|' + (b.sec ? 1 : 0) + '|' + b.link; (groups[k] = groups[k] || []).push(s); }
    let sxy = 0, sxx = 0, n = 0;
    for (const g of Object.values(groups)) { if (g.length < 2) continue; const mx = mean(g.map(s => s.dur)), my = mean(g.map(s => s.s)); for (const s of g) { sxy += (s.dur - mx) * (s.s - my); sxx += (s.dur - mx) ** 2; n++; } }
    return { b: sxx > 0 ? sxy / sxx : 0, n };
  }

  // ---- Merton / KMV distance to default ----
  function merton(iss, cfg) {
    if (!iss || !iss.mcap || !iss.vol) return null;
    const E = iss.mcap, sE = iss.vol, D = (iss.stl || 0) + cfg.kmvLt * (iss.ltl || 0), r = cfg.rf, T = 1;
    if (!(D > 0)) return null;
    let V = E + D, sV = sE * E / V;
    for (let i = 0; i < 200; i++) {
      const d1 = (Math.log(V / D) + (r + sV * sV / 2) * T) / (sV * Math.sqrt(T)); const d2 = d1 - sV * Math.sqrt(T);
      const Vn = (E + D * Math.exp(-r * T) * N(d2)) / N(d1); const sVn = sE * E / (N(d1) * Vn);
      if (Math.abs(Vn - V) < 1e-6 * V && Math.abs(sVn - sV) < 1e-7) { V = Vn; sV = sVn; break; }
      V = Vn; sV = sVn;
    }
    const DD = (Math.log(V / D) + (r - sV * sV / 2) * T) / (sV * Math.sqrt(T));
    return { V, sV, D, DD, pd: N(-DD), lev: D / V };
  }

  function lgdU(iss, cfg, ov) {
    if (ov && isFinite(ov.lgdU)) return { v: ov.lgdU, how: 'ידני' };
    const ea = iss && iss.ta ? iss.eq / iss.ta : 0.3;
    let v = cfg.lgdBase + cfg.lgdSlope * (0.30 - ea) + (iss && iss.foreign ? cfg.lgdForeign : 0);
    return { v: clamp(v, cfg.lgdLo, cfg.lgdHi), how: `${cfg.lgdBase} + ${cfg.lgdSlope}×(0.30 − הון/מאזן ${ea.toFixed(2)})${iss && iss.foreign ? ' + חו"ל' : ''}` };
  }

  // ---- one pair, snapshot models ----
  function pairSnapshot(pair, ctx) {
    const { bonds, sp, issuers, coll, cfg, slope } = ctx;
    const bs = bonds[pair.sec], bu = bonds[pair.uns], ss = sp[pair.sec], su = sp[pair.uns];
    const iss = issuers[pair.iss] || {}; const c = coll[pair.sec] || null;
    const out = { pair, bs, bu, ss, su, iss, coll: c, ok: !!(ss && su) };
    if (!out.ok) return out;
    out.dRaw = su.s - ss.s; out.dDur = su.dur - ss.dur; out.adj = slope * out.dDur; out.d = out.dRaw - out.adj;
    const late = tm => { const h = parseInt(String(tm).split(':')[0], 10); return isFinite(h) && h < cfg.staleHour; };
    out.stale = late(ss.tm) || late(su.tm); out.short = Math.min(ss.dur, su.dur) < cfg.minDur;
    out.hy = su.s > cfg.hyS;
    const tv = [bs.turn90, bu.turn90].filter(v => v != null && isFinite(v));
    out.illiq = tv.length > 0 && Math.min(...tv) < cfg.minTurn;
    out.unc = cfg.uncBase + (out.stale ? cfg.uncStale : 0) + cfg.uncDur * Math.abs(out.dDur) + cfg.uncSpr * Math.max(0, su.s) + (c && c.auto ? cfg.uncAuto : 0);
    out.sizeR = bs.par > 0 && bu.par > 0 ? bu.par / bs.par : NaN;
    // fundamentals
    const rating = iss.rating || 'NR'; const bk = BUCKET(rating);
    const pd = cfg.pd[rating] != null ? cfg.pd[rating] : cfg.pd.NR; const lam = cfg.lambda[bk]; const cs0 = cfg.cs[bk];
    const cs = cs0 + (1 - cs0) * clamp((su.s - cfg.csLo) / (cfg.csHi - cfg.csLo), 0, 1);
    const ov = (ctx.over || {})[pair.id] || {};
    const LU = lgdU(iss, cfg, ov); const lu = LU.v;
    const cr = isFinite(ov.cr) ? ov.cr : (c ? c.cr : 1.0); const h = isFinite(ov.h) ? ov.h : (c ? c.h : 0.4);
    const short = Math.max(cfg.lgdFloorSec, 1 - cr * (1 - h)); const ls = lu * short;
    out.f = { rating, bk, pd, lam, cs, cs0, lu, luHow: LU.how, cr, h, shortfall: short, ls, dLgd: lu - ls };
    // market-implied loss ratio of the secured leg vs the unsecured leg (if the whole spread were default compensation): 1 - d / s_u
    out.implR = su.s > 0 ? 1 - out.dRaw / su.s : null;
    out.el = lam * pd * (lu - ls) * 1e4;
    out.mi = cs * Math.max(0, su.s) * (1 - ls / lu);
    const m = merton(iss, cfg); out.mer = m; out.merFair = m ? m.pd * (lu - ls) * 1e4 : null;
    out.score = c ? c.score : null;
    return out;
  }

  function regress(rows) { // rows: pairSnapshot outputs with ok
    const R = rows.filter(r => r.ok && r.score != null && !r.short && !r.hy && !r.illiq && isFinite(r.sizeR));
    if (R.length < 7) return { n: R.length, err: 'מעט מדי זוגות לרגרסיה' };
    const names = ['קבוע', 'ציון בטוחה (10 נק׳)', 'מרווח הסדרה הלא מובטחת (נ"ב)', 'ln(גודל לא מובטחת / מובטחת)'];
    const X = R.map(r => [1, r.score / 10, r.su.s, Math.log(r.sizeR)]); const y = R.map(r => r.d);
    const o = ols(X, y); if (!o) return { n: R.length, err: 'הרגרסיה לא התכנסה' };
    const fitOf = r => [1, (r.score || 0) / 10, r.su.s, Math.log(r.sizeR)].reduce((s, x, i) => s + x * o.b[i], 0);
    return { ...o, names, ids: R.map(r => r.pair.id), fitOf };
  }

  // regFixed: apply an already-fitted regression (used for extra comparisons that must not move the fit)
  function composite(rows, cfg, regFixed) {
    const reg = regFixed || regress(rows);
    for (const r of rows) {
      if (!r.ok) continue;
      r.reg = reg && reg.fitOf && r.score != null && isFinite(r.sizeR) && !r.hy ? reg.fitOf(r) : null;
      // high-yield regime: the rating-based PD and the regression (fitted on investment-grade pairs) do not apply; only the spread-implied model is used
      const parts = (r.hy ? [['mi', r.mi]] : [['el', r.el], ['mi', r.mi], ['reg', r.reg], ['mer', r.merFair]]).filter(([k, v]) => v != null && isFinite(v) && (r.hy || cfg.w[k] > 0));
      const wOf = k => r.hy ? 1 : cfg.w[k];
      const W = parts.reduce((s, [k]) => s + wOf(k), 0);
      r.fair = W > 0 ? parts.reduce((s, [k, v]) => s + wOf(k) * v, 0) / W : null;
      r.meat = r.fair != null ? r.fair - r.d : null;
      const band = Math.max(cfg.thr, r.unc);
      r.call = r.meat == null ? 'na' : r.illiq ? 'ill' : r.hy ? 'hy' : r.meat > band ? 'sec' : r.meat < -band ? 'uns' : 'neu';
      r.lean = r.meat == null ? null : r.meat > band ? 'sec' : r.meat < -band ? 'uns' : 'neu'; // the side the numbers lean to, also for hy / illiquid pairs
      r.band = band;
    }
    return reg;
  }

  // ---- history statistics on a dated series {d:[iso], v:[bp]} ----
  function histStats(d, v) {
    const n = v.length; if (!n) return null; const x = v[n - 1];
    const m = mean(v), s = sd(v); const below = v.filter(y => y < x).length, eq = v.filter(y => y === x).length;
    const at = days => { const t = Date.parse(d[n - 1]) - days * 864e5; let i = n - 1; while (i > 0 && Date.parse(d[i]) > t) i--; return Date.parse(d[i]) <= t ? v[i] : null; };
    let ar = null;
    if (n >= 12) { const X = v.slice(0, -1).map(y => [1, y]); const o = ols(X, v.slice(1)); if (o) { const phi = o.b[1]; const dt = (Date.parse(d[n - 1]) - Date.parse(d[0])) / 864e5 / (n - 1); ar = { phi, hl: phi > 0 && phi < 1 ? -Math.log(2) / Math.log(phi) * dt : null, mu: phi < 1 ? o.b[0] / (1 - phi) : null }; } }
    return { n, x, mean: m, sd: s, z: s > 0 ? (x - m) / s : NaN, pct: (below + 0.5 * eq) / n * 100, min: Math.min(...v), max: Math.max(...v), med: median(v), c1m: at(30) != null ? x - at(30) : null, c3m: at(91) != null ? x - at(91) : null, c6m: at(182) != null ? x - at(182) : null, c12m: at(365) != null ? x - at(365) : null, ar };
  }

  return { DEFAULT_CFG, BUCKET, N, ols, fitNS, buildSnap, creditSlope, merton, lgdU, pairSnapshot, composite, regress, histStats, mean, sd, median, clamp };
})();
if (typeof module !== 'undefined') module.exports = ENG;
