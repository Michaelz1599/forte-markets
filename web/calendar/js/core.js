/* ============================================================
   LAYER: core — namespace, helpers, time zones, formatting,
   data store and the section registry used by feature modules.
   Feature files never touch each other; they talk through FC.
   ============================================================ */
(function () {
  'use strict';
  const FC = (window.FC = window.FC || {});

  // ---------- DOM helper
  FC.h = function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    if (attrs) for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'html') el.innerHTML = v;
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat(Infinity)) {
      if (kid == null || kid === false) continue;
      el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return el;
  };

  // ---------- icons (inline SVG, stroke = currentColor)
  const P = {
    chev: '<path d="M15 6l-6 6 6 6"/>',
    left: '<path d="M15 6l-6 6 6 6"/>',
    right: '<path d="M9 6l6 6-6 6"/>',
    close: '<path d="M6 6l12 12M18 6L6 18"/>',
    cal: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    dl: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
    mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0014 0M12 18v3"/>',
    play: '<circle cx="12" cy="12" r="9"/><path d="M10 8l6 4-6 4z"/>',
    doc: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 12h6M9 16h6"/>',
    text: '<path d="M4 6h16M4 10h16M4 14h10M4 18h7"/>',
    link: '<path d="M10 14a4 4 0 006 0l3-3a4 4 0 00-6-6l-1 1"/><path d="M14 10a4 4 0 00-6 0l-3 3a4 4 0 006 6l1-1"/>',
    globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 010 18M12 3a14 14 0 000 18"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5L19 19M5 19l1.5-1.5M17.5 6.5L19 5"/>',
    moon: '<path d="M20 14A8 8 0 0110 4a8 8 0 1010 10z"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 00-1-1H5a1 1 0 00-1 1v10a1 1 0 001 1h3"/>',
    half: '<circle cx="12" cy="12" r="9"/><path d="M12 3v18" /><path d="M12 3a9 9 0 010 18z" fill="currentColor"/>'
  };
  FC.icon = (n, cls) => {
    const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    s.setAttribute('width', '16'); s.setAttribute('height', '16'); if (cls) s.setAttribute('class', cls);
    s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('fill', 'none'); s.setAttribute('stroke', 'currentColor');
    s.setAttribute('stroke-width', '1.8'); s.setAttribute('stroke-linecap', 'round'); s.setAttribute('stroke-linejoin', 'round');
    s.setAttribute('aria-hidden', 'true'); s.innerHTML = P[n] || ''; return s;
  };

  // ---------- storage (per-viewer convenience only)
  FC.pref = {
    get(k, d) { try { const v = localStorage.getItem('fc.' + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem('fc.' + k, JSON.stringify(v)); } catch (e) { /* ignore */ } }
  };

  // ---------- time zones
  const NY = 'America/New_York', IL = 'Asia/Jerusalem';
  FC.TZ = { NY, IL };
  function tzOffsetMs(utcMs, tz) {
    const f = new Intl.DateTimeFormat('en-US', { timeZone: tz, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const p = Object.fromEntries(f.formatToParts(new Date(utcMs)).map((x) => [x.type, x.value]));
    return Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute, +p.second) - utcMs;
  }
  /** wall-clock date+time in tz -> UTC ms */
  FC.toUtc = function (dateISO, hhmm, tz) {
    const [y, m, d] = dateISO.split('-').map(Number);
    const [hh, mm] = (hhmm || '00:00').split(':').map(Number);
    const guess = Date.UTC(y, m - 1, d, hh, mm);
    const o1 = tzOffsetMs(guess, tz);
    const o2 = tzOffsetMs(guess - o1, tz);
    return guess - o2;
  };
  FC.fmtTime = (ms, tz) => new Intl.DateTimeFormat('he-IL', { timeZone: tz, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(ms));
  FC.fmtDate = (ms, tz, opts) => new Intl.DateTimeFormat('he-IL', Object.assign({ timeZone: tz, day: 'numeric', month: 'numeric' }, opts || {})).format(new Date(ms));
  FC.dayKey = (ms, tz) => {
    const p = Object.fromEntries(new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date(ms)).map((x) => [x.type, x.value]));
    return `${p.year}-${p.month}-${p.day}`;
  };
  /** hours between ET and Israel on a given date (6 or 7 in Oct/Nov transition weeks) */
  FC.gapHours = (dateISO) => Math.round((tzOffsetMs(FC.toUtc(dateISO, '12:00', NY), IL) - tzOffsetMs(FC.toUtc(dateISO, '12:00', NY), NY)) / 3600000);

  /** Describe a clock time for display in the viewer's chosen zone; returns {main, alt, ms, nextDay} */
  FC.describe = function (dateISO, hhmm, tz, viewTz) {
    const ms = FC.toUtc(dateISO, hhmm, tz);
    const other = viewTz === IL ? NY : IL;
    const dk = FC.dayKey(ms, viewTz);
    return {
      ms,
      main: FC.fmtTime(ms, viewTz),
      alt: FC.fmtTime(ms, other) + (other === NY ? ' ET' : ' שעון ישראל'),
      dayShift: dk !== dateISO ? FC.fmtDate(ms, viewTz, { weekday: 'short', day: 'numeric', month: 'numeric' }) : null
    };
  };

  // ---------- dates (calendar math in plain ISO dates)
  FC.iso = (d) => d.toISOString().slice(0, 10);
  FC.addDays = (iso, n) => { const d = new Date(iso + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return FC.iso(d); };
  FC.mondayOf = (iso) => { const d = new Date(iso + 'T12:00:00Z'); const wd = (d.getUTCDay() + 6) % 7; return FC.addDays(iso, -wd); };
  FC.HE_DAYS = ['ראשון', 'שני', 'שלישי', 'רביעי', 'חמישי', 'שישי', 'שבת'];
  FC.HE_MONTHS = ['ינואר', 'פברואר', 'מרץ', 'אפריל', 'מאי', 'יוני', 'יולי', 'אוגוסט', 'ספטמבר', 'אוקטובר', 'נובמבר', 'דצמבר'];
  FC.dayName = (iso) => FC.HE_DAYS[new Date(iso + 'T12:00:00Z').getUTCDay()];
  FC.shortDate = (iso) => { const [, m, d] = iso.split('-'); return `${+d}.${+m}`; };
  FC.longDate = (iso) => { const [y, m, d] = iso.split('-').map(Number); return `יום ${FC.dayName(iso)}, ${d} ב${FC.HE_MONTHS[m - 1]} ${y}`; };
  FC.todayIL = () => FC.dayKey(Date.now(), IL);

  // ---------- number formatting
  FC.money = (v) => {
    if (v == null || isNaN(v)) return '—';
    const a = Math.abs(v), s = v < 0 ? '−' : '';
    if (a >= 1e12) return `${s}$${(a / 1e12).toFixed(2)}T`;
    if (a >= 1e9) return `${s}$${(a / 1e9).toFixed(a >= 1e11 ? 0 : 1)}B`;
    if (a >= 1e6) return `${s}$${(a / 1e6).toFixed(0)}M`;
    return `${s}$${a.toFixed(2)}`;
  };
  FC.x = (v, d = 1) => (v == null || isNaN(v) ? '—' : `${v.toFixed(d)}x`);
  FC.n = (v, d = 2) => (v == null || isNaN(v) ? '—' : (v < 0 ? '−' : '') + Math.abs(v).toFixed(d));
  FC.pct = (v, d = 1) => (v == null || isNaN(v) ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(d)}%`);
  FC.usd = (v) => (v == null || isNaN(v) ? '—' : (v < 0 ? '−$' : '$') + Math.abs(v).toFixed(2));

  // ---------- section registry (company panel categories)
  const sections = [];
  FC.sections = {
    /** register({id, order, title, summary(ctx)->string, render(ctx)->Node}) */
    register(def) { sections.push(def); sections.sort((a, b) => a.order - b.order); },
    all() { return sections.slice(); }
  };

  // ---------- tiny event bus
  const bus = {};
  FC.on = (ev, fn) => (bus[ev] = bus[ev] || []).push(fn);
  FC.emit = (ev, data) => (bus[ev] || []).forEach((fn) => { try { fn(data); } catch (e) { console.error(e); } });

  // ---------- data store
  async function getJSON(path) {
    const r = await fetch(path, { cache: 'no-cache' });
    if (!r.ok) throw new Error(path + ' ' + r.status);
    return r.json();
  }
  FC.getJSON = getJSON;

  FC.store = {
    manifest: null, events: [], byTicker: {}, profiles: {}, market: {}, voices: {}, logos: {}, weeks: [],
    async load() {
      const m = (this.manifest = await getJSON('data/manifest.json'));
      const [weeks, prof, mk, voices, logos] = await Promise.all([
        Promise.all(m.weeks.map((w) => getJSON(w.file).catch(() => ({ events: [] })))),
        getJSON(m.profiles).catch(() => ({ companies: {} })),
        getJSON(m.market).catch(() => ({ quotes: {} })),
        getJSON(m.voices).catch(() => ({ items: {} })),
        getJSON(m.logos).catch(() => ({ logos: {} }))
      ]);
      this.weeks = m.weeks;
      this.profiles = prof.companies || {};
      this.market = mk.quotes || {};
      this.marketAsOf = mk.asof;
      this.voices = voices.items || {};
      this.logos = logos.logos || {};
      this.events = weeks.flatMap((w) => w.events || []);
      this.byTicker = {};
      for (const e of this.events) (this.byTicker[e.ticker] = this.byTicker[e.ticker] || []).push(e);
      return this;
    },
    eventById(id) { return this.events.find((e) => e.id === id); },
    ctx(ev) {
      const t = ev.ticker;
      return { t, ev, profile: this.profiles[t] || { name: t, tags: [] }, quote: this.market[t] || {}, voices: this.voices[t] || [], others: (this.byTicker[t] || []).filter((x) => x.id !== ev.id) };
    },
    /** release/call times resolved to UTC + labels for a viewer zone */
    timing(ev, viewTz) {
      const out = { release: null, call: null, slotHint: null };
      const gap = FC.gapHours(ev.date);
      if (ev.release && ev.release.time) out.release = FC.describe(ev.date, ev.release.time, ev.release.tz || NY, viewTz);
      if (ev.call && ev.call.time) out.call = FC.describe(ev.date, ev.call.time, ev.call.tz || NY, viewTz);
      const open = FC.describe(ev.date, '09:30', NY, viewTz), close = FC.describe(ev.date, '16:00', NY, viewTz);
      out.gap = gap;
      if (ev.market === 'US') {
        if (ev.session === 'BMO') out.slotHint = `לפני פתיחת המסחר בניו יורק (${open.main}${viewTz === IL ? ' שעון ישראל' : ' ET'})`;
        else if (ev.session === 'AMC') out.slotHint = `אחרי סגירת המסחר בניו יורק (${close.main}${viewTz === IL ? ' שעון ישראל' : ' ET'})`;
      } else {
        out.slotHint = ev.session === 'BMO' ? 'לפני פתיחת המסחר' : ev.session === 'AMC' ? 'אחרי סגירת המסחר' : 'שעת פרסום לא צוינה';
      }
      return out;
    }
  };

  FC.TAG_HE = { SPX: 'S&P 500', NDX: 'נאסד"ק 100', GLOBAL: 'גלובלי', TA125: 'ת"א 125', TASE: 'ת"א כל המניות' };
  FC.SESSION_HE = { BMO: 'לפני פתיחה', AMC: 'אחרי סגירה', DMT: 'במהלך המסחר', TBD: 'שעה לא ידועה' };
})();
