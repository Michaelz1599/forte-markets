/* ============================================================
   MODULE: "מודלים של פורטה" — slot for Forte's internal models (DCF etc.).
   To add a model: publish data/models/<TICKER>.json and list the ticker
   in data/models/index.json. Schema (all fields optional except title):
   { title, author, updated, currency, price, fairValue,
     assumptions:[{k,v}], table:{head:[...], rows:[{k, v:[...]}]},
     sensitivity:{rowLabel, colLabel, rows:[..], cols:[..], values:[[..]]},
     file: "assets/models/MSFT.xlsx" }
   ============================================================ */
(function () {
  'use strict';
  const FC = window.FC, h = FC.h;
  let index = null;
  async function loadIndex() {
    if (index) return index;
    try { index = (await FC.getJSON('data/models/index.json')).models || {}; } catch (e) { index = {}; }
    return index;
  }
  loadIndex();

  function renderModel(m) {
    const kids = [];
    if (m.fairValue != null) {
      const up = m.price ? ((m.fairValue - m.price) / m.price) * 100 : null;
      kids.push(h('div', { class: 'kv three' },
        h('div', null, h('span', { class: 'k' }, 'שווי הוגן'), h('span', { class: 'v hi' }, FC.usd(m.fairValue))),
        h('div', null, h('span', { class: 'k' }, 'מחיר בעת המודל'), h('span', { class: 'v' }, FC.usd(m.price))),
        h('div', null, h('span', { class: 'k' }, 'פוטנציאל'), h('span', { class: 'v' }, FC.pct(up)))));
    }
    if (m.assumptions && m.assumptions.length) {
      kids.push(h('details', { class: 'sub' }, h('summary', null, 'הנחות המודל'),
        h('div', { class: 'sub-body' }, h('div', { class: 'kv' }, m.assumptions.map((a) => h('div', null, h('span', { class: 'k' }, a.k), h('span', { class: 'v' }, a.v)))))));
    }
    if (m.table && m.table.rows) {
      const t = h('table', { style: 'width:100%;border-collapse:collapse;font-size:var(--fs-sm)' },
        h('thead', null, h('tr', null, h('th'), m.table.head.map((x) => h('th', { class: 'num', style: 'text-align:center;padding:4px;background:var(--band);color:var(--band-ink)' }, x)))),
        h('tbody', null, m.table.rows.map((r) => h('tr', null, h('th', { style: 'text-align:start;padding:4px;border-top:1px solid var(--line)' }, r.k), r.v.map((x) => h('td', { class: 'num', style: 'text-align:center;padding:4px;border-top:1px solid var(--line)' }, x))))));
      kids.push(h('details', { class: 'sub' }, h('summary', null, 'תחזית'), h('div', { class: 'sub-body', style: 'overflow-x:auto' }, t)));
    }
    if (m.sensitivity) {
      const s = m.sensitivity;
      const t = h('table', { style: 'border-collapse:collapse;font-size:var(--fs-sm)' },
        h('thead', null, h('tr', null, h('th', { style: 'padding:4px' }, `${s.rowLabel} \\ ${s.colLabel}`), s.cols.map((c) => h('th', { class: 'num', style: 'padding:4px;background:var(--tier2);color:var(--tier2-ink)' }, c)))),
        h('tbody', null, s.rows.map((r, i) => h('tr', null, h('th', { class: 'num', style: 'padding:4px;background:var(--tier2);color:var(--tier2-ink)' }, r), s.values[i].map((v) => h('td', { class: 'num', style: 'padding:4px 8px;border:1px solid var(--line);text-align:center' }, v))))));
      kids.push(h('details', { class: 'sub' }, h('summary', null, 'ניתוח רגישות'), h('div', { class: 'sub-body', style: 'overflow-x:auto' }, t)));
    }
    if (m.file) kids.push(h('a', { class: 'link-row', href: m.file, target: '_blank', rel: 'noopener' }, FC.icon('doc'), h('span', null, h('span', { class: 'lt' }, 'קובץ המודל')), FC.icon('link')));
    kids.push(h('p', { class: 'src' }, [m.author, m.updated && 'עודכן ' + m.updated].filter(Boolean).join(' · ')));
    return kids;
  }

  FC.sections.register({
    id: 'models', order: 60, title: 'מודלים של פורטה',
    summary(c) { return index && index[c.ev.ticker] ? index[c.ev.ticker] : 'DCF ומודלים פנימיים'; },
    render(c) {
      const box = h('div', { class: 'cat-body', style: 'padding:0' }, h('p', { class: 'muted' }, 'טוען…'));
      loadIndex().then(async (idx) => {
        box.textContent = '';
        if (!idx[c.ev.ticker]) {
          box.append(h('p', { class: 'muted' }, 'עוד לא הוזן מודל של פורטה לחברה הזו. המקום שמור: כשמודל DCF או מודל אחר יתווסף, הוא יופיע כאן.'));
          return;
        }
        try { box.append(...renderModel(await FC.getJSON(`data/models/${encodeURIComponent(c.ev.ticker)}.json`))); }
        catch (e) { box.append(h('p', { class: 'muted' }, 'לא ניתן לטעון את המודל.')); }
      });
      return box;
    }
  });
})();
