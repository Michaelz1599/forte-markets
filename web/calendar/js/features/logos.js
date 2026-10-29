/* ============================================================
   LAYER: logos
   Reads data/logos.json → { logos: { TICKER: "assets/logos/TICKER.png" } }.
   When a ticker has no logo file, a neutral Forte monogram is drawn.
   To add logos later: publish the image files and list them in logos.json —
   nothing else in the site changes.
   ============================================================ */
(function () {
  'use strict';
  const FC = window.FC, h = FC.h;
  FC.logo = function (t, opts) {
    opts = opts || {};
    const p = FC.store.profiles[t] || {};
    const el = h('span', { class: 'mono' + (opts.lg ? ' lg' : ''), 'aria-hidden': 'true' });
    const src = FC.store.logos[t];
    if (src) {
      const img = h('img', { src, alt: '' });
      img.addEventListener('error', () => { img.remove(); el.textContent = label(t); });
      el.append(img);
    } else {
      el.textContent = label(t);
    }
    if (p.country === 'IL') el.append(h('span', { class: 'flag' }, 'IL'));
    return el;
  };
  function label(t) { return t.length <= 4 ? t : t.slice(0, 4); }
})();
