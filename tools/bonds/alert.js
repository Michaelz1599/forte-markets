// Weekly holdings-distortion check for the bond-pairs dashboard ("ניתוח אג"ח").
// Same engine and the same rules as the dashboard's "עיוותים באחזקות" panel: every held series is compared with
// the nearest-duration series of the other kind (secured vs unsecured) of the same issuer and linkage, and flagged when
//   free : a held UNSECURED series earns about the same or less than the secured sibling (premium <= 2bp after the duration fix)
//   sec  : a held UNSECURED series where the model says the secured sibling is cheap (meat beyond the band)
//   over : a held SECURED series where the model says the collateral is overpriced (the unsecured sibling is better)
// Pairs in the distress regime (unsecured spread > 400bp) or with an illiquid leg get no automatic call.
//
//   node tools/bonds/alert.js [base.json] [snapshot.json] [out.json]
'use strict';
const fs = require('fs');
const path = require('path');
const ENG = require('./engine.js');

const ROOT = path.resolve(__dirname, '..', '..');
const [baseF, snapF, outF] = [process.argv[2] || 'data/bonds/base.json', process.argv[3] || 'data/bonds/latest.json', process.argv[4] || 'data/bonds/alert.json'].map(f => path.resolve(ROOT, f));
const B = JSON.parse(fs.readFileSync(baseF, 'utf8'));
const snap = JSON.parse(fs.readFileSync(snapF, 'utf8'));
const prev = fs.existsSync(outF) ? JSON.parse(fs.readFileSync(outF, 'utf8')) : null;
const cfgF = path.resolve(ROOT, 'data/bonds/cfg.json');   // optional: model overrides copied from the dashboard (cfg/model)

const fmt = (v, d = 1) => v == null || !isFinite(v) ? '—' : Number(v).toFixed(d);
const fmtS = (v, d = 1) => v == null || !isFinite(v) ? '—' : (v > 0 ? '+' : '') + Number(v).toFixed(d);

function cfg() {
  const c = JSON.parse(JSON.stringify(ENG.DEFAULT_CFG));
  if (fs.existsSync(cfgF)) { const o = JSON.parse(fs.readFileSync(cfgF, 'utf8')); for (const [k, v] of Object.entries(o)) { if (v && typeof v === 'object' && !Array.isArray(v)) c[k] = { ...c[k], ...v }; else if (v != null) c[k] = v; } }
  return c;
}
const bonds = B.bonds, coll = B.coll, issuers = B.iss, gov = B.gov;
const pairs = Object.entries(B.pairs).filter(([, p]) => p && !p.removed).map(([k, p]) => ({ ...p, id: k })).sort((a, b) => (a.order ?? 99) - (b.order ?? 99));
const issName = k => (issuers[k] && issuers[k].name) || k;
const nm = k => `${issName(bonds[k].iss)} ${bonds[k].ser}`;

const C = cfg();
const built = ENG.buildSnap(snap.q, bonds, gov);
const slope = ENG.creditSlope(bonds, built.sp, C.minDur, 8, C.slopeMaxS);
const ctx = { bonds, sp: built.sp, issuers, coll, cfg: C, slope: slope.b, over: {} };
const rows = pairs.map(p => ENG.pairSnapshot(p, ctx));
const reg = ENG.composite(rows, C);

const held = new Set((B.held && B.held.ids) || []);
const dur = k => built.sp[k] && built.sp[k].dur;
const pairKey = new Map(pairs.map(p => [p.sec + '|' + p.uns, p.id]));
const comps = [];
for (const id of held) {
  const b = bonds[id]; if (!b || dur(id) == null || dur(id) < C.minDur) continue;
  const isSec = !!b.sec; if (isSec && !coll[id]) continue;
  const cand = Object.keys(bonds).filter(k => k !== id && bonds[k].iss === b.iss && bonds[k].link === b.link && !!bonds[k].sec !== isSec && (isSec || coll[k]) && dur(k) != null && dur(k) >= C.minDur && Math.abs(dur(k) - dur(id)) <= 2.5)
    .sort((a, c) => Math.abs(dur(a) - dur(id)) - Math.abs(dur(c) - dur(id)));
  if (!cand.length) continue;
  const k = cand[0]; const sec = isSec ? id : k, uns = isSec ? k : id;
  comps.push({ held: id, other: k, heldSec: isSec, p: { id: pairKey.get(sec + '|' + uns) || `H-${sec}-${uns}`, iss: b.iss, sec, uns } });
}
const crow = comps.map(o => ENG.pairSnapshot(o.p, ctx)); ENG.composite(crow, C, reg);

function signal(o, r) {
  if (!r || !r.ok || r.illiq) return null;
  if (!o.heldSec) {
    if (!r.hy && r.d <= 2) return { k: 'free', lvl: r.d <= 0 ? 2 : 1, txt: `${nm(o.other)} (מובטחת) נותנת ${r.d <= 0 ? 'מרווח גבוה יותר' : 'כמעט אותו מרווח'}: פרמיה ${fmtS(r.d)} נ"ב אחרי תיקון מח"מ, מול הוגנת ${fmt(r.fair)}. הבטוחה כמעט בחינם.` };
    if (r.call === 'sec') return { k: 'sec', lvl: 1, txt: `${nm(o.other)} (מובטחת) זולה לפי המודל: פרמיה ${fmt(r.d)} נ"ב, הוגנת ${fmt(r.fair)}, בשר ${fmtS(r.meat)} מעבר לרצועה (±${fmt(r.band, 0)}).` };
  } else if (r.call === 'uns') {
    return { k: 'over', lvl: 1, txt: `משלמים על הבטוחה יותר מהמודל: פרמיה ${fmt(r.d)} נ"ב מול הוגנת ${fmt(r.fair)} (בשר ${fmtS(r.meat)}). לשקול את ${nm(o.other)} (לא מובטחת).` };
  }
  return null;
}
const prevKeys = new Set(((prev && prev.items) || []).map(x => x.held + '|' + x.other + '|' + x.k));
const items = comps.map((o, i) => ({ o, r: crow[i], s: signal(o, crow[i]) })).filter(x => x.s)
  .map(({ o, r, s }) => ({
    held: o.held, heldName: nm(o.held), heldSec: o.heldSec, other: o.other, otherName: nm(o.other), pair: o.p.id,
    k: s.k, lvl: s.lvl, txt: s.txt, d: +fmt(r.d), fair: +fmt(r.fair), meat: +fmt(r.meat), band: +fmt(r.band, 0),
    su: +fmt(r.su.s, 0), ss: +fmt(r.ss.s, 0), durH: +fmt(dur(o.held), 2), durO: +fmt(dur(o.other), 2),
    isNew: !prevKeys.has(o.held + '|' + o.other + '|' + s.k),
  }))
  .sort((a, b) => b.lvl - a.lvl || a.d - b.d);
const okRows = rows.filter(r => r.ok).length;
const out = {
  d: snap.d, at: new Date().toISOString().slice(0, 16), snapAt: snap.at, heldAsof: B.held && B.held.asof,
  stats: { held: held.size, compared: comps.length, flagged: items.length, newFlags: items.filter(x => x.isNew).length, pairsPriced: okRows, pairs: rows.length },
  items,
};
fs.writeFileSync(outF, JSON.stringify(out, null, 1));
console.log(`${out.d}: ${items.length} distortions in ${comps.length} held comparisons (${out.stats.newFlags} new)`);
for (const x of items) console.log(`  [${x.k}${x.isNew ? ', new' : ''}] ${x.heldName} vs ${x.otherName}: ${x.txt}`);
