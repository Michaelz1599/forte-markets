/* ============================================================
   LAYER: month view + list view
   ============================================================ */
(function () {
  'use strict';
  const FC = window.FC, h = FC.h;
  FC.views = FC.views || {};

  FC.views.month = function (root, st) {
    const [y, m] = st.month.split('-').map(Number);
    const first = `${st.month}-01`;
    const last = FC.iso(new Date(Date.UTC(y, m, 0)));
    const evs = FC.filtered().filter((e) => e.date >= first && e.date <= last);
    const mcap = (e) => (FC.store.market[e.ticker] || {}).mcap || 0;
    const grid = h('div', { class: 'month', role: 'grid', 'aria-label': 'לוח חודשי' });
    grid.append(h('div', { class: 'month-head' }, ['שני', 'שלישי', 'רביעי', 'חמישי', 'שישי'].map((d) => h('div', null, d))));
    const capDay = {};
    for (const e of evs) capDay[e.date] = (capDay[e.date] || 0) + ((FC.store.market[e.ticker] || {}).mcap || 0);
    const maxCap = Math.max(1, ...Object.values(capDay));
    let wk = FC.mondayOf(first);
    while (wk <= last) {
      const row = h('div', { class: 'month-row', role: 'row' });
      for (let i = 0; i < 5; i++) {
        const d = FC.addDays(wk, i);
        const inMonth = d >= first && d <= last;
        const de = evs.filter((e) => e.date === d).sort((a, b) => mcap(b) - mcap(a));
        const il = de.filter((e) => e.market === 'IL');
        const top = [...il.slice(0, 2), ...de.filter((e) => e.market !== 'IL').slice(0, 5)].slice(0, 6);
        const cell = h(inMonth ? 'button' : 'div', {
          class: 'mcell' + (inMonth ? '' : ' out'), type: inMonth ? 'button' : null,
          'aria-label': inMonth ? `${FC.longDate(d)}: ${de.length} דוחות` : null,
          onclick: inMonth ? () => { st.view = 'week'; st.week = FC.mondayOf(d); FC.render(); } : null
        },
          inMonth && capDay[d] ? h('span', { class: 'heat', style: `opacity:${(0.07 + 0.38 * Math.sqrt(capDay[d] / maxCap)).toFixed(2)}` }) : null,
          h('span', { class: 'd' }, h('span', { class: 'n' }, String(+d.slice(8))), de.length ? h('span', { class: 'c' }, `${de.length} דוחות · ${FC.money(capDay[d] || 0)}`) : null),
          inMonth && de.length ? h('span', { class: 'tks' }, top.map((e) => h('span', { class: e.market === 'IL' ? 'il' : '' }, e.ticker))) : null
        );
        row.append(cell);
      }
      grid.append(row);
      wk = FC.addDays(wk, 7);
    }
    root.append(grid);
    const covered = FC.store.weeks.filter((w) => w.id.slice(0, 7) === st.month || FC.addDays(w.id, 4).slice(0, 7) === st.month);
    root.append(h('p', { class: 'muted', style: 'margin-top:10px' },
      'החודש מציג את כל השבועות שנטענו עד עכשיו. שבועות שעוד לא עודכנו במלואם מסומנים בלוח השבועי. ',
      covered.length ? `שבועות בחודש זה: ${covered.map((w) => w.label || w.id).join(' · ')}` : 'עוד אין נתונים לחודש הזה.'));
  };

  FC.views.list = function (root, st) {
    let evs = FC.filtered();
    if (!st.q) evs = evs.filter((e) => e.date >= st.week && e.date <= FC.addDays(st.week, 4));
    const mcap = (e) => (FC.store.market[e.ticker] || {}).mcap || 0;
    evs.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : (a.session === b.session ? mcap(b) - mcap(a) : a.session === 'BMO' ? -1 : 1)));
    if (!evs.length) { root.append(h('p', { class: 'muted' }, st.q ? `לא נמצאו דוחות עבור "${st.q}".` : 'אין דוחות בשבוע הזה לפי המסננים.')); return; }
    const list = h('div', { class: 'list', role: 'list' });
    for (const e of evs) {
      const p = FC.store.profiles[e.ticker] || {};
      const tm = FC.store.timing(e, st.tz);
      list.append(h('button', { class: 'list-row', type: 'button', role: 'listitem', onclick: () => FC.panel.open(e.id) },
        FC.logo(e.ticker),
        h('span', { style: 'min-width:0' }, h('b', { class: 'tk' }, e.ticker), ' ', h('span', { class: 's' }, p.name || '')),
        h('span', { class: 's hide-sm' }, p.sectorHe || ''),
        h('span', { class: 's hide-sm num' }, FC.money((FC.store.market[e.ticker] || {}).mcap)),
        h('span', { class: 's' }, `${FC.dayName(e.date)} ${FC.shortDate(e.date)} · ${tm.call ? 'שיחה ' + tm.call.main : FC.SESSION_HE[e.session] || ''}`)
      ));
    }
    root.append(list);
  };
})();
