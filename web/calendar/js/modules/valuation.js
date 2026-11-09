/* ============================================================
   MODULE: "שווי ומכפילים" — market cap, EV, P/E, forward P/E and more.
   Data: market/<asof>.json quotes[ticker]
   ============================================================ */
(function () {
  'use strict';
  const FC = window.FC, h = FC.h;
  // multiples collected with the analysts' views (data/analysts.json) fill what the market snapshot lacks
  function quoteOf(c) {
    const q = Object.assign({}, c.quote);
    const a = FC.analystOf && FC.analystOf(c.ev.ticker), m = a && a.mult;
    if (m) {
      for (const k of ['pe', 'fpe', 'ps', 'pb', 'evEbitda', 'peg', 'mcap', 'ev']) if ((q[k] == null || isNaN(q[k])) && m[k] != null) { q[k] = m[k]; q._filled = true; }
      if (q._filled) q._multSrc = m.src, q._multAsof = m.asof || a.asof, q._mcapCur = m.cur;
    }
    return q;
  }
  const cell = (k, v, hi) => h('div', null, h('span', { class: 'k' }, k), h('span', { class: 'v' + (hi && v !== '—' ? ' hi' : '') }, v));

  FC.sections.register({
    id: 'valuation', order: 30, title: 'שווי ומכפילים',
    summary(c) {
      const q = quoteOf(c);
      if (!q.mcap && q.pe == null && q.fpe == null) return 'אין נתוני שוק';
      if (!q.mcap) return [q.fpe ? 'מכפיל עתידי ' + FC.x(q.fpe) : '', q.pe ? 'מכפיל ' + FC.x(q.pe) : ''].filter(Boolean).join(' · ');
      const capTxt = q._mcapCur && q._mcapCur !== 'USD' ? `${(q.mcap / 1e9).toFixed(1)} מיליארד ${q._mcapCur === 'ILS' ? '₪' : q._mcapCur}` : FC.money(q.mcap);
      return `שווי ${capTxt}${q.fpe ? ' · מכפיל עתידי ' + FC.x(q.fpe) : q.pe ? ' · מכפיל ' + FC.x(q.pe) : ''}`;
    },
    render(c) {
      const q = quoteOf(c), t = c.ev.ticker;
      if (!q.mcap && q.pe == null && q.fpe == null) {
        return [h('p', { class: 'muted' }, 'לחברה הזו אין עדיין נתוני שוק במערכת (למשל מניה שנסחרת רק בתל אביב). הנתונים יתווספו בשכבת הנתונים של ת"א.')];
      }
      const ev = q.ev, ebitda = q.ebitda;
      const evEbitda = q.evEbitda || (ev && ebitda ? ev / ebitda : null);
      const kids = [
        h('div', { class: 'kv' },
          cell('שווי שוק', q._mcapCur && q._mcapCur !== 'USD' && q.mcap ? `${(q.mcap / 1e9).toFixed(1)} מיליארד ${q._mcapCur === 'ILS' ? '₪' : q._mcapCur}` : FC.money(q.mcap), true),
          cell('שווי פעילות (EV)', q._mcapCur && q._mcapCur !== 'USD' && ev ? `${(ev / 1e9).toFixed(1)} מיליארד ${q._mcapCur === 'ILS' ? '₪' : q._mcapCur}` : FC.money(ev), true),
          cell('מכפיל רווח (P/E)', FC.x(q.pe)),
          cell('מכפיל רווח עתידי (Forward P/E)', FC.x(q.fpe))
        )
      ];
      const more = h('div', { class: 'kv three' },
        cell('EV/EBITDA', FC.x(evEbitda)),
        cell('מכפיל מכירות (P/S)', FC.x(q.ps)),
        cell('מכפיל הון (P/B)', FC.x(q.pb)),
        cell('PEG', FC.n(q.peg)),
        cell('בטא', FC.n(q.beta)),
        cell('תשואת דיבידנד', q.div != null ? q.div.toFixed(2) + '%' : '—'),
        cell('מחיר אחרון', q.price ? '$' + q.price.toFixed(2) : '—'),
        cell('רווח למניה (12 ח׳)', FC.usd(q.eps)),
        cell('EBITDA', FC.money(ebitda))
      );
      const r52 = q.w52lo && q.w52hi && q.price && q.w52hi / q.w52lo < 2.6 ? (() => {
        const pos = ((q.price - q.w52lo) / (q.w52hi - q.w52lo)) * 100;
        return h('div', null,
          h('b', { style: 'font-size:var(--fs-sm)' }, 'טווח 52 שבועות'),
          h('div', { class: 'range', role: 'img', 'aria-label': `מחיר ${q.price} בטווח ${q.w52lo}–${q.w52hi}` },
            h('div', { class: 'track', style: 'inset-inline:0' }), h('div', { class: 'mark', style: `inset-inline-start:${Math.max(0, Math.min(100, pos))}%` })),
          h('div', { class: 'range-labels' }, h('span', null, 'Low ' + FC.usd(q.w52lo)), h('span', null, 'Last ' + FC.usd(q.price)), h('span', null, 'High ' + FC.usd(q.w52hi))));
      })() : null;
      kids.push(h('details', { class: 'sub' }, h('summary', null, 'כל המכפילים'), h('div', { class: 'sub-body' }, more, r52)));
      const src = q.src || {};
      kids.push(h('p', { class: 'src' }, c.quote.mcap ? `נכון לסגירה ${FC.store.marketAsOf ? FC.shortDate(FC.store.marketAsOf) : ''} · ` : '',
        [src.base, src.valuation].filter(Boolean).join(' · '),
        q._filled ? `${src.base || src.valuation ? ' · ' : ''}מכפילים שחסרו: ${q._multSrc || 'StockAnalysis'}${q._multAsof ? ', ' + FC.shortDate(q._multAsof) : ''}` : '', ' · ',
        h('a', { href: `https://finance.yahoo.com/quote/${encodeURIComponent(t)}/key-statistics/`, target: '_blank', rel: 'noopener' }, 'לנתונים חיים')));
      return kids;
    }
  });
})();
