/* ============================================================
   MODULE: "על החברה" — description, then (collapsed) what notable
   investors / CEOs said, sector & industry, and factor profile.
   Data: profiles.json + voices.json
   ============================================================ */
(function () {
  'use strict';
  const FC = window.FC, h = FC.h;
  const TYPE_HE = { article: 'כתבה', interview: 'ראיון', video: 'וידאו', filing: 'דיווח' };

  FC.sections.register({
    id: 'profile', order: 40, title: 'על החברה',
    summary(c) {
      const p = c.profile;
      return [p.subHe || p.sectorHe, c.voices.length ? `${c.voices.length} אזכורים` : null].filter(Boolean).join(' · ');
    },
    render(c) {
      const p = c.profile;
      const out = [h('p', { class: 'prose' }, p.desc || 'תיאור החברה יתווסף בעדכון הבא.')];

      if (c.voices.length) {
        out.push(h('details', { class: 'sub' }, h('summary', null, `מה אמרו עליה לאחרונה (${c.voices.length})`),
          h('div', { class: 'sub-body' }, c.voices.map((v) => h('div', { class: 'voice' },
            h('span', { class: 'w' }, v.who),
            h('span', { class: 'x' }, v.he),
            h('span', { class: 'm' }, `${TYPE_HE[v.type] || 'כתבה'} · ${v.src}${v.date ? ' · ' + v.date : ''} · `, h('a', { href: v.url, target: '_blank', rel: 'noopener' }, 'לקריאה')))))));
      }

      out.push(h('details', { class: 'sub' }, h('summary', null, 'סקטור, תעשייה ומדדים'),
        h('div', { class: 'sub-body' },
          h('div', { class: 'kv' },
            h('div', null, h('span', { class: 'k' }, 'סקטור'), h('span', { class: 'v', style: 'font-family:var(--font-body)' }, p.sectorHe || '—')),
            h('div', null, h('span', { class: 'k' }, 'תעשייה'), h('span', { class: 'v', style: 'font-family:var(--font-body)' }, p.subHe || '—')),
            h('div', null, h('span', { class: 'k' }, 'סיווג GICS'), h('span', { class: 'v', style: 'font-family:var(--font-body);font-size:var(--fs-sm)' }, [p.sector, p.sub].filter(Boolean).join(' / ') || '—')),
            h('div', null, h('span', { class: 'k' }, 'מדדים'), h('span', { class: 'v', style: 'font-family:var(--font-body);font-size:var(--fs-sm)' }, (p.tags || []).map((t) => FC.TAG_HE[t] || t).join(' · ') || '—'))
          ))));

      const f = p.factors || [];
      out.push(h('details', { class: 'sub' }, h('summary', null, 'פקטורים'),
        h('div', { class: 'sub-body' },
          f.length ? h('div', { class: 'factor' }, f.flatMap((x) => [h('b', null, x.he), h('span', null, x.why)])) : h('p', { class: 'muted' }, 'אין מספיק נתונים לחישוב.'),
          h('p', { class: 'src' }, 'מחושב אוטומטית מנתוני השוק: גודל לפי שווי שוק; Value/Growth לפי מכפיל מול חציון הסקטור ב-S&P 500; מומנטום לפי מיקום המחיר בטווח 52 שבועות; דיבידנד מעל 3%; בטא.'))));
      return out;
    }
  });
})();
