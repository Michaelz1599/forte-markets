/* ============================================================
   LAYER: week view
   1) "מפת הדוחות" — treemap: day regions sized by reported market cap,
      company tiles sized by market cap (inspired by QuarterChart's map).
   2) "שווי השוק המדווח בכל שבוע" — stacked bars per loaded week.
   3) Day tables — company, market cap, EPS/revenue estimates, timing, call, status.
   ============================================================ */
(function () {
  'use strict';
  const FC = window.FC, h = FC.h;
  const expanded = new Set();
  let ro = null;

  const mcapOf = (e) => (FC.store.market[e.ticker] || {}).mcap || 0;
  const shortName = (p) => (p.name || '').split('·')[0].replace(/\s*\(.*?\)\s*/g, ' ').replace(/,? Inc\.?$|,? Corporation$|,? Corp\.?$| plc$| N\.V\.$| S\.A\.$| Company$/g, '').replace(/Company \(The\)/, '').trim();
  FC.dayIndex = (iso) => (new Date(iso + 'T12:00:00Z').getUTCDay() + 6) % 7; // Mon=0

  // ---------- squarified treemap (Bruls et al.)
  function squarify(items, x, y, w, hgt) {
    const out = [];
    const total = items.reduce((s, i) => s + i.v, 0);
    if (!total || w <= 0 || hgt <= 0) return out;
    const k = (w * hgt) / total;
    let rest = items.map((i) => ({ i, a: i.v * k }));
    const worst = (row, s) => {
      const sum = row.reduce((t, r) => t + r.a, 0);
      const mx = Math.max(...row.map((r) => r.a)), mn = Math.min(...row.map((r) => r.a));
      return Math.max((s * s * mx) / (sum * sum), (sum * sum) / (s * s * mn));
    };
    while (rest.length) {
      const s = Math.min(w, hgt);
      let row = [rest[0]], n = 1;
      while (n < rest.length && worst(row.concat(rest[n]), s) <= worst(row, s)) { row = row.concat(rest[n]); n++; }
      const sum = row.reduce((t, r) => t + r.a, 0), thick = sum / s;
      if (w >= hgt) { let yy = y; for (const r of row) { const hh = r.a / thick; out.push({ ...r.i, x, y: yy, w: thick, h: hh }); yy += hh; } x += thick; w -= thick; }
      else { let xx = x; for (const r of row) { const ww = r.a / thick; out.push({ ...r.i, x: xx, y, w: ww, h: thick }); xx += ww; } y += thick; hgt -= thick; }
      rest = rest.slice(row.length);
    }
    return out;
  }

  // ---------- one tile
  function tile(cell, st, dayIdx) {
    const { w, h: ht } = cell;
    if (cell.more) {
      return h('button', { class: `tm-tile d${dayIdx} more-tile`, type: 'button', style: pos(cell), 'aria-label': `עוד ${cell.more} חברות ב${FC.dayName(cell.day)}`,
        onclick: () => { expanded.add(cell.day); const el = document.getElementById('tbl-' + cell.day); if (el) { FC.render(); document.getElementById('tbl-' + cell.day).scrollIntoView({ behavior: 'smooth', block: 'start' }); } } },
        h('span', { class: 'tm-more' }, `+${cell.more}`), w > 70 && ht > 44 ? h('span', { class: 'tm-sub' }, 'חברות נוספות') : null);
    }
    const ev = cell.ev, p = FC.store.profiles[ev.ticker] || {};
    const tm = FC.store.timing(ev, st.tz);
    const len = ev.ticker.length;
    let fs = Math.min((w - 8) * 0.9 / (len * 0.72), ht * 0.36, 76);
    fs = Math.max(fs, 8);
    const showName = w > 92 && ht > 70;
    const showMeta = w > 120 && ht > 104;
    const nameFs = Math.max(10, Math.min(15, fs * 0.32));
    const contentH = fs * 0.95 + (showName ? nameFs * 1.2 + 2 : 0) + (showMeta ? 16 : 0);
    const roomForBadge = (ht - contentH) / 2 >= 22 && w >= 40;
    const badge = ev.session === 'BMO' ? 'BMO' : ev.session === 'AMC' ? 'AMC' : '';
    const k = ev.consensus;
    const logo = FC.store.logos[ev.ticker];
    return h('button', {
      class: `tm-tile d${dayIdx}` + (ev.status === 'confirmed' ? ' ok' : '') + (st.openId === ev.id ? ' on' : ''), type: 'button', style: pos(cell), 'data-ev': ev.id,
      title: `${p.name || ev.ticker} · ${FC.SESSION_HE[ev.session] || ''}${tm.call ? ' · שיחה ' + tm.call.main : ''}`,
      'aria-label': `${ev.ticker} ${shortName(p)}, ${FC.SESSION_HE[ev.session] || ''}${tm.call ? ', שיחת ועידה ' + tm.call.main : ''}`,
      onclick: () => FC.panel.open(ev.id)
    },
      badge && roomForBadge ? h('span', { class: 'tm-badge' + (fs < 20 ? ' xs' : '') }, badge) : null,
      ev.status === 'confirmed' && roomForBadge && w > 60 ? h('span', { class: 'tm-ok', title: 'מאומת מול הודעת החברה' }) : null,
      h('span', { class: 'tm-body' },
        logo && showName ? h('img', { class: 'tm-logo', src: logo, alt: '' }) : null,
        showName ? h('span', { class: 'tm-name', style: `font-size:${nameFs}px` }, shortName(p)) : null,
        h('span', { class: 'tm-tk', style: `font-size:${fs}px` }, ev.ticker),
        showMeta ? h('span', { class: 'tm-meta' }, [tm.call ? 'שיחה ' + tm.call.main : null, k && k.eps != null && (w >= 200 || !tm.call) ? 'EPS ' + FC.usd(k.eps) : null].filter(Boolean).join(' · ')) : null)
    );
  }
  const pos = (c) => `left:${c.x.toFixed(1)}px;top:${c.y.toFixed(1)}px;width:${Math.max(0, c.w - 3).toFixed(1)}px;height:${Math.max(0, c.h - 3).toFixed(1)}px`;

  // ---------- map
  function buildMap(holder, days, byDay, st) {
    const W = holder.clientWidth;
    if (!W) return;
    holder.textContent = '';
    const mobile = W < 640;
    const HEAD = 34;
    const tot = days.map((d) => byDay[d].reduce((s, e) => s + Math.max(mcapOf(e), 2e9), 0));
    const grand = tot.reduce((a, b) => a + b, 0) || 1;
    const regions = [];
    if (mobile) {
      let y = 0;
      days.forEach((d, i) => {
        const share = tot[i] / grand;
        const hh = byDay[d].length ? Math.round(Math.max(170, Math.min(520, 900 * share + 140))) : 64;
        regions.push({ d, i, x: 0, y, w: W, h: hh }); y += hh + 6;
      });
      holder.style.height = (regions.length ? regions[regions.length - 1].y + regions[regions.length - 1].h : 0) + 'px';
    } else {
      const nEv = days.reduce((a, d) => a + byDay[d].length, 0);
      const H = Math.min(W > 1100 ? 640 : 540, 280 + nEv * 30);
      holder.style.height = H + 'px';
      // columns: a small day shares a column with its neighbour (stacked), like a calendar column pair
      const share = tot.map((t) => t / grand);
      const cols = [];
      for (let i = 0; i < days.length; i++) {
        const last = cols[cols.length - 1];
        const small = share[i] < 0.09;
        if (small && last && last.days.length === 1 && share[last.days[0]] < 0.22) { last.days.push(i); continue; }
        if (small && !last && i + 1 < days.length && share[i + 1] < 0.22) { cols.push({ days: [i, i + 1] }); i++; continue; }
        cols.push({ days: [i] });
      }
      const cw = cols.map((c) => Math.max(0.12, c.days.reduce((s, i) => s + share[i], 0)));
      const cwSum = cw.reduce((a, b) => a + b, 0);
      let x = W; // RTL: first day on the right
      cols.forEach((c, ci) => {
        const ww = (cw[ci] / cwSum) * W;
        x -= ww;
        const sub = c.days.map((i) => Math.max(0.22, share[i] || 0));
        const subSum = sub.reduce((a, b) => a + b, 0);
        let y = 0;
        c.days.forEach((i, k) => {
          const hh = c.days.length === 1 ? H : (sub[k] / subSum) * H;
          regions.push({ d: days[i], i, x, y, w: ww, h: hh }); y += hh;
        });
      });
    }
    for (const r of regions) {
      const evs = byDay[r.d].slice().sort((a, b) => mcapOf(b) - mcapOf(a));
      const reg = h('div', { class: `tm-day d${r.i}`, style: `left:${r.x}px;top:${r.y}px;width:${r.w - 4}px;height:${r.h - 4}px` });
      const capTxt = evs.length ? (r.w > 230 ? `${evs.length} דוחות · ${FC.money(tot[r.i])}` : `${evs.length}`) : '';
      reg.append(h('div', { class: 'tm-head' }, h('span', { class: 'tm-dname' }, `${FC.dayName(r.d)} ${FC.shortDate(r.d)}`), h('span', { class: 'tm-dcap' }, capTxt)));
      const iw = r.w - 4 - 6, ih = r.h - 4 - HEAD - 4;
      const area = h('div', { class: 'tm-area', style: `height:${Math.max(0, ih)}px` });
      if (!evs.length) area.append(h('div', { class: 'tm-empty' }, 'אין דוחות'));
      else {
        // keep tiles readable: everything below the minimum area folds into "+N"
        const MIN = mobile ? 2200 : 2400;
        const total = evs.reduce((s, e) => s + Math.max(mcapOf(e), 2e9), 0);
        const scale = (iw * ih) / total;
        const keep = [], rest = [];
        evs.forEach((e, idx) => {
          const v = Math.max(mcapOf(e), 2e9);
          (v * scale >= MIN && keep.length < 28) || idx === 0 ? keep.push(e) : rest.push(e);
        });
        const items = keep.map((e) => ({ v: Math.max(mcapOf(e), 2e9), ev: e }));
        // the "+N" tile stays small: about the size of the smallest visible company tile
        const smallest = items.length ? items[items.length - 1].v : MIN / scale;
        if (rest.length) items.push({ v: Math.max(smallest * 1.1, (MIN * 1.4) / scale), more: rest.length, day: r.d });
        items.sort((a, b) => b.v - a.v);
        const cells = squarify(items, 0, 0, iw, ih).map((c) => ({ ...c, x: iw - c.x - c.w })); // mirror for RTL
        for (const c of cells) area.append(tile(c, st, r.i));
      }
      reg.append(area);
      holder.append(reg);
    }
  }

  // ---------- weekly market-cap chart (SVG)
  function capChart(st) {
    const weeks = FC.store.weeks;
    const filtered = FC.filtered();
    const data = weeks.map((w) => {
      const days = [0, 1, 2, 3, 4].map((i) => FC.addDays(w.id, i));
      const per = days.map((d) => filtered.filter((e) => e.date === d).reduce((s, e) => s + mcapOf(e), 0));
      return { w, per, total: per.reduce((a, b) => a + b, 0) };
    });
    const max = Math.max(...data.map((d) => d.total), 1);
    const nice = [1e12, 2e12, 5e12, 10e12, 20e12, 40e12, 60e12].find((v) => v >= max) || max;
    const VW = 720, VH = 230, L = 52, R = 12, T = 26, B = 40;
    const bw = Math.min(64, (VW - L - R) / data.length * 0.5);
    const step = (VW - L - R) / data.length;
    const y = (v) => T + (VH - T - B) * (1 - v / nice);
    const svg = [`<svg viewBox="0 0 ${VW} ${VH}" class="cap-svg" role="img" aria-label="שווי השוק של החברות המדווחות בכל שבוע">`];
    for (let g = 0; g <= 4; g++) {
      const v = (nice / 4) * g, yy = y(v);
      svg.push(`<line x1="${L}" x2="${VW - R}" y1="${yy}" y2="${yy}" class="cap-grid"/>`, `<text x="${L - 8}" y="${yy + 4}" class="cap-ax" text-anchor="end">${FC.money(v).replace('.00', '')}</text>`);
    }
    data.forEach((d, i) => {
      // RTL: earliest week on the right
      const cx = VW - R - step * i - step / 2;
      if (d.w.id === st.week) svg.push(`<rect x="${cx - step / 2 + 4}" y="${T - 22}" width="${step - 8}" height="${VH - T - B + 22}" class="cap-hl" rx="6"/>`, `<text x="${cx}" y="${T - 8}" class="cap-this" text-anchor="middle">השבוע המוצג</text>`);
      let acc = 0;
      d.per.forEach((v, di) => {
        if (!v) return;
        const y0 = y(acc), y1 = y(acc + v);
        svg.push(`<rect x="${cx - bw / 2}" y="${y1}" width="${bw}" height="${Math.max(1, y0 - y1 - 1.5)}" class="cap-seg d${di}"><title>${FC.HE_DAYS[(di + 1) % 7]}: ${FC.money(v)}</title></rect>`);
        acc += v;
      });
      svg.push(`<text x="${cx}" y="${y(d.total) - 6}" class="cap-val" text-anchor="middle">${d.total ? FC.money(d.total) : '—'}</text>`);
      const partial = d.w.coverage && d.w.coverage.US !== 'full';
      svg.push(`<text x="${cx}" y="${VH - B + 18}" class="cap-ax" text-anchor="middle">${FC.shortDate(d.w.id)}–${FC.shortDate(FC.addDays(d.w.id, 4))}</text>`);
      if (partial) svg.push(`<text x="${cx}" y="${VH - B + 32}" class="cap-part" text-anchor="middle">חלקי</text>`);
    });
    svg.push('</svg>');
    const box = h('div', { class: 'cap-wrap' });
    box.innerHTML = svg.join('');
    box.querySelectorAll('rect.cap-seg').forEach((r) => r.setAttribute('tabindex', '-1'));
    return box;
  }

  // ---------- day tables
  function dayTable(d, evs, st) {
    const all = evs.slice().sort((a, b) => mcapOf(b) - mcapOf(a));
    const LIM = 10, open = expanded.has(d) || st.q;
    const rows = open ? all : all.slice(0, LIM);
    const zone = st.tz === FC.TZ.IL ? '' : ' ET';
    const tb = h('tbody', null, rows.map((e) => {
      const p = FC.store.profiles[e.ticker] || {}, k = e.consensus, tm = FC.store.timing(e, st.tz);
      return h('tr', { tabindex: '0', role: 'button', 'aria-label': `פתיחת ${e.ticker}`, onclick: () => FC.panel.open(e.id), onkeydown: (ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); FC.panel.open(e.id); } } },
        h('td', { class: 'c-co' }, FC.logo(e.ticker), h('span', null, h('b', null, shortName(p) || e.ticker), ' ', h('span', { class: 'tk' }, e.ticker))),
        h('td', { class: 'num' }, FC.money(mcapOf(e))),
        h('td', { class: 'num' }, k ? FC.usd(k.eps) : '—'),
        h('td', { class: 'num hide-md' }, k ? FC.money(k.rev) : '—'),
        h('td', { class: 'num' }, FC.moveCell ? FC.moveCell(e) : '—'),
        h('td', null, h('span', { class: 'sess s-' + e.session }, FC.SESSION_HE[e.session] || '—')),
        h('td', { class: 'num hide-sm' }, tm.call ? tm.call.main + zone : '—'),
        h('td', { class: 'hide-sm' }, e.status === 'confirmed' ? h('span', { class: 'pill' }, 'מאומת') : h('span', { class: 'st-un' }, 'לפי לוח הדוחות'))
      );
    }));
    const table = h('table', { class: 'dtable' },
      h('thead', null, h('tr', null, h('th', null, 'חברה'), h('th', { class: 'num' }, 'שווי שוק'), h('th', { class: 'num' }, 'EPS צפוי'), h('th', { class: 'num hide-md' }, 'הכנסות צפויות'), h('th', { class: 'num', title: 'לפני הדוח: התנועה שהאופציות מתמחרות (±). אחרי הדוח: התנועה בפועל ביום התגובה' }, 'תנועה'), h('th', null, 'תזמון'), h('th', { class: 'num hide-sm' }, 'שיחת ועידה'), h('th', { class: 'hide-sm' }, 'סטטוס'))),
      tb);
    const sec = h('section', { class: 'dsec', id: 'tbl-' + d },
      h('h3', { class: 'dsec-h' }, h('span', { class: `dsw d${FC.dayIndex(d)}` }), `${FC.longDate(d)}`, h('span', { class: 'dsec-c' }, all.length ? `${all.length} דוחות · ${FC.money(all.reduce((s, e) => s + mcapOf(e), 0))}` : 'אין דוחות')));
    if (all.length) {
      sec.append(h('div', { class: 'dtable-wrap' }, table));
      if (all.length > LIM && !st.q) sec.append(h('button', { class: 'more', type: 'button', onclick: () => { open ? expanded.delete(d) : expanded.add(d); FC.render(); } }, open ? 'הצג פחות' : `הצג את כל ${all.length} הדוחות`));
    }
    return sec;
  }

  FC.views = FC.views || {};
  FC.views.week = function (root, st) {
    const days = [0, 1, 2, 3, 4].map((i) => FC.addDays(st.week, i));
    const evs = FC.filtered().filter((e) => e.date >= days[0] && e.date <= days[4]);
    const byDay = Object.fromEntries(days.map((d) => [d, evs.filter((e) => e.date === d)]));

    // summary strip
    const total = evs.reduce((s, e) => s + mcapOf(e), 0);
    const conf = evs.filter((e) => e.status === 'confirmed').length;
    const big = days.map((d) => [d, byDay[d].reduce((s, e) => s + mcapOf(e), 0)]).sort((a, b) => b[1] - a[1])[0];
    const il = st.market === 'IL' ? 0 : evs.filter((e) => e.market === 'IL').length;
    root.append(h('div', { class: 'kpis' },
      kpi(String(evs.length), 'דוחות השבוע'),
      kpi(FC.money(total), 'שווי שוק מדווח'),
      kpi(`${conf}`, 'מועדים מאומתים'),
      big && big[1] ? kpi(FC.dayName(big[0]), `היום העמוס (${FC.money(big[1])})`) : null,
      st.market === 'US' ? nextIL() : null));

    const mapSec = h('section', { class: 'map-sec', 'aria-label': 'מפת הדוחות' },
      h('div', { class: 'sec-h' }, h('h2', null, 'מפת הדוחות'), h('p', null, 'גודל כל ריבוע לפי שווי השוק. לחיצה פותחת את כרטיס החברה.')));
    const holder = h('div', { class: 'tm' });
    mapSec.append(holder, h('div', { class: 'legend' },
      h('span', null, h('span', { class: 'tm-badge static' }, 'BMO'), 'לפני פתיחת המסחר'),
      h('span', null, h('span', { class: 'tm-badge static' }, 'AMC'), 'אחרי סגירת המסחר'),
      h('span', null, h('span', { class: 'tm-ok static' }), 'מועד ושעות מאומתים מול הודעת החברה'),
      h('span', null, `שעות ב${st.tz === FC.TZ.IL ? 'שעון ישראל' : 'שעון ניו יורק'} · הפרש ישראל–ניו יורק השבוע: ${FC.gapHours(days[0])}${FC.gapHours(days[4]) !== FC.gapHours(days[0]) ? '–' + FC.gapHours(days[4]) : ''} שעות`)));
    root.append(mapSec);

    const tables = h('section', { class: 'tables', 'aria-label': 'טבלאות לפי יום' });
    days.forEach((d) => tables.append(dayTable(d, byDay[d], st)));

    const chartSec = h('section', { class: 'chart-sec' },
      h('div', { class: 'sec-h' }, h('h2', null, 'שווי השוק המדווח בכל שבוע'), h('p', null, 'סך שווי השוק של החברות שמדווחות בכל שבוע, לפי ימים. שבועות מסומנים "חלקי" עוד לא נטענו במלואם.')),
      capChart(st),
      h('div', { class: 'legend' }, ['שני', 'שלישי', 'רביעי', 'חמישי', 'שישי'].map((n, i) => h('span', null, h('span', { class: `dsw d${i}` }), n))));

    root.append(h('div', { class: 'below' }, tables, chartSec));

    // layout after insertion (needs width) + on resize
    requestAnimationFrame(() => buildMap(holder, days, byDay, st));
    if (ro) ro.disconnect();
    if ('ResizeObserver' in window) {
      let last = 0, t = null;
      ro = new ResizeObserver(() => { const w = holder.clientWidth; if (Math.abs(w - last) < 4) return; last = w; clearTimeout(t); t = setTimeout(() => buildMap(holder, days, byDay, st), 60); });
      ro.observe(holder);
    }
  };
  function nextIL() {
    const today = FC.todayIL();
    const n = FC.store.events.filter((e) => e.market === 'IL' && e.date >= today).sort((a, b) => (a.date < b.date ? -1 : 1))[0];
    if (!n) return null;
    const p = FC.store.profiles[n.ticker] || {};
    return h('button', { class: 'kpi kpi-btn', type: 'button', onclick: () => { FC.state.week = FC.mondayOf(n.date); FC.setMarket('IL'); FC.panel.open(n.id); } },
      h('span', { class: 'kpi-v' }, (p.name || n.ticker).split('·')[0].trim()), h('span', { class: 'kpi-l' }, `הדוח הישראלי הבא · ${FC.dayName(n.date)} ${FC.shortDate(n.date)}`));
  }
  function kpi(v, l) { return h('div', { class: 'kpi' }, h('span', { class: 'kpi-v' }, v), h('span', { class: 'kpi-l' }, l)); }
})();
