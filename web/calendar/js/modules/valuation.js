/* ============================================================
   MODULE: "שווי ומכפילים" — market cap, EV, P/E, forward P/E and more.
   Data: market/<asof>.json quotes[ticker]
   ============================================================ */
(function () {
  'use strict';
  const FC = window.FC, h = FC.h;
  const cell = (k, v, hi) => h('div', null, h('span', { class: 'k' }, k), h('span', { class: 'v' + (hi && v !== '—' ? ' hi' : '') }, v));

  FC.sections.register({
    id: 'valuation', order: 30, title: 'שווי ומכפילים',
    summary(c) {
      const q = c.quote;
      if (!q.mcap) return 'אין נתוני שוק';
      return `שווי ${FC.money(q.mcap)}${q.fpe ? ' · מכפיל עתידי ' + FC.x(q.fpe) : q.pe ? ' · מכפיל ' + FC.x(q.pe) : ''}`;
    },
    render(c) {
      const q = c.quote, t = c.ev.ticker;
      if (!q.mcap) {
        return [h('p', { class: 'muted' }, 'לחברה הזו אין עדיין נתוני שוק במערכת (למשל מניה שנסחרת רק בתל אביב). הנתונים יתווספו בשכבת הנתונים של ת"א.')];
      }
      const ev = q.ev, ebitda = q.ebitda;
      const evEbitda = q.evEbitda || (ev && ebitda ? ev / ebitda : null);
      const kids = [
        h('div', { class: 'kv' },
          cell('שווי שוק', FC.money(q.mcap), true),
          cell('שווי פעילות (EV)', FC.money(ev), true),
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
      kids.push(h('p', { class: 'src' }, `נכון לסגירה ${FC.store.marketAsOf ? FC.shortDate(FC.store.marketAsOf) : ''} · `,
        [src.base, src.valuation].filter(Boolean).join(' · '), ' · ',
        h('a', { href: `https://finance.yahoo.com/quote/${encodeURIComponent(t)}/key-statistics/`, target: '_blank', rel: 'noopener' }, 'לנתונים חיים')));
      return kids;
    }
  });
})();
