/* ============================================================
   LAYER: calendar export (Outlook)
   - outlookLink(ev): opens a prefilled Outlook event (works for anyone)
   - export dialog: builds an .ics for the shown month/week and saves it
     inside a .zip (the viewer's save allowlist has no .ics), with a
     copy-to-clipboard fallback.
   ============================================================ */
(function () {
  'use strict';
  const FC = window.FC, h = FC.h;

  function timesOf(ev) {
    if (ev.kind === 'macro') { if (ev.time) { const s = FC.toUtc(ev.date, ev.time, ev.tz); return { start: s, end: s + 30 * 60000 }; } return { allDay: true }; }
    if (ev.call && ev.call.time) { const s = FC.toUtc(ev.date, ev.call.time, ev.call.tz || FC.TZ.NY); return { start: s, end: s + 60 * 60000, kind: 'call' }; }
    if (ev.release && ev.release.time) { const s = FC.toUtc(ev.date, ev.release.time, ev.release.tz || FC.TZ.NY); return { start: s, end: s + 30 * 60000, kind: 'release' }; }
    return { allDay: true };
  }
  function titleOf(ev) {
    if (ev.kind === 'macro') return `${ev.country === 'IL' ? 'ישראל' : 'ארה"ב'} · ${ev.he}${ev.period ? ' · ' + ev.period : ''}`;
    const p = FC.store.profiles[ev.ticker] || {};
    const nm = (p.name || '').split('·')[0].trim();
    return `${ev.ticker} · דוח ${ev.period || 'רבעוני'}${nm ? ' · ' + nm : ''}`;
  }
  function bodyOf(ev) {
    if (ev.kind === 'macro') return [ev.why, ev.prev ? 'קודם: ' + ev.prev : null, ev.fcst ? 'צפי: ' + ev.fcst : null, ev.src && ev.src.url ? 'מקור: ' + ev.src.url : null, 'יומן הדוחות של פורטה · מאקרו'].filter(Boolean).join('\n');
    const st = FC.state, tm = FC.store.timing(ev, FC.TZ.IL), lines = [];
    lines.push(`פרסום: ${FC.longDate(ev.date)} · ${tm.release ? tm.release.main + ' שעון ישראל (' + tm.release.alt + ')' : (FC.SESSION_HE[ev.session] || '')}`);
    if (tm.call) lines.push(`שיחת ועידה: ${tm.call.main} שעון ישראל (${tm.call.alt})${ev.call.confirmed ? '' : ' — טרם אושר'}`);
    if (ev.call && ev.call.webcast) lines.push(`שידור: ${ev.call.webcast}`);
    const k = ev.consensus;
    if (k) lines.push(`קונצנזוס: EPS ${FC.usd(k.eps)} · הכנסות ${FC.money(k.rev)}`);
    lines.push(ev.status === 'confirmed' ? 'מאומת מול הודעת החברה' : 'לפי לוח הדוחות — טרם אומת');
    lines.push('יומן הדוחות של פורטה');
    return lines.join('\n');
  }

  // ---------- Outlook deep link
  function outlookLink(ev) {
    const t = timesOf(ev);
    const u = new URL('https://outlook.office.com/calendar/0/deeplink/compose');
    u.searchParams.set('path', '/calendar/action/compose');
    u.searchParams.set('rru', 'addevent');
    u.searchParams.set('subject', titleOf(ev));
    u.searchParams.set('body', bodyOf(ev));
    if (ev.call && ev.call.webcast) u.searchParams.set('location', ev.call.webcast);
    if (ev.kind === 'macro' && ev.src && ev.src.url) u.searchParams.set('location', ev.src.url);
    if (t.allDay) { u.searchParams.set('allday', 'true'); u.searchParams.set('startdt', ev.date); u.searchParams.set('enddt', FC.addDays(ev.date, 1)); }
    else { u.searchParams.set('startdt', new Date(t.start).toISOString()); u.searchParams.set('enddt', new Date(t.end).toISOString()); }
    return u.toString();
  }

  // ---------- ICS
  const enc = new TextEncoder();
  const esc = (s) => String(s).replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\r?\n/g, '\\n');
  const utc = (ms) => new Date(ms).toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '');
  function fold(line) {
    const out = []; let cur = '', bytes = 0;
    for (const ch of line) {
      const b = enc.encode(ch).length;
      if (bytes + b > (out.length ? 74 : 75)) { out.push(cur); cur = ''; bytes = 0; }
      cur += ch; bytes += b;
    }
    out.push(cur);
    return out.join('\r\n ');
  }
  function buildIcs(events, calName) {
    const L = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Forte Investment House//Earnings Calendar//HE', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH', 'X-WR-CALNAME:' + esc(calName), 'X-WR-TIMEZONE:Asia/Jerusalem'];
    const stamp = utc(Date.now());
    for (const ev of events) {
      const t = timesOf(ev);
      L.push('BEGIN:VEVENT', `UID:${ev.id}@forte-earnings`, `DTSTAMP:${stamp}`);
      if (t.allDay) { L.push(`DTSTART;VALUE=DATE:${ev.date.replace(/-/g, '')}`, `DTEND;VALUE=DATE:${FC.addDays(ev.date, 1).replace(/-/g, '')}`, 'TRANSP:TRANSPARENT'); }
      else { L.push(`DTSTART:${utc(t.start)}`, `DTEND:${utc(t.end)}`); }
      L.push('SUMMARY:' + esc(titleOf(ev)), 'DESCRIPTION:' + esc(bodyOf(ev)));
      if (ev.call && ev.call.webcast) L.push('LOCATION:' + esc(ev.call.webcast), 'URL:' + ev.call.webcast);
      L.push('CATEGORIES:' + esc('דוחות כספיים'), 'END:VEVENT');
    }
    L.push('END:VCALENDAR');
    return L.map(fold).join('\r\n') + '\r\n';
  }

  // ---------- minimal ZIP (store, no compression)
  const CRC = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
  const crc32 = (u8) => { let c = 0xFFFFFFFF; for (let i = 0; i < u8.length; i++) c = CRC[(c ^ u8[i]) & 0xFF] ^ (c >>> 8); return (c ^ 0xFFFFFFFF) >>> 0; };
  function zip(name, data) {
    const nm = enc.encode(name), crc = crc32(data), size = data.length;
    const d = new Date(), dt = ((d.getHours() << 11) | (d.getMinutes() << 5) | (d.getSeconds() >> 1)) & 0xFFFF, dd = (((d.getFullYear() - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate()) & 0xFFFF;
    const lh = new DataView(new ArrayBuffer(30));
    [[0, 0x04034b50, 4], [4, 20, 2], [6, 0x0800, 2], [8, 0, 2], [10, dt, 2], [12, dd, 2], [14, crc, 4], [18, size, 4], [22, size, 4], [26, nm.length, 2], [28, 0, 2]].forEach(([o, v, n]) => (n === 4 ? lh.setUint32(o, v, true) : lh.setUint16(o, v, true)));
    const ch = new DataView(new ArrayBuffer(46));
    [[0, 0x02014b50, 4], [4, 20, 2], [6, 20, 2], [8, 0x0800, 2], [10, 0, 2], [12, dt, 2], [14, dd, 2], [16, crc, 4], [20, size, 4], [24, size, 4], [28, nm.length, 2], [30, 0, 2], [32, 0, 2], [34, 0, 2], [36, 0, 2], [38, 0, 4], [42, 0, 4]].forEach(([o, v, n]) => (n === 4 ? ch.setUint32(o, v, true) : ch.setUint16(o, v, true)));
    const cdOffset = 30 + nm.length + size, cdSize = 46 + nm.length;
    const end = new DataView(new ArrayBuffer(22));
    [[0, 0x06054b50, 4], [4, 0, 2], [6, 0, 2], [8, 1, 2], [10, 1, 2], [12, cdSize, 4], [16, cdOffset, 4], [20, 0, 2]].forEach(([o, v, n]) => (n === 4 ? end.setUint32(o, v, true) : end.setUint16(o, v, true)));
    const out = new Uint8Array(cdOffset + cdSize + 22); let p = 0;
    for (const part of [new Uint8Array(lh.buffer), nm, data, new Uint8Array(ch.buffer), nm, new Uint8Array(end.buffer)]) { out.set(part, p); p += part.length; }
    return out;
  }

  // ---------- downloads capability (viewer-provided)
  let dlPromise = null;
  function downloads() {
    if (!dlPromise) dlPromise = (window.claude && typeof window.claude.use === 'function') ? window.claude.use('downloads').catch(() => null)
      : Promise.resolve({ direct: true, save({ filename, data }) { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([data], { type: /\.ics$/.test(filename) ? 'text/calendar' : 'application/zip' })); a.download = filename; document.body.append(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1500); return Promise.resolve(); } });
    return dlPromise;
  }
  downloads();

  // ---------- dialog
  function openDialog() {
    const st = FC.state;
    let scope = st.view === 'week' ? 'week' : 'month';
    let onlyFiltered = true;
    const monthOf = st.view === 'month' ? st.month : st.week.slice(0, 7);
    const status = h('div', { class: 'status', role: 'status' });
    const countEl = h('b');
    const pick = () => {
      const base = st.market === 'MACRO' && FC.macro ? (onlyFiltered ? FC.macro.filtered() : FC.macro.all()) : onlyFiltered ? FC.filtered() : FC.store.events;
      if (scope === 'week') { const end = FC.addDays(st.week, 4); return base.filter((e) => e.date >= st.week && e.date <= end); }
      return base.filter((e) => e.date.slice(0, 7) === monthOf);
    };
    const refresh = () => { const n = pick().length; countEl.textContent = n; saveBtn.disabled = !n; copyBtn.disabled = !n; };
    const seg = (opts, get, set) => h('div', { class: 'radio' }, opts.map(([v, l]) => {
      const b = h('button', { class: 'chip', type: 'button', 'aria-pressed': String(get() === v), onclick: () => { set(v); b.parentNode.querySelectorAll('.chip').forEach((x) => x.setAttribute('aria-pressed', 'false')); b.setAttribute('aria-pressed', 'true'); refresh(); } }, l);
      return b;
    }));
    const [y, m] = monthOf.split('-').map(Number);
    const monthLabel = `${FC.HE_MONTHS[m - 1]} ${y}`;
    const fname = () => scope === 'week' ? `forte-earnings-week-${st.week}` : `forte-earnings-${monthOf}`;
    const saveBtn = h('button', { class: 'btn btn-primary', type: 'button', onclick: async () => {
      const evs = pick();
      const ics = buildIcs(evs, `פורטה · דוחות ${scope === 'week' ? 'שבוע ' + FC.shortDate(st.week) : monthLabel}`);
      const dl = await downloads();
      if (!dl) { status.className = 'status err'; status.textContent = 'שמירת קבצים לא זמינה בתצוגה הזו. השתמשו בכפתור ההעתקה למטה.'; showText(ics); return; }
      try {
        if (dl.direct) await dl.save({ filename: fname() + '.ics', data: enc.encode(ics) });
        else await dl.save({ filename: fname() + '.zip', data: zip(fname() + '.ics', enc.encode(ics)) });
        status.className = 'status'; status.textContent = dl.direct ? `נשמר קובץ ‎.ics‎ עם ${evs.length} אירועים. לחיצה כפולה עליו מייבאת לאאוטלוק.` : `נשמר קובץ ZIP עם ${evs.length} אירועים. פתחו אותו ולחצו פעמיים על הקובץ ‎.ics‎ כדי לייבא לאאוטלוק.`;
      } catch (e) {
        status.className = 'status err';
        status.textContent = e && e.code === 'declined' ? 'השמירה בוטלה.' : 'השמירה לא הצליחה בתצוגה הזו. אפשר להעתיק את תוכן הקובץ.';
        if (!(e && e.code === 'declined')) showText(ics);
      }
    } }, FC.icon('dl'), 'שמירת קובץ ליומן');
    const ta = h('textarea', { class: 'ics', readonly: true, hidden: true, 'aria-label': 'תוכן קובץ ICS' });
    function showText(ics) { ta.value = ics; ta.hidden = false; }
    const copyBtn = h('button', { class: 'btn', type: 'button', onclick: async () => {
      const ics = buildIcs(pick(), `פורטה · דוחות ${monthLabel}`); showText(ics);
      try { await navigator.clipboard.writeText(ics); status.className = 'status'; status.textContent = 'הועתק. הדביקו לקובץ טקסט ושמרו אותו בסיומת ‎.ics‎.'; }
      catch (e) { ta.focus(); ta.select(); status.className = 'status'; status.textContent = 'סמנו את הטקסט והעתיקו ידנית (Ctrl+C).'; }
    } }, FC.icon('copy'), 'העתקת תוכן ICS');
    const card = h('div', { class: 'modal-card', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'ייצוא לאאוטלוק' },
      h('div', { class: 'modal-head' }, h('span', null, 'ייצוא ליומן Outlook'), h('button', { class: 'd-close', type: 'button', 'aria-label': 'סגירה', onclick: close }, FC.icon('close'))),
      h('div', { class: 'modal-body' },
        h('div', { class: 'field' }, h('span', null, 'טווח'), seg([['month', 'כל ' + monthLabel], ['week', 'השבוע המוצג']], () => scope, (v) => (scope = v))),
        h('div', { class: 'field' }, h('span', null, 'אילו חברות'), seg([[true, 'לפי המסננים הנוכחיים'], [false, 'כל החברות']], () => onlyFiltered, (v) => (onlyFiltered = v))),
        h('p', { class: 'muted' }, 'ייווצרו ', countEl, ' אירועים. אירוע נקבע לשעת שיחת הוועידה כשהיא ידועה; אחרת לשעת הפרסום; אחרת כאירוע של יום שלם. החודש כולל רק שבועות שכבר נטענו.'),
        h('div', { class: 'when-actions' }, saveBtn, copyBtn),
        status, ta,
        h('p', { class: 'src' }, 'הקובץ נשמר בתוך ZIP כי התצוגה לא מאפשרת לשמור ‎.ics‎ ישירות. לאירוע בודד אפשר להשתמש בכפתור "הוספה ל-Outlook" בכרטיס החברה.')));
    status.hidden = false; status.textContent = 'בחרו טווח ושמרו.';
    const wrap = h('div', { class: 'modal' }, h('div', { class: 'scrim', onclick: close }), card);
    document.body.append(wrap);
    refresh();
    saveBtn.focus();
    function close() { wrap.remove(); FC.closeModal = null; }
    FC.closeModal = close;
  }

  FC.ics = { outlookLink, buildIcs, zip, openDialog };
})();
