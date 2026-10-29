/* ============================================================
   LAYER: company panel (drawer).
   Shows only the essentials; everything else lives in collapsed
   categories that come from FC.sections (one file per category).
   ============================================================ */
(function () {
  'use strict';
  const FC = window.FC, h = FC.h;
  let lastFocus = null, current = null;

  function whenBlock(c, st) {
    const ev = c.ev, tm = FC.store.timing(ev, st.tz);
    const zone = st.tz === FC.TZ.IL ? 'שעון ישראל' : 'ET';
    const relV = tm.release
      ? h('span', { class: 'v' }, `${tm.release.main} ${zone}`, h('small', null, `${tm.release.alt}${tm.release.dayShift ? ' · ' + tm.release.dayShift : ''}`))
      : h('span', { class: 'v' }, FC.SESSION_HE[ev.session] || '—', h('small', null, tm.slotHint || ''));
    let callV;
    if (tm.call) {
      callV = h('span', { class: 'v' }, `${tm.call.main} ${zone}`,
        tm.call.dayShift ? h('small', null, `נופל ב${tm.call.dayShift} לפי ${zone}`) : null,
        h('small', null, tm.call.alt + (ev.call.confirmed ? '' : ' · לפי הרבעון הקודם, טרם אושר')),
        ev.call.hebrewCallIL ? h('small', null, `שיחה בעברית: ${ev.call.hebrewCallIL} שעון ישראל`) : null);
    } else {
      callV = h('span', { class: 'v' }, 'טרם פורסם', h('small', null, 'השעה תתעדכן כשהחברה תפרסם אותה'));
    }
    const actions = h('div', { class: 'when-actions' });
    if (FC.ics) actions.append(h('a', { class: 'btn btn-primary', href: FC.ics.outlookLink(ev), target: '_blank', rel: 'noopener' }, FC.icon('cal'), 'הוספה ל-Outlook'));
    if (ev.call && ev.call.webcast) actions.append(h('a', { class: 'btn', href: ev.call.webcast, target: '_blank', rel: 'noopener' }, FC.icon('mic'), 'שיחת הוועידה'));
    return h('div', { class: 'when' },
      h('div', { class: 'when-row' }, h('span', { class: 'k' }, 'מועד'), h('span', { class: 'v' }, FC.longDate(ev.date), h('small', null, [ev.period, ev.status === 'confirmed' ? 'מאומת מול הודעת החברה' : 'לפי לוח הדוחות; טרם אומת'].filter(Boolean).join(' · ')))),
      h('div', { class: 'when-row' }, h('span', { class: 'k' }, 'פרסום הדוח'), relV),
      h('div', { class: 'when-row' }, h('span', { class: 'k' }, 'שיחת ועידה'), callV),
      ev.note ? h('div', { class: 'status err' }, ev.note) : null,
      actions);
  }
  function relText(t) {
    return ({ 'after market close': 'אחרי סגירת המסחר', 'before market open': 'לפני פתיחת המסחר' })[t] || t;
  }

  function category(def, c, st) {
    const sum = def.summary ? def.summary(c, st) : '';
    const d = h('details', { class: 'cat', 'data-sec': def.id },
      h('summary', null, h('span', { class: 't' }, def.title), sum ? h('span', { class: 's' }, sum) : null, FC.icon('chev', 'chev')));
    let built = false;
    d.addEventListener('toggle', () => {
      if (d.open && !built) {
        built = true;
        let body;
        try { body = def.render(c, st); } catch (e) { console.error(e); body = h('p', { class: 'muted' }, 'לא ניתן להציג את החלק הזה כרגע.'); }
        d.append(h('div', { class: 'cat-body' }, body));
      }
    });
    return d;
  }

  FC.panel = {
    open(id) {
      const ev = FC.store.eventById(id);
      if (!ev) return;
      this.close(true);
      lastFocus = document.activeElement;
      const st = FC.state, c = FC.store.ctx(ev);
      st.openId = id;
      const p = c.profile;
      const scrim = h('div', { class: 'scrim', onclick: () => this.close() });
      const closeBtn = h('button', { class: 'd-close', type: 'button', 'aria-label': 'סגירה', onclick: () => this.close() }, FC.icon('close'));
      const drawer = h('aside', { class: 'drawer', role: 'dialog', 'aria-modal': 'true', 'aria-label': p.name || ev.ticker },
        h('div', { class: 'd-head' },
          FC.logo(ev.ticker, { lg: true }),
          h('div', { style: 'min-width:0' },
            h('div', { class: 'd-name' }, p.name || ev.ticker),
            h('div', { class: 'd-sub' }, h('span', { class: 'tk' }, ev.ticker), p.sectorHe ? h('span', null, '· ' + p.sectorHe) : null,
              (p.tags || []).map((t) => h('span', { class: 'tag' }, FC.TAG_HE[t] || t)))),
          closeBtn),
        h('div', { class: 'd-body' },
          whenBlock(c, st),
          FC.sections.all().filter((s) => !s.when || s.when(c)).map((s) => category(s, c, st))
        ));
      document.body.append(scrim, drawer);
      current = { scrim, drawer };
      document.body.style.overflow = 'hidden';
      closeBtn.focus();
      document.querySelectorAll('.tile[aria-current="true"]').forEach((x) => x.removeAttribute('aria-current'));
      const tl = document.querySelector(`.tile[data-ev="${CSS.escape(id)}"]`);
      if (tl) tl.setAttribute('aria-current', 'true');
    },
    close(silent) {
      if (!current) return;
      current.scrim.remove(); current.drawer.remove(); current = null;
      document.body.style.overflow = '';
      FC.state.openId = null;
      document.querySelectorAll('.tile[aria-current="true"]').forEach((x) => x.removeAttribute('aria-current'));
      if (!silent && lastFocus && lastFocus.focus) lastFocus.focus();
    }
  };
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { if (document.querySelector('.modal')) FC.closeModal && FC.closeModal(); else FC.panel.close(); } });
})();
