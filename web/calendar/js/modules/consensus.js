/* ============================================================
   MODULE: "ציפיות (קונצנזוס)" — analysts' EPS and revenue for the
   quarter being reported. Data: event.consensus
   ============================================================ */
(function () {
  'use strict';
  const FC = window.FC, h = FC.h;

  function rangeBar(lo, avg, hi, ya, fmt) {
    if (lo == null || hi == null || avg == null || hi <= lo) return null;
    const min = Math.min(lo, ya != null ? ya : lo), max = Math.max(hi, ya != null ? ya : hi);
    const pos = (v) => `${((v - min) / (max - min)) * 100}%`;
    return h('div', null,
      h('div', { class: 'range', role: 'img', 'aria-label': `טווח הערכות ${fmt(lo)} עד ${fmt(hi)}, ממוצע ${fmt(avg)}` },
        h('div', { class: 'track', style: `inset-inline-start:${pos(lo)};inset-inline-end:${100 - parseFloat(pos(hi))}%` }),
        h('div', { class: 'mark', style: `inset-inline-start:${pos(avg)}`, title: 'ממוצע' }),
        ya != null ? h('div', { class: 'mark ya', style: `inset-inline-start:${pos(ya)}`, title: 'לפני שנה' }) : null),
      h('div', { class: 'range-labels' }, h('span', null, fmt(min)), h('span', null, fmt(max))),
      h('div', { class: 'range-legend' }, `פס = טווח התחזיות (${fmt(lo)}–${fmt(hi)}) · קו = ממוצע ${fmt(avg)}${ya != null ? ' · נקודה = לפני שנה ' + fmt(ya) : ''}`));
  }

  FC.sections.register({
    id: 'consensus', order: 20, title: 'ציפיות האנליסטים (קונצנזוס)',
    summary(c) {
      const k = c.ev.consensus;
      if (!k) return 'לא נאסף לחברה זו';
      return `EPS ${FC.usd(k.eps)} · הכנסות ${FC.money(k.rev)}`;
    },
    render(c) {
      const k = c.ev.consensus, ev = c.ev;
      const y = encodeURIComponent(ev.ticker);
      if (!k) {
        return [h('p', { class: 'muted' }, 'עוד לא אספנו קונצנזוס לחברה הזו. בעדכון השבועי נאספות תחזיות לחברות הגדולות בכל שבוע.'),
          h('a', { class: 'link-row', href: `https://finance.yahoo.com/quote/${y}/analysis/`, target: '_blank', rel: 'noopener' }, FC.icon('globe'), h('span', null, h('span', { class: 'lt' }, 'תחזיות אנליסטים ב-Yahoo Finance')), FC.icon('link'))];
      }
      const epsYoY = k.eps != null && k.epsYearAgo ? ((k.eps - k.epsYearAgo) / Math.abs(k.epsYearAgo)) * 100 : null;
      return [
        h('div', { class: 'kv' },
          h('div', null, h('span', { class: 'k' }, `רווח למניה צפוי (${k.period || 'רבעון'})`), h('span', { class: 'v hi' }, FC.usd(k.eps))),
          h('div', null, h('span', { class: 'k' }, 'הכנסות צפויות'), h('span', { class: 'v hi' }, FC.money(k.rev))),
          h('div', null, h('span', { class: 'k' }, 'שינוי ב-EPS מול שנה שעברה'), h('span', { class: 'v' }, FC.pct(epsYoY))),
          h('div', null, h('span', { class: 'k' }, 'צמיחה בהכנסות מול שנה שעברה'), h('span', { class: 'v' }, FC.pct(k.revGrowth))),
          k.whisper != null ? h('div', null, h('span', { class: 'k' }, 'Whisper (ציפיית השוק הלא-רשמית)'), h('span', { class: 'v' }, FC.usd(k.whisper))) : null
        ),
        h('details', { class: 'sub' }, h('summary', null, 'פיזור התחזיות'),
          h('div', { class: 'sub-body' },
            h('b', { style: 'font-size:var(--fs-sm)' }, `רווח למניה · ${k.epsN ? k.epsN + ' אנליסטים' : ''}`),
            rangeBar(k.epsLow, k.eps, k.epsHigh, k.epsYearAgo, FC.usd) || h('p', { class: 'muted' }, 'אין נתוני טווח.'),
            h('b', { style: 'font-size:var(--fs-sm)' }, `הכנסות · ${k.revN ? k.revN + ' אנליסטים' : ''}`),
            rangeBar(k.revLow, k.rev, k.revHigh, k.revYearAgo, FC.money) || h('p', { class: 'muted' }, 'אין נתוני טווח.'),
            h('p', { class: 'muted' }, `לפני שנה: EPS ${FC.usd(k.epsYearAgo)} · הכנסות ${FC.money(k.revYearAgo)}`))),
        k.note ? h('p', { class: 'muted' }, k.note) : null,
        h('p', { class: 'src' }, `מקור: ${k.source} · נאסף ${k.asof ? FC.shortDate(k.asof) : ''}`, k.quality === 'low' ? ' · ' : '', k.quality === 'low' ? h('span', { class: 'pill warn' }, 'לבדיקה') : null)
      ];
    }
  });
})();
