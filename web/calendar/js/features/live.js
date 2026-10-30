/* ============================================================
   LAYER: live market data for the calendar (written by the dashboard's daily pipeline)
   - data/live.json: implied move from the options market for upcoming reports, and the actual
     move + EPS vs consensus after each report; a short Hebrew summary per reported company.
   - data/why.json: the main reason for the move and links to the report (written each night for the week's largest reporters).
   Adds two categories to the company panel and a "move" column to the day tables (week.js).
   ============================================================ */
(function () {
  'use strict';
  const FC = window.FC, h = FC.h;
  const load = FC.store.load.bind(FC.store);
  FC.store.load = async function () {
    const r = await load();
    const [live, why] = await Promise.all([FC.getJSON('data/live.json').catch(() => ({})), FC.getJSON('data/why.json').catch(() => ({}))]);
    this.live = { implied: live.implied || {}, results: live.results || {}, asof: live.asof };
    this.why = why.items || {};
    // links found by the nightly job (press release, call transcript) fill in what the weekly build has not linked yet
    for (const ev of this.events || []) {
      const w = this.why[ev.id];
      if (w && w.links) ev.links = Object.assign({}, w.links, ev.links || {});
    }
    return r;
  };
  const sgn = (v, d = 1) => (v == null || isNaN(v) ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v * 100).toFixed(d)}%`);

  /** cell for the day tables: actual move after the report, else the move the options market prices */
  FC.moveCell = function (ev) {
    const L = FC.store.live || { implied: {}, results: {} };
    const r = L.results[ev.id], im = L.implied[ev.id];
    if (r && r.move != null) {
      const big = im && im.move ? Math.abs(r.move) > im.move : null;
      return h('span', { class: 'mv ' + (r.move >= 0 ? 'up' : 'dn'), title: `תנועה ביום התגובה לדוח${im ? ' · השוק תמחר ±' + (im.move * 100).toFixed(1) + '%' : ''}` }, sgn(r.move), big != null ? h('small', null, big ? ' מעל המגולם' : ' בתוך המגולם') : null);
    }
    if (im && im.move) return h('span', { class: 'mv im', title: `תנועה מגולמת באופציות (פקיעה ${FC.shortDate(im.exp)})` }, '±' + (im.move * 100).toFixed(1) + '%');
    return h('span', { class: 'muted' }, '—');
  };

  FC.sections.register({
    id: 'result', order: 5, title: 'מה קרה בדוח',
    summary(c) {
      const r = (FC.store.live || { results: {} }).results[c.ev.id];
      if (!r) return c.ev.date < FC.todayIL() ? 'יתעדכן אחרי יום המסחר שאחרי הדוח' : 'הדוח עוד לא פורסם';
      return `${sgn(r.move)} ביום התגובה${r.surprise != null ? ' · EPS ' + (r.surprise >= 0 ? 'מעל' : 'מתחת') + ' לצפי' : ''}`;
    },
    render(c) {
      const ev = c.ev, r = (FC.store.live || { results: {} }).results[ev.id], w = (FC.store.why || {})[ev.id];
      if (!r) return h('p', { class: 'muted' }, ev.date < FC.todayIL() ? 'הסיכום יופיע אחרי סגירת יום המסחר שאחרי הדוח.' : 'הדוח עוד לא פורסם.');
      const im = (FC.store.live.implied || {})[ev.id];
      return [
        h('p', { class: 'res-sum' }, r.he || '', w && w.he ? ' ' + w.he : ''),
        h('div', { class: 'kv' },
          h('div', null, h('span', { class: 'k' }, `תנועה ביום התגובה (${FC.shortDate(r.d1)})`), h('span', { class: 'v hi ' + (r.move >= 0 ? 'pos' : 'neg') }, sgn(r.move))),
          h('div', null, h('span', { class: 'k' }, 'מול S&P 500'), h('span', { class: 'v' }, sgn(r.ex))),
          im ? h('div', null, h('span', { class: 'k' }, 'השוק תמחר'), h('span', { class: 'v' }, '±' + (im.move * 100).toFixed(1) + '%')) : null,
          r.epsAct != null ? h('div', null, h('span', { class: 'k' }, 'רווח למניה בפועל'), h('span', { class: 'v' }, FC.usd(r.epsAct), r.epsEst != null ? h('small', null, ` צפי ${FC.usd(r.epsEst)}`) : null)) : null,
          r.surprise != null ? h('div', null, h('span', { class: 'k' }, 'הפתעה ב-EPS'), h('span', { class: 'v ' + (r.surprise >= 0 ? 'pos' : 'neg') }, sgn(r.surprise))) : null),
        h('p', { class: 'src' }, 'תנועה: סגירה ביום התגובה מול הסגירה שלפני הדוח (Yahoo Finance). EPS בפועל ממאגר Yahoo.', w && w.src ? [' · ', h('a', { href: w.src, target: '_blank', rel: 'noopener' }, 'מקור להסבר')] : null)
      ];
    }
  });

  FC.sections.register({
    id: 'implied', order: 15, title: 'מה השוק מתמחר ליום הדוח',
    summary(c) {
      const im = ((FC.store.live || {}).implied || {})[c.ev.id];
      return im && im.move ? `תנועה מגולמת ±${(im.move * 100).toFixed(1)}%` : 'אין נתוני אופציות';
    },
    render(c) {
      const im = ((FC.store.live || {}).implied || {})[c.ev.id];
      if (!im) return h('p', { class: 'muted' }, 'אין נתוני אופציות לחברה הזו, או שהדוח רחוק מדי. התמחור מחושב לדוחות של 7 הימים הקרובים.');
      return [
        h('div', { class: 'kv' },
          h('div', null, h('span', { class: 'k' }, 'תנועה מגולמת (Straddle)'), h('span', { class: 'v hi' }, '±' + (im.move * 100).toFixed(1) + '%', h('small', null, ` · כ-${FC.usd(im.move * im.spot)} למניה`))),
          h('div', null, h('span', { class: 'k' }, 'תנודתיות גלומה (IV, באט-דה-מאני)'), h('span', { class: 'v' }, im.iv != null ? (im.iv * 100).toFixed(0) + '%' : '—', im.ivNext != null ? h('small', null, ` · אחרי הדוח: ${(im.ivNext * 100).toFixed(0)}%`) : null)),
          h('div', null, h('span', { class: 'k' }, 'פקיעה'), h('span', { class: 'v' }, FC.shortDate(im.exp), h('small', null, ` · ${im.dte} ימים`)))),
        h('p', { class: 'muted' }, 'התנועה המגולמת = מחיר ה-Straddle (קול ופוט במחיר המימוש הקרוב לשער) חלקי שער המניה, בפקיעה הראשונה שאחרי הדוח. זה הטווח שהשוק משלם עליו: בערך שני שלישים מהפעמים התנועה בפועל קטנה ממנו.' + (im.dte > 7 ? ' הפקיעה רחוקה מהדוח, ולכן חלק מהמחיר הוא זמן ולא הדוח עצמו.' : '')),
        h('p', { class: 'src' }, `מקור: שרשרת האופציות ב-Yahoo Finance · ${im.at ? FC.shortDate(im.at.slice(0, 10)) : ''}`)
      ];
    }
  });
})();
