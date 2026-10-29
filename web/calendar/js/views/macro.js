/* ============================================================
   LAYER: macro — separate from earnings. Own data file (data/macro.json),
   own tab ("מאקרו"), own filters. US + Israel: rates, inflation, labour,
   growth, consumer, politics.
   ============================================================ */
(function () {
  'use strict';
  const FC = window.FC, h = FC.h;
  const M = (FC.macro = { events: [], loaded: false, country: FC.pref.get('mCountry', 'ALL'), highOnly: FC.pref.get('mHigh', false) });
  const CAT_HE = { rates: 'ריבית', inflation: 'אינפלציה', labor: 'תעסוקה', growth: 'צמיחה', consumer: 'צרכן', politics: 'פוליטיקה', fiscal: 'פיסקלי' };
  const C_HE = { US: 'ארה"ב', IL: 'ישראל' };

  M.ready = (async () => {
    try {
      const man = await FC.getJSON('data/manifest.json');
      const d = await FC.getJSON(man.macro || 'data/macro.json');
      M.events = d.events || []; M.generated = d.generated;
    } catch (e) { M.events = []; }
    M.loaded = true;
    if (FC.state && FC.state.week && FC.render) FC.render();
  })();

  M.all = () => M.events.slice();
  M.filtered = () => M.events.filter((e) => (M.country === 'ALL' || e.country === M.country) && (!M.highOnly || e.imp >= 3));
  M.weeks = () => {
    if (!M.events.length) return [];
    const out = []; let w = FC.mondayOf(M.events[0].date); const last = M.events[M.events.length - 1].date;
    while (w <= last) { out.push(w); w = FC.addDays(w, 7); }
    return out;
  };
  M.months = () => [...new Set(M.events.map((e) => e.date.slice(0, 7)))].sort();
  M.countWeek = (wk) => M.filtered().filter((e) => e.date >= wk && e.date <= FC.addDays(wk, 6)).length;

  function when(e, tz) {
    if (!e.time) return { main: 'כל היום', alt: '' };
    return FC.describe(e.date, e.time, e.tz, tz);
  }
  function rel(date) {
    const t = FC.todayIL();
    const d = Math.round((new Date(date + 'T12:00:00Z') - new Date(t + 'T12:00:00Z')) / 864e5);
    if (d === 0) return 'היום'; if (d === 1) return 'מחר'; if (d === -1) return 'אתמול';
    return d > 0 ? `בעוד ${d} ימים` : 'התקיים';
  }
  const bars = (n) => h('span', { class: 'imp', title: ['', 'חשיבות נמוכה', 'חשיבות בינונית', 'חשיבות גבוהה'][n], 'aria-label': ['', 'חשיבות נמוכה', 'חשיבות בינונית', 'חשיבות גבוהה'][n] },
    [1, 2, 3].map((i) => h('i', { class: i <= n ? 'on' : '' })));
  const flag = (c) => h('span', { class: 'cflag c-' + c }, C_HE[c]);

  // ---------- filters row (shown instead of the earnings filters)
  M.filters = function (st) {
    const seg = (items, cur, onPick, label) => h('div', { class: 'seg', role: 'group', 'aria-label': label }, items.map(([v, l]) =>
      h('button', { type: 'button', 'aria-pressed': String(cur === v), onclick: () => onPick(v) }, l)));
    return h('div', { class: 'tb-row filters' },
      seg([['ALL', 'הכל'], ['US', 'ארה"ב'], ['IL', 'ישראל']], M.country, (v) => { M.country = v; FC.pref.set('mCountry', v); FC.render(); }, 'מדינה'),
      seg([[FC.TZ.IL, 'שעון ישראל'], [FC.TZ.NY, 'שעון ניו יורק']], st.tz, (v) => { st.tz = v; FC.pref.set('tz', v); FC.render(); }, 'אזור זמן'),
      h('label', { class: 'chk' }, h('input', { type: 'checkbox', id: 'mhigh', checked: M.highOnly ? true : null, onchange: (e) => { M.highOnly = e.target.checked; FC.pref.set('mHigh', M.highOnly); FC.render(); } }), 'רק אירועים בחשיבות גבוהה'));
  };

  // ---------- one agenda row (expandable)
  function row(e, st) {
    const w = when(e, st.tz), past = e.date < FC.todayIL();
    const det = h('details', { class: 'mrow' + (past ? ' past' : '') + (e.imp >= 3 ? ' hi' : ''), id: 'm-' + e.id },
      h('summary', null,
        h('span', { class: 'm-time num' }, w.main),
        flag(e.country),
        h('span', { class: 'm-name' }, h('b', null, e.he), e.period ? h('span', { class: 'm-per' }, e.period) : null),
        bars(e.imp),
        h('span', { class: 'm-val hide-sm' }, h('small', null, 'קודם'), h('span', null, e.prev || '—')),
        h('span', { class: 'm-val hide-sm' }, h('small', null, 'צפי'), h('span', null, e.fcst || '—')),
        FC.icon('chev', 'chev')),
      h('div', { class: 'm-body' },
        e.why ? h('p', { class: 'prose' }, e.why) : null,
        h('div', { class: 'kv three' },
          h('div', null, h('span', { class: 'k' }, 'מועד'), h('span', { class: 'v', style: 'font-family:var(--font-body);font-size:var(--fs-sm)' }, `${FC.longDate(e.date)}${e.time ? ' · ' + w.main : ''}`)),
          h('div', null, h('span', { class: 'k' }, 'קריאה קודמת'), h('span', { class: 'v', style: 'font-family:var(--font-body);font-size:var(--fs-sm)' }, e.prev || '—')),
          h('div', null, h('span', { class: 'k' }, 'צפי (קונצנזוס)'), h('span', { class: 'v', style: 'font-family:var(--font-body);font-size:var(--fs-sm)' }, e.fcst || 'טרם פורסם'))),
        e.time ? h('p', { class: 'muted' }, `בשעון ${st.tz === FC.TZ.IL ? 'ניו יורק' : 'ישראל'}: ${w.alt}`) : null,
        e.note ? h('p', { class: 'muted' }, e.note) : null,
        h('div', { class: 'when-actions' },
          FC.ics ? h('a', { class: 'btn sm', href: FC.ics.outlookLink(e), target: '_blank', rel: 'noopener' }, FC.icon('cal'), 'הוספה ל-Outlook') : null,
          e.src && e.src.url ? h('a', { class: 'btn ghost sm', href: e.src.url, target: '_blank', rel: 'noopener' }, FC.icon('link'), 'מקור: ' + e.src.label) : null)));
    return det;
  }

  // ---------- week
  function week(root, st) {
    const end = FC.addDays(st.week, 6);
    const evs = M.filtered().filter((e) => e.date >= st.week && e.date <= end);
    const key = evs.filter((e) => e.imp >= 3);
    if (!M.loaded) { root.append(h('p', { class: 'muted' }, 'טוען אירועי מאקרו…')); return; }
    root.append(h('p', { class: 'lede' }, 'אירועי המאקרו המשפיעים ביותר בארה"ב ובישראל. לחיצה על אירוע פותחת הסבר, קריאה קודמת וצפי, מקור והוספה ליומן.'));
    if (key.length) {
      root.append(h('section', { class: 'mkey', 'aria-label': 'האירועים המרכזיים השבוע' },
        h('div', { class: 'sec-h' }, h('h2', null, 'האירועים המרכזיים השבוע')),
        h('div', { class: 'mkey-grid' }, key.map((e) => {
          const w = when(e, st.tz);
          return h('button', { class: 'mcard c-' + e.country + (e.date < FC.todayIL() ? ' past' : ''), type: 'button', onclick: () => { const d = document.getElementById('m-' + e.id); if (d) { d.open = true; d.scrollIntoView({ behavior: 'smooth', block: 'center' }); } } },
            h('span', { class: 'mc-top' }, flag(e.country), h('span', { class: 'mc-rel' }, rel(e.date))),
            h('span', { class: 'mc-name' }, e.he),
            h('span', { class: 'mc-when num' }, `${FC.dayName(e.date)} ${FC.shortDate(e.date)}${e.time ? ' · ' + w.main : ''}`),
            h('span', { class: 'mc-per' }, [e.period, e.prev ? 'קודם: ' + e.prev : null].filter(Boolean).join(' · ')));
        }))));
    }
    const days = [...new Set(evs.map((e) => e.date))].sort();
    if (!days.length) root.append(h('div', { class: 'mempty' }, h('b', null, 'אין אירועי מאקרו בשבוע הזה לפי הסינון.'), h('span', null, ' נסו "הכל" או את השבוע הבא.')));
    for (const d of days) {
      const de = evs.filter((e) => e.date === d).sort((a, b) => (a.time || '99').localeCompare(b.time || '99'));
      root.append(h('section', { class: 'dsec' },
        h('h3', { class: 'dsec-h' }, h('span', { class: 'dsw d' + Math.min(4, FC.dayIndex(d)) }), FC.longDate(d), h('span', { class: 'dsec-c' }, `${de.length} אירועים`)),
        h('div', { class: 'mlist' }, de.map((e) => row(e, st)))));
    }
    root.append(h('p', { class: 'src' }, 'מקורות: הפדרל ריזרב, BLS, BEA, Census, ISM, בנק ישראל, הלמ"ס ועיתונות כלכלית. אירועים שהמועד שלהם לא אושר ממקור רשמי מסומנים בהערה.'));
  }

  // ---------- month
  function month(root, st) {
    const [y, m] = st.month.split('-').map(Number);
    const first = `${st.month}-01`, last = FC.iso(new Date(Date.UTC(y, m, 0)));
    const evs = M.filtered().filter((e) => e.date >= first && e.date <= last);
    const grid = h('div', { class: 'month mmonth', role: 'grid', 'aria-label': 'לוח מאקרו חודשי' });
    grid.append(h('div', { class: 'month-head' }, ['שני', 'שלישי', 'רביעי', 'חמישי', 'שישי'].map((d) => h('div', null, d))));
    let wk = FC.mondayOf(first);
    while (wk <= last) {
      const r = h('div', { class: 'month-row', role: 'row' });
      for (let i = 0; i < 5; i++) {
        const d = FC.addDays(wk, i), inM = d >= first && d <= last;
        const de = evs.filter((e) => e.date === d).sort((a, b) => b.imp - a.imp);
        r.append(h(inM ? 'button' : 'div', { class: 'mcell' + (inM ? '' : ' out'), type: inM ? 'button' : null, onclick: inM ? () => { st.view = 'week'; st.week = FC.mondayOf(d); FC.render(); } : null },
          h('span', { class: 'd' }, h('span', { class: 'n' }, String(+d.slice(8)))),
          inM && de.length ? h('span', { class: 'mchips' }, de.map((e) => h('span', { class: 'mchip c-' + e.country + (e.imp >= 3 ? ' hi' : '') }, e.he))) : null));
      }
      grid.append(r); wk = FC.addDays(wk, 7);
    }
    root.append(grid);
  }

  FC.views = FC.views || {};
  FC.views.macro = (root, st) => (st.view === 'month' ? month(root, st) : week(root, st));
})();
