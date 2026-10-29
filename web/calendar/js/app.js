/* ============================================================
   LAYER: app shell — state, filters, masthead (Forte dashboard style),
   toolbar, routing. Markets: ארה"ב / ישראל tabs in the masthead.
   ============================================================ */
(function () {
  'use strict';
  const FC = window.FC, h = FC.h;

  const st = (FC.state = {
    view: FC.pref.get('view', 'week') === 'month' ? 'month' : 'week',
    week: null, month: null,
    tz: FC.pref.get('tz', FC.TZ.IL),
    market: ['US', 'IL', 'MACRO'].includes(FC.pref.get('market2', 'US')) ? FC.pref.get('market2', 'US') : 'US',
    sector: '', q: '', confirmedOnly: false, openId: null
  });

  FC.filtered = function () {
    const q = st.q.trim().toLowerCase();
    return FC.store.events.filter((e) => {
      const p = FC.store.profiles[e.ticker] || {};
      if (e.market !== st.market) return false;
      if (st.sector && p.sector !== st.sector) return false;
      if (st.confirmedOnly && e.status !== 'confirmed') return false;
      if (q && !(e.ticker.toLowerCase().includes(q) || (p.name || '').toLowerCase().includes(q) || (p.subHe || '').includes(q) || (p.sectorHe || '').includes(q))) return false;
      return true;
    });
  };

  /** switch market tab; on Israel jump to the first week that has Israeli reports */
  FC.setMarket = function (m) {
    st.market = m; FC.pref.set('market2', m);
    if (m === 'MACRO') {
      const mw = FC.macro ? FC.macro.weeks() : [];
      if (mw.length && !mw.includes(st.week)) { const t = FC.mondayOf(FC.todayIL()); st.week = mw.find((w) => w >= t) || mw[0]; st.month = st.week.slice(0, 7); }
      FC.render(); return;
    }
    const has = (wk) => FC.store.events.some((e) => e.market === m && e.date >= wk && e.date <= FC.addDays(wk, 4));
    if (!has(st.week)) {
      const today = FC.mondayOf(FC.todayIL());
      const wks = FC.store.weeks.map((w) => w.id).filter(has);
      const pick = wks.find((w) => w >= today) || wks[0];
      if (pick) { st.week = pick; st.month = pick.slice(0, 7); }
    }
    FC.render();
  };

  // ---------- masthead (same structure as the Forte market dashboard)
  function mast() {
    const m = FC.store.manifest;
    const upd = new Date(m.updated);
    const days = isNaN(upd) ? 99 : (Date.now() - upd.getTime()) / 864e5;
    const updTxt = isNaN(upd) ? '' : FC.fmtDate(upd.getTime(), FC.TZ.IL, { day: 'numeric', month: 'numeric' });
    const counts = { US: 0, IL: 0 };
    const wEnd = FC.addDays(st.week, 4);
    for (const e of FC.store.events) if (e.date >= st.week && e.date <= wEnd) counts[e.market] = (counts[e.market] || 0) + 1;
    counts.MACRO = FC.macro && FC.macro.loaded ? FC.macro.countWeek(st.week) : '';
    const tab = (id, label) => h('button', { class: 'tab' + (id === 'MACRO' ? ' tab-macro' : ''), role: 'tab', type: 'button', 'aria-selected': String(st.market === id), onclick: () => FC.setMarket(id) },
      label, counts[id] !== '' ? h('span', { class: 'tab-n' }, String(counts[id] || 0)) : null);
    return h('header', { class: 'mast' }, h('div', { class: 'mast-in' },
      h('div', { class: 'brand' }, h('span', { class: 'brand-name' }, 'פורטה'), h('span', { class: 'brand-sub' }, 'בית השקעות · יומן דוחות')),
      h('nav', { class: 'tabs', role: 'tablist', 'aria-label': 'שוק' }, tab('US', 'דוחות ארה"ב'), tab('IL', 'דוחות ישראל'), tab('MACRO', 'מאקרו')),
      h('div', { class: 'asof' }, h('span', { class: days < 8 ? 'dot-ok' : 'dot-warn' }),
        h('span', null, `עודכן ${updTxt} · מחירים לסגירה ${FC.shortDate(m.marketAsOf)} · היומן מתעדכן כל יום ראשון, התנועות כל יום`))));
  }

  // ---------- toolbar
  function toolbar() {
    const seg = (items, cur, onPick, label) => h('div', { class: 'seg', role: 'group', 'aria-label': label }, items.map(([v, l]) =>
      h('button', { type: 'button', 'aria-pressed': String(cur === v), onclick: () => onPick(v) }, l)));
    const isWeek = st.view !== 'month';
    let navLabel, prev, next;
    if (isWeek) {
      const weeks = st.market === 'MACRO' && FC.macro ? FC.macro.weeks() : FC.store.weeks.map((w) => w.id), i = weeks.indexOf(st.week), w = FC.store.weeks.find((x) => x.id === st.week);
      navLabel = w && w.label ? w.label : `${FC.shortDate(st.week)}–${FC.shortDate(FC.addDays(st.week, 4))}`;
      prev = i > 0 ? () => { st.week = weeks[i - 1]; FC.render(); } : null;
      next = i < weeks.length - 1 ? () => { st.week = weeks[i + 1]; FC.render(); } : null;
    } else {
      const [y, mo] = st.month.split('-').map(Number);
      navLabel = `${FC.HE_MONTHS[mo - 1]} ${y}`;
      const months = st.market === 'MACRO' && FC.macro ? FC.macro.months() : [...new Set(FC.store.events.map((e) => e.date.slice(0, 7)))].sort(), i = months.indexOf(st.month);
      prev = i > 0 ? () => { st.month = months[i - 1]; FC.render(); } : null;
      next = i < months.length - 1 ? () => { st.month = months[i + 1]; FC.render(); } : null;
    }
    const inMarket = Object.values(FC.store.profiles).filter((p) => (st.market === 'IL') === (p.country === 'IL'));
    const sectors = [...new Set(inMarket.map((p) => p.sector).filter(Boolean))].sort();
    const secHe = Object.fromEntries(inMarket.map((p) => [p.sector, p.sectorHe]));
    const themeBtn = h('button', { class: 'btn ghost sm icon', type: 'button', 'aria-label': 'מצב תצוגה בהיר/כהה', title: 'בהיר / כהה', onclick: () => {
      const cur = document.documentElement.getAttribute('data-theme');
      const dark = cur ? cur === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
      document.documentElement.setAttribute('data-theme', dark ? 'light' : 'dark'); FC.pref.set('theme', dark ? 'light' : 'dark');
    } }, FC.icon('half'));
    return h('div', { class: 'toolbar', role: 'toolbar', 'aria-label': 'ניווט וסינון' },
      h('div', { class: 'tb-row' },
        h('div', { class: 'nav' },
          h('button', { class: 'btn ghost sm icon', type: 'button', 'aria-label': 'הקודם', disabled: !prev, onclick: prev }, FC.icon('right')),
          h('h1', { class: 'nav-label', 'aria-live': 'polite' }, navLabel),
          h('button', { class: 'btn ghost sm icon', type: 'button', 'aria-label': 'הבא', disabled: !next, onclick: next }, FC.icon('left'))),
        seg([['week', 'שבוע'], ['month', 'חודש']], st.view, (v) => { st.view = v; FC.pref.set('view', v); if (v === 'month') st.month = st.week.slice(0, 7); FC.render(); }, 'תצוגה'),
        h('div', { class: 'tb-end' },
          h('button', { class: 'btn sm', type: 'button', onclick: () => FC.ics.openDialog() }, FC.icon('cal'), 'ייצוא לאאוטלוק'),
          themeBtn)),
      st.market === 'MACRO' && FC.macro ? FC.macro.filters(st) : h('div', { class: 'tb-row filters' },
        h('input', { type: 'search', id: 'q', class: 'tb-search', placeholder: 'חיפוש חברה, טיקר או תעשייה', value: st.q, 'aria-label': 'חיפוש', oninput: (e) => { st.q = e.target.value; renderMain(); } }),
        h('select', { id: 'sector', class: 'tb-select', 'aria-label': 'סקטור', onchange: (e) => { st.sector = e.target.value; renderMain(); } },
          h('option', { value: '' }, 'כל הסקטורים'), sectors.map((s) => h('option', { value: s, selected: st.sector === s ? true : null }, secHe[s] || s))),
        seg([[FC.TZ.IL, 'שעון ישראל'], [FC.TZ.NY, 'שעון ניו יורק']], st.tz, (v) => { st.tz = v; FC.pref.set('tz', v); FC.render(); }, 'אזור זמן'),
        h('label', { class: 'chk' }, h('input', { type: 'checkbox', id: 'conf', checked: st.confirmedOnly ? true : null, onchange: (e) => { st.confirmedOnly = e.target.checked; renderMain(); } }), 'רק מועדים מאומתים')));
  }

  let mainEl;
  function renderMain() {
    if (!mainEl) return;
    mainEl.textContent = '';
    const wrap = h('div', { class: 'wrap' }, toolbar());
    if (st.market === 'MACRO') { FC.views.macro(wrap, st); wrap.append(footer()); mainEl.append(wrap); return; }
    if (st.view !== 'month') {
      const w = FC.store.weeks.find((x) => x.id === st.week);
      const cov = (w && w.coverage) || {};
      let note = null;
      if (st.market === 'US' && w) note = cov.US === 'full' ? w.note : 'תצוגה מקדימה: רק מועדים שהחברות כבר הודיעו. הרשימה המלאה תתעדכן ביום ראשון.';
      if (st.market === 'IL') note = 'מועדים שהחברות הישראליות כבר הודיעו עליהם. חברות נוספות מתווספות בעדכון השבועי.';
      if (note) wrap.append(h('p', { class: 'lede' }, note));
    }
    const v = st.q && st.view !== 'month' ? 'list' : st.view;
    FC.views[v](wrap, st);
    wrap.append(footer());
    mainEl.append(wrap);
  }

  FC.render = function () {
    const root = document.getElementById('app');
    const active = document.activeElement && document.activeElement.id;
    root.textContent = '';
    mainEl = h('main', { id: 'main' });
    root.append(mast(), mainEl);
    renderMain();
    if (active) { const el = document.getElementById(active); if (el) { el.focus(); if (el.setSelectionRange && el.value) el.setSelectionRange(el.value.length, el.value.length); } }
  };

  function footer() {
    const m = FC.store.manifest;
    return h('footer', { class: 'foot' },
      h('div', null, 'מקורות: ', m.sources.concat([{ label: 'QuarterChart', url: 'https://quarterchart.com/earnings' }]).map((s, i) => [i ? ' · ' : '', s.url ? h('a', { href: s.url, target: '_blank', rel: 'noopener' }, s.label) : s.label])),
      h('div', null, 'המידע נאסף ממקורות פומביים ואינו מהווה ייעוץ השקעות. מועדים שלא אומתו מול הודעת החברה מסומנים בהתאם.'));
  }

  // ---------- boot
  (async function boot() {
    const theme = FC.pref.get('theme', null);
    if (theme) document.documentElement.setAttribute('data-theme', theme);
    const root = document.getElementById('app');
    try { await FC.store.load(); }
    catch (e) { root.textContent = 'לא ניתן לטעון את הנתונים. נסו לרענן את העמוד.'; console.error(e); return; }
    const weeks = FC.store.weeks.map((w) => w.id);
    const today = FC.todayIL(), thisMon = FC.mondayOf(today);
    const dow = new Date(today + 'T12:00:00Z').getUTCDay();
    const target = dow === 6 || dow === 0 ? FC.addDays(thisMon, 7) : thisMon;
    st.week = weeks.includes(target) ? target : (weeks.find((w) => w >= target) || weeks[weeks.length - 1]);
    st.month = st.week.slice(0, 7);
    const hash = (location.hash || '').slice(1);
    if (/^w-\d{4}-\d{2}-\d{2}$/.test(hash) && weeks.includes(hash.slice(2))) st.week = hash.slice(2);
    if (hash === 'il') st.market = 'IL';
    FC.setMarket(st.market);
    if (/^c-[A-Za-z.\-]+$/.test(hash)) {
      const evs = FC.store.byTicker[hash.slice(2).toUpperCase()];
      if (evs) { st.market = evs[0].market; st.week = FC.mondayOf(evs[0].date); FC.render(); FC.panel.open(evs[0].id); }
    }
  })();
})();
