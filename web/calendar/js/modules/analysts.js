/* ============================================================
   MODULE: "דעות האנליסטים" — how many analysts are bullish, neutral
   and bearish, averaged across several sites, and the average price
   target of each camp. Data: data/analysts.json items[ticker]
     sites[]  {src, url, asof, bull, neutral, bear, ptAvg, ptLow, ptHigh}
              one row per site, as that site reports it
     avg      {bull, neutral, bear, ptAvg, ptLow, ptHigh, n}  mean of the sites
     camp     {bull:{n,pt}, neutral:{n,pt}, bear:{n,pt}, ratings, from, src}
              individual ratings (latest per firm, last 12 months) by camp
     price, cur, asof
   Also loads the multiples (mult) that "שווי ומכפילים" falls back to.
   ============================================================ */
(function () {
  'use strict';
  const FC = window.FC, h = FC.h;

  // loaded once, next to the store; a missing file simply leaves the module empty
  FC.analysts = { items: {}, asof: null, loaded: false };
  FC.analystsReady = FC.getJSON('data/analysts.json').then((d) => {
    FC.analysts = { items: (d && d.items) || {}, asof: d && d.asof, loaded: true };
    if (FC.state && FC.state.openId && FC.panel) FC.panel.open(FC.state.openId);   // an open drawer picks up the data
  }).catch(() => { FC.analysts.loaded = true; });

  FC.analystOf = (t) => FC.analysts.items[t] || null;

  const CUR = { USD: '$', ILS: '₪', ILA: 'אג׳ ', EUR: '€', GBP: '£', GBX: 'p', JPY: '¥', CAD: 'C$', BRL: 'R$', HKD: 'HK$' };
  const money = (v, cur) => {
    if (v == null || isNaN(v)) return '—';
    if (cur === 'ILA') { v = v / 100; cur = 'ILS'; }   // Tel Aviv quotes in agorot: shown in shekels
    const s = CUR[cur || 'USD'] ?? '';
    const d = Math.abs(v) >= 1000 ? 0 : 2;
    const n = Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
    return `${s}${n}`;
  };
  const upside = (pt, price) => (pt != null && price ? ((pt / price) - 1) * 100 : null);
  const round1 = (v) => (v == null || isNaN(v) ? '—' : (Math.round(v * 10) / 10).toString());

  function stanceBar(b, n, s) {
    const tot = (b || 0) + (n || 0) + (s || 0); if (!tot) return null;
    const w = (x) => `${((x || 0) / tot) * 100}%`;
    return h('div', { class: 'an-bar', role: 'img', 'aria-label': `שוריים ${round1(b)}, ניטרליים ${round1(n)}, דוביים ${round1(s)}` },
      h('span', { class: 'bull', style: `width:${w(b)}` }), h('span', { class: 'neu', style: `width:${w(n)}` }), h('span', { class: 'bear', style: `width:${w(s)}` }));
  }
  function verdict(a) {
    const tot = (a.bull || 0) + (a.neutral || 0) + (a.bear || 0); if (!tot) return null;
    const sc = ((a.bull || 0) - (a.bear || 0)) / tot;
    if (sc >= 0.6) return 'קנייה חזקה';
    if (sc >= 0.25) return 'קנייה';
    if (sc > -0.25) return 'החזק';
    return 'מכירה';
  }

  FC.sections.register({
    id: 'analysts', order: 25, title: 'דעות האנליסטים',
    summary(c) {
      const a = FC.analystOf(c.ev.ticker);
      if (!a || !a.avg) return FC.analysts.loaded ? 'לא נאסף לחברה זו' : 'טוען…';
      const A = a.avg;
      return `${Math.round(A.bull)} שוריים · ${Math.round(A.neutral)} ניטרליים · ${Math.round(A.bear)} דוביים${A.ptAvg ? ' · יעד ' + money(A.ptAvg, a.cur) : ''}`;
    },
    render(c) {
      const t = c.ev.ticker, a = FC.analystOf(t);
      if (!a || !a.avg) {
        return [h('p', { class: 'muted' }, a && a.note ? a.note : 'עוד לא אספנו דעות אנליסטים לחברה הזו. בעדכון השבועי הן נאספות ל-30 החברות הגדולות שמדווחות בשבוע ולכל החברות הישראליות.')];
      }
      const A = a.avg, C = a.camp || {};
      const price = a.price;
      const tile = (cls, label, n, pt) => h('div', { class: 'an-camp ' + cls },
        h('span', { class: 'k' }, label),
        h('span', { class: 'cnt' }, round1(n)),
        h('span', { class: 'pt' }, pt && pt.pt != null ? `יעד ממוצע ${money(pt.pt, a.cur)}` : 'אין יעד'),
        pt && pt.pt != null && price ? h('span', { class: 'up ' + (pt.pt >= price ? 'pos' : 'neg') }, `${FC.pct(upside(pt.pt, price))} מהמחיר`) : null,
        pt && pt.n ? h('span', { class: 'nn' }, `${pt.n} יעדים אישיים`) : null);
      const v = verdict(A);
      const kids = [
        h('div', { class: 'an-head' },
          v ? h('span', { class: 'pill' }, `קונצנזוס: ${v}`) : null,
          h('span', { class: 'muted' }, `ממוצע של ${a.sites.length} ${a.sites.length === 1 ? 'אתר' : 'אתרים'} · כ-${Math.round(A.n || (A.bull + A.neutral + A.bear))} אנליסטים`)),
        stanceBar(A.bull, A.neutral, A.bear),
        h('div', { class: 'an-camps' },
          tile('bull', 'שוריים (קנייה)', A.bull, C.bull),
          tile('neu', 'ניטרליים (החזק)', A.neutral, C.neutral),
          tile('bear', 'דוביים (מכירה)', A.bear, C.bear)),
        h('div', { class: 'kv three' },
          h('div', null, h('span', { class: 'k' }, 'מחיר יעד ממוצע (כל האנליסטים)'), h('span', { class: 'v hi' }, money(A.ptAvg, a.cur))),
          h('div', null, h('span', { class: 'k' }, 'פוטנציאל מהמחיר'), h('span', { class: 'v' }, FC.pct(upside(A.ptAvg, price)))),
          h('div', null, h('span', { class: 'k' }, 'טווח יעדים'), h('span', { class: 'v', dir: 'ltr', style: 'unicode-bidi:isolate' }, A.ptLow != null ? `${money(A.ptLow, a.cur)} – ${money(A.ptHigh, a.cur)}` : '—'))),
      ];
      const rows = a.sites.map((s) => h('tr', null,
        h('th', null, s.url ? h('a', { href: s.url, target: '_blank', rel: 'noopener' }, s.src) : s.src),
        h('td', { class: 'num' }, s.bull ?? '—'), h('td', { class: 'num' }, s.neutral ?? '—'), h('td', { class: 'num' }, s.bear ?? '—'),
        h('td', { class: 'num' }, money(s.ptAvg, a.cur)), h('td', { class: 'num' }, s.asof ? FC.shortDate(s.asof) : '—')));
      kids.push(h('details', { class: 'sub' }, h('summary', null, 'לפי אתר'),
        h('div', { class: 'sub-body', style: 'overflow-x:auto' },
          h('table', { class: 'an-tbl' },
            h('thead', null, h('tr', null, h('th', null, 'אתר'), h('th', null, 'שוריים'), h('th', null, 'ניטרליים'), h('th', null, 'דוביים'), h('th', null, 'יעד ממוצע'), h('th', null, 'נכון ל'))),
            h('tbody', null, rows)),
          h('p', { class: 'muted' }, 'שוריים = Strong Buy + Buy (וגם Outperform / Overweight). ניטרליים = Hold / Neutral / Equal Weight. דוביים = Sell + Strong Sell (וגם Underperform / Underweight). כל אתר סופר אנליסטים קצת אחרת, ולכן ההמוצע יכול לצאת לא שלם.'),
          C.ratings ? h('p', { class: 'muted' }, `היעד לכל מחנה: ממוצע יעדי המחיר האישיים של ${C.ratings} המלצות (העדכנית לכל בית השקעות${C.from ? ', מ-' + FC.shortDate(C.from) : ''}) מתוך ${C.src || 'רשימות ההמלצות באתרים'}. מחנה בלי המלצה עם יעד = "אין יעד".`) : null)));
      kids.push(h('p', { class: 'src' }, `מחיר ${money(price, a.cur)}${a.asof ? ' · נאסף ' + FC.shortDate(a.asof) : ''} · `, a.sites.map((s, i) => [i ? ' · ' : '', s.src]),
        a.flag ? ' · ' : '', a.flag ? h('span', { class: 'pill warn' }, a.flag) : null));
      return kids;
    }
  });
})();
