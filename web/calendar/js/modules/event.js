/* ============================================================
   MODULE: "הדוח ושיחת הוועידה" — links to the call, recording,
   transcripts, the report itself and sources.
   Data: event.links {pressRelease, filing, replay, transcriptCall, transcriptReport}
   (filled by the weekly update after the event).
   ============================================================ */
(function () {
  'use strict';
  const FC = window.FC, h = FC.h;

  function row(icon, title, sub, url, pending) {
    const kids = [FC.icon(icon), h('span', { style: 'min-width:0' }, h('span', { class: 'lt' }, title), sub ? h('span', { class: 'ls' }, sub) : null), url && !pending ? FC.icon('link') : h('span')];
    return url && !pending
      ? h('a', { class: 'link-row', href: url, target: '_blank', rel: 'noopener' }, kids)
      : h('div', { class: 'link-row pending' }, kids);
  }
  const g = (q) => 'https://www.google.com/search?q=' + encodeURIComponent(q);

  FC.sections.register({
    id: 'event', order: 10, title: 'הדוח ושיחת הוועידה',
    summary(c) {
      const L = c.ev.links || {};
      const n = ['replay', 'transcriptCall', 'transcriptReport', 'pressRelease'].filter((k) => L[k]).length;
      const past = c.ev.date < FC.todayIL();
      return n ? `${n} קישורים זמינים` : past ? 'קישורים יתווספו בעדכון הקרוב' : 'שידור, הקלטה ותמלולים';
    },
    render(c, st) {
      const ev = c.ev, L = ev.links || {}, p = c.profile;
      const past = ev.date < FC.todayIL();
      const label = `${ev.ticker} ${ev.period || ''}`.trim();
      const live = h('div', { class: 'links' },
        ev.call && ev.call.webcast ? row('mic', 'שידור חי של שיחת הוועידה', ev.call.webcast.replace(/^https?:\/\//, ''), ev.call.webcast) : row('mic', 'שידור חי של שיחת הוועידה', 'הקישור יתפרסם על ידי החברה', null, true),
        ev.call && ev.call.dial ? h('p', { class: 'muted' }, 'חיוג: ', h('span', { class: 'num', dir: 'ltr' }, ev.call.dial)) : null
      );
      const after = h('div', { class: 'links' },
        L.replay ? row('play', 'הקלטת השיחה', 'הקלטה רשמית', L.replay) : row('play', 'הקלטת השיחה', past ? 'בדרך כלל זמינה בעמוד השידור של החברה' : 'תהיה זמינה אחרי השיחה, לרוב בעמוד השידור', ev.call && ev.call.webcast && past ? ev.call.webcast : null, !past),
        L.transcriptCall ? row('text', 'תמלול שיחת הוועידה', L.transcriptCallSrc || '', L.transcriptCall) : row('text', 'תמלול שיחת הוועידה', past ? 'חיפוש תמלול' : 'יתפרסם אחרי השיחה', past ? g(`${label} earnings call transcript`) : null, !past),
        L.pressRelease ? row('doc', 'הודעת התוצאות (Press release)', '', L.pressRelease) : row('doc', 'הודעת התוצאות (Press release)', past ? 'חיפוש ההודעה' : 'תתפרסם במועד הדוח', past ? g(`${p.name || ev.ticker} ${ev.period || ''} results press release`) : null, !past),
        L.transcriptReport ? row('doc', 'הדוח המלא', L.transcriptReportSrc || '', L.transcriptReport) : null
      );
      const filings = h('div', { class: 'links' });
      if (ev.market === 'US' && p.cik) filings.append(row('globe', 'דיווחים ל-SEC (8-K / 10-Q)', 'EDGAR', `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=${p.cik}&type=8-K&dateb=&owner=include&count=40`));
      else if (ev.market === 'US') filings.append(row('globe', 'דיווחים ל-SEC (6-K / 20-F)', 'EDGAR', `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company=&CIK=${encodeURIComponent(ev.ticker)}&type=6-K&owner=include&count=40`));
      if (ev.market === 'IL' || p.country === 'IL') filings.append(row('globe', 'דיווחים במאי"ה', 'חיפוש דיווחי החברה במערכת מאי"ה', g(`site:maya.tase.co.il ${p.name ? p.name.split('·')[0].trim() : ev.ticker} דוח רבעוני`)));

      const src = h('p', { class: 'src' }, 'מקורות: ', (ev.sources || []).map((s, i) => [i ? ' · ' : '', h('a', { href: s.url, target: '_blank', rel: 'noopener' }, s.label)]));
      return [
        live,
        h('details', { class: 'sub' }, h('summary', null, 'הקלטה, תמלולים והדוח'), h('div', { class: 'sub-body' }, after,
          h('p', { class: 'muted' }, 'אנחנו מקשרים לתמלולים ולדוחות במקור ולא משכפלים אותם כאן.'))),
        h('details', { class: 'sub' }, h('summary', null, 'דיווחים רשמיים'), h('div', { class: 'sub-body' }, filings)),
        src
      ];
    }
  });
})();
