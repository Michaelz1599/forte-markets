/* ============================================================
   LAYER: live market data for the calendar (written by the dashboard's daily pipeline)
   - data/live.json: implied move from the options market for upcoming reports, and the actual
     move + EPS vs consensus after each report; a short Hebrew summary per reported company.
   - data/why.json: written each night for the largest reporters: what was reported (rep), what happened to the stock
     and why (he), and links to the press release and the call transcript.
   - data/extra.json: events added outside the weekly build (missed companies, weeks before the calendar started).
   - data/maya.json: Israeli report dates and conference-call times from Maya (pipeline/maya.py, every run).
   Adds two categories to the company panel and a "move" column to the day tables (week.js).
   ============================================================ */
(function () {
  'use strict';
  const FC = window.FC, h = FC.h;
  const load = FC.store.load.bind(FC.store);
  FC.store.load = async function () {
    const r = await load();
    const [live, why, extra, maya] = await Promise.all([FC.getJSON('data/live.json').catch(() => ({})), FC.getJSON('data/why.json').catch(() => ({})), FC.getJSON('data/extra.json').catch(() => ({})), FC.getJSON('data/maya.json').catch(() => ({}))]);
    const have = new Set((this.events || []).map((e) => e.id));
    const add = (extra.events || []).filter((e) => e && e.id && !have.has(e.id));
    if (add.length) {
      this.events = this.events.concat(add);
      for (const e of add) (this.byTicker[e.ticker] = this.byTicker[e.ticker] || []).push(e);
    }
    for (const [t, pr] of Object.entries(extra.profiles || {})) if (!this.profiles[t]) this.profiles[t] = pr;
    // Israeli report dates and call times from Maya: new companies are added; known ones only gain a missing call time
    const byId = new Map(this.events.map((e) => [e.id, e]));
    for (const m of maya.events || []) {
      const cur = byId.get(m.id);
      if (!cur) { this.events.push(m); byId.set(m.id, m); (this.byTicker[m.ticker] = this.byTicker[m.ticker] || []).push(m); continue; }
      if (cur.call && !cur.call.time && !cur.call.note && m.call && (m.call.time || m.call.note)) cur.call = Object.assign({}, cur.call, { time: m.call.time, tz: m.call.tz, note: m.call.note });
    }
    for (const [t, pr] of Object.entries(maya.profiles || {})) if (!this.profiles[t]) this.profiles[t] = pr;
    const wk = new Set((this.weeks || []).map((w) => w.id));
    const wAdd = (extra.weeks || []).filter((w) => w && w.id && !wk.has(w.id));
    if (wAdd.length) this.weeks = this.weeks.concat(wAdd).sort((a, b) => (a.id < b.id ? -1 : 1));
    this.live = { implied: live.implied || {}, results: live.results || {}, reported: live.reported || {}, asof: live.asof };
    this.why = why.items || {};
    this.digests = why.digests || {};
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
    const r = L.results[ev.id], im = L.implied[ev.id], rp = (L.reported || {})[ev.id];
    if (r && r.move != null) {
      const big = im && im.move ? Math.abs(r.move) > im.move : null;
      return h('span', { class: 'mv ' + (r.move >= 0 ? 'up' : 'dn'), title: `תנועה ביום התגובה לדוח${im ? ' · השוק תמחר ±' + (im.move * 100).toFixed(1) + '%' : ''}` }, sgn(r.move), big != null ? h('small', null, big ? ' מעל המגולם' : ' בתוך המגולם') : null);
    }
    if (rp && rp.ext != null) return h('span', { class: 'mv ' + (rp.ext >= 0 ? 'up' : 'dn'), title: (rp.extKind === 'post' ? 'במסחר המאוחר' : 'במסחר המוקדם') + ' אחרי הדוח · התנועה ביום התגובה תתעדכן אחרי הסגירה' }, sgn(rp.ext), h('small', null, rp.extKind === 'post' ? ' מאוחר' : ' מוקדם'));
    if (im && im.move) return h('span', { class: 'mv im', title: `תנועה מגולמת באופציות (פקיעה ${FC.shortDate(im.exp)})` }, '±' + (im.move * 100).toFixed(1) + '%');
    return h('span', { class: 'muted' }, '—');
  };

  const pp = (v) => (v == null || isNaN(v) ? '—' : (v * 100).toFixed(1) + '%');
  const pts = (v) => (v == null || isNaN(v) ? '' : ` (${v >= 0 ? '+' : '−'}${Math.abs(v * 100).toFixed(1)} נק' משנה שעברה)`);
  const gap = (a, e) => (a != null && e ? (a / e - 1) : null);
  const cash = (v, cur) => (cur === 'ILS' ? (v == null || isNaN(v) ? '—' : '₪' + (Math.abs(v) >= 1e9 ? (v / 1e9).toFixed(2) + 'B' : (v / 1e6).toFixed(0) + 'M')) : FC.money(v));

  /* the report in short: a bottom line and 3-4 points (written each night for the largest reporters) */
  FC.sections.register({
    id: 'analysis', order: 4, title: 'ניתוח הדוח בקצרה',
    summary(c) { const w = (FC.store.why || {})[c.ev.id]; return w && w.an && w.an.bl ? w.an.bl : 'ייכתב בלילה שאחרי הדוח, לחברות הגדולות'; },
    render(c) {
      const w = (FC.store.why || {})[c.ev.id], an = w && w.an;
      if (!an || !an.bl) return h('p', { class: 'muted' }, 'ניתוח קצר נכתב בלילה שאחרי הדוח לחברות הגדולות של השבוע.');
      return [h('p', { class: 'an-bl' }, an.bl), h('ul', { class: 'an-pts' }, ...(an.pts || []).map((t) => h('li', null, t))),
        w.src ? h('p', { class: 'src' }, 'מקורות: הודעת החברה, שיחת הוועידה והסיקור בתקשורת · ', h('a', { href: w.src, target: '_blank', rel: 'noopener' }, 'כתבה')) : null];
    }
  });

  /* actual against consensus: revenue, EPS, growth, margins, guidance */
  FC.sections.register({
    id: 'numbers', order: 6, title: 'בפועל מול הקונצנזוס',
    summary(c) {
      const n = numbers(c.ev); if (!n) return 'יתעדכן אחרי הדוח';
      const parts = [];
      if (n.rev != null && n.cur !== 'local') parts.push('הכנסות ' + cash(n.rev, n.cur) + (n.revEst ? ` (${sgn(gap(n.rev, n.revEst))} מהצפי)` : ''));
      if (n.revYoY != null) parts.push('צמיחה ' + sgn(n.revYoY));
      return parts.join(' · ') || 'פורסם';
    },
    render(c) {
      const n = numbers(c.ev);
      if (!n) return h('p', { class: 'muted' }, 'המספרים יופיעו אחרי הדוח: בלילה לחברות הגדולות, ולשאר אחרי ש-Yahoo Finance מעדכן את הדוח הרבעוני (לרוב יום-יומיים).');
      const row = (k, v, note) => h('div', null, h('span', { class: 'k' }, k), h('span', { class: 'v' }, v, note ? h('small', null, ' ' + note) : null));
      const revGap = gap(n.rev, n.revEst), epsGap = gap(n.eps, n.epsEst);
      return [
        h('div', { class: 'kv' },
          n.rev != null ? row('הכנסות', n.cur === 'local' ? '—' : cash(n.rev, n.cur), n.revEst ? `צפי ${cash(n.revEst, n.cur)} · ${sgn(revGap)}` : '') : null,
          n.ni != null ? row('רווח נקי', cash(n.ni, n.cur), n.niYoY != null ? `${sgn(n.niYoY)} משנה שעברה` : '') : null,
          n.revYoY != null ? row('צמיחה בהכנסות משנה שעברה', sgn(n.revYoY)) : null,
          n.eps != null ? row(n.epsAdj ? 'רווח למניה (מתואם)' : 'רווח למניה', n.cur === 'ILS' ? '₪' + n.eps.toFixed(2) : FC.usd(n.eps), n.epsEst != null ? `צפי ${FC.usd(n.epsEst)} · ${sgn(epsGap)}` : '') : null,
          n.gm != null ? row('שולי רווח גולמי', pp(n.gm), pts(n.gmYoY)) : null,
          n.om != null ? row('שולי רווח תפעולי', pp(n.om), pts(n.omYoY)) : null,
          n.guide ? row('תחזית לרבעון הבא', n.guide) : null),
        h('p', { class: 'src' }, n.from === 'pr' ? 'לפי הודעת החברה (נתונים מתואמים כשהחברה מפרסמת כאלה); הקונצנזוס מהעדכון השבועי.' : 'Yahoo Finance (דוח רבעוני, GAAP); קונצנזוס ההכנסות מהעדכון השבועי. לשולי הרווח אין קונצנזוס זמין, ולכן ההשוואה היא לרבעון המקביל אשתקד.' + (n.cur === 'local' ? ' חברה זרה: הדוח במטבע שלה, לכן מוצגות רק צמיחה ושוליים.' : ''))
      ];
    }
  });
  function numbers(ev) {
    const L = FC.store.live || {}, w = (FC.store.why || {})[ev.id], f = (L.fin || {})[ev.id], r = (L.results || {})[ev.id] || (L.reported || {})[ev.id];
    const cons = ev.consensus || {};
    if (w && w.fin && Object.keys(w.fin).length) return { from: 'pr', revEst: ev.market === 'US' ? cons.rev : null, epsEst: ev.market === 'US' ? cons.eps : null, ...w.fin };
    if (!f && !(r && r.epsAct != null)) return null;
    return { from: 'yahoo', ...(f || {}), eps: r && r.epsAct, epsEst: r && r.epsEst };
  }

  /* the night's reports in short, at the top of the US week (written each night) */
  FC.digest = function (st) {
    const D = FC.store.digests || {};
    const days = Object.keys(D).filter((d) => d >= st.week && d <= FC.addDays(st.week, 6)).sort();
    if (!days.length) return null;
    let cur = days[days.length - 1];
    const box = h('section', { class: 'digest' });
    const draw = () => {
      const d = D[cur] || {};
      box.textContent = '';
      box.append(
        h('div', { class: 'dg-head' }, h('b', null, 'הדוחות בקצרה'),
          h('span', { class: 'dg-days' }, ...days.map((x) => h('button', { type: 'button', class: 'dg-day' + (x === cur ? ' on' : ''), onclick: () => { cur = x; draw(); } }, FC.shortDate(x))))),
        d.bl ? h('p', { class: 'an-bl' }, d.bl) : null,
        h('ul', { class: 'an-pts' }, ...(d.pts || []).map((t) => h('li', null, t))));
    };
    draw();
    return box;
  };

  FC.sections.register({
    id: 'result', order: 5, title: 'מה קרה בדוח',
    summary(c) {
      const L = FC.store.live || { results: {} }, r = L.results[c.ev.id], rp = (L.reported || {})[c.ev.id], w = (FC.store.why || {})[c.ev.id];
      if (!r && (rp || w)) return 'פורסם' + (rp && rp.surprise != null ? ' · EPS ' + (rp.surprise >= 0 ? 'מעל' : 'מתחת') + ' לצפי' : '') + (rp && rp.ext != null ? ` · ${sgn(rp.ext)} ${rp.extKind === 'post' ? 'במסחר המאוחר' : 'במסחר המוקדם'}` : '');
      if (!r) return c.ev.date < FC.todayIL() ? 'יתעדכן אחרי יום המסחר שאחרי הדוח' : 'הדוח עוד לא פורסם';
      return `${sgn(r.move)} ביום התגובה${r.surprise != null ? ' · EPS ' + (r.surprise >= 0 ? 'מעל' : 'מתחת') + ' לצפי' : ''}`;
    },
    render(c) {
      const ev = c.ev, L = FC.store.live || { results: {} }, r = L.results[ev.id], w = (FC.store.why || {})[ev.id], rp = (L.reported || {})[ev.id];
      const im = (L.implied || {})[ev.id];
      const srcLink = w && w.src ? [' · ', h('a', { href: w.src, target: '_blank', rel: 'noopener' }, 'מקור לסיכום')] : null;
      if (!r) {
        if (!rp && !w) return h('p', { class: 'muted' }, ev.date < FC.todayIL() ? 'הסיכום יופיע אחרי פרסום הדוח.' : 'הדוח עוד לא פורסם.');
        return [
          h('p', { class: 'res-sum' }, (w && w.rep) || (rp && rp.he) || '', w && w.he ? ' ' + w.he : ''),
          h('div', { class: 'kv' },
            rp && rp.ext != null ? h('div', null, h('span', { class: 'k' }, rp.extKind === 'post' ? 'במסחר המאוחר' : 'במסחר המוקדם'), h('span', { class: 'v hi ' + (rp.ext >= 0 ? 'pos' : 'neg') }, sgn(rp.ext))) : null,
            im ? h('div', null, h('span', { class: 'k' }, 'השוק תמחר'), h('span', { class: 'v' }, '±' + (im.move * 100).toFixed(1) + '%')) : null,
            rp && rp.epsAct != null ? h('div', null, h('span', { class: 'k' }, 'רווח למניה בפועל'), h('span', { class: 'v' }, FC.usd(rp.epsAct), rp.epsEst != null ? h('small', null, ` צפי ${FC.usd(rp.epsEst)}`) : null)) : null,
            rp && rp.surprise != null ? h('div', null, h('span', { class: 'k' }, 'הפתעה ב-EPS'), h('span', { class: 'v ' + (rp.surprise >= 0 ? 'pos' : 'neg') }, sgn(rp.surprise))) : null),
          h('p', { class: 'src' }, 'התנועה ביום המסחר שאחרי הדוח תתעדכן בלילה, אחרי הסגירה בוול סטריט. EPS ומחיר המסחר המאוחר: Yahoo Finance.', srcLink)
        ];
      }
      return [
        h('p', { class: 'res-sum' }, (w && w.rep) || r.he || '', w && w.he ? ' ' + w.he : ''),
        h('div', { class: 'kv' },
          h('div', null, h('span', { class: 'k' }, `תנועה ביום התגובה (${FC.shortDate(r.d1)})`), h('span', { class: 'v hi ' + (r.move >= 0 ? 'pos' : 'neg') }, sgn(r.move))),
          h('div', null, h('span', { class: 'k' }, 'מול S&P 500'), h('span', { class: 'v' }, sgn(r.ex))),
          im ? h('div', null, h('span', { class: 'k' }, 'השוק תמחר'), h('span', { class: 'v' }, '±' + (im.move * 100).toFixed(1) + '%')) : null,
          r.epsAct != null ? h('div', null, h('span', { class: 'k' }, 'רווח למניה בפועל'), h('span', { class: 'v' }, FC.usd(r.epsAct), r.epsEst != null ? h('small', null, ` צפי ${FC.usd(r.epsEst)}`) : null)) : null,
          r.surprise != null ? h('div', null, h('span', { class: 'k' }, 'הפתעה ב-EPS'), h('span', { class: 'v ' + (r.surprise >= 0 ? 'pos' : 'neg') }, sgn(r.surprise))) : null),
        h('p', { class: 'src' }, 'תנועה: סגירה ביום התגובה מול הסגירה שלפני הדוח (Yahoo Finance). EPS בפועל ממאגר Yahoo.', srcLink)
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
