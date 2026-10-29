/* ============================================================
   MODULE: "קבוצת השוואה ו-Leading Indicators"
   Peers that also report in the loaded weeks are clickable.
   Data: profiles.json (peers, li, liLevel)
   ============================================================ */
(function () {
  'use strict';
  const FC = window.FC, h = FC.h;

  FC.sections.register({
    id: 'peers', order: 50, title: 'קבוצת השוואה ו-Leading Indicators',
    summary(c) {
      const p = c.profile;
      const reporting = (p.peers || []).filter((x) => FC.store.byTicker[x]).length;
      return [(p.peers || []).slice(0, 3).join(', '), reporting ? `${reporting} מדווחות בתקופה` : null].filter(Boolean).join(' · ');
    },
    render(c) {
      const p = c.profile;
      const peers = (p.peers || []).map((x) => {
        const evs = FC.store.byTicker[x];
        if (evs && evs.length) {
          const e = evs[0];
          return h('button', { class: 'tag-btn', type: 'button', onclick: () => FC.panel.open(e.id), title: 'פתיחת החברה' },
            h('span', { class: 'tk' }, x), h('span', { class: 'when' }, `מדווחת ${FC.dayName(e.date)} ${FC.shortDate(e.date)}`));
        }
        const q = FC.store.market[x];
        return h('span', { class: 'tag-btn' }, h('span', { class: /^[A-Z.\-]+$/.test(x) ? 'tk' : '' }, x), q && q.mcap ? h('span', { class: 'muted num' }, FC.money(q.mcap)) : null);
      });
      return [
        h('div', { class: 'tags' }, peers.length ? peers : h('span', { class: 'muted' }, 'לא הוגדרה קבוצת השוואה.')),
        h('p', { class: 'src' }, p.peersAuto ? 'נבחרו אוטומטית: החברות הגדולות באותה תת-תעשייה (GICS) ב-S&P 500.' : 'קבוצת השוואה שנבחרה ידנית.'),
        h('details', { class: 'sub' }, h('summary', null, 'Leading Indicators — מה כדאי לעקוב לפני הדוח'),
          h('div', { class: 'sub-body' },
            (p.li || []).length ? h('ul', { class: 'ul' }, p.li.map((x) => h('li', null, x))) : h('p', { class: 'muted' }, 'לא הוגדרו.'),
            h('p', { class: 'src' }, p.liLevel === 'company' ? 'אינדיקטורים ייעודיים לחברה (טיוטת מחקר).' : 'אינדיקטורים ברמת התעשייה (טיוטת מחקר).')))
      ];
    }
  });
})();
