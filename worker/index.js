// Forte market dashboard - Cloudflare Worker.
// Serves the static site (./site) and a small API for what the analyst edits on the site:
// technical analyses (with chart images), the market summary, and manual indicator data.
// Reads are open to whoever can open the site; every write needs the editor code (sha-256 in EDITOR_HASH).
// Storage: one KV namespace (binding KV).
//   stocks         {TICKER: doc}                 all analysis cards
//   ver:TICKER     [doc, ...]                    up to 30 previous versions, newest first
//   note           {text, at}                    the "bottom line" summary
//   custom         {indicators:{}, overrides:{}, points:{id:{date:value}}}
//   img:ID         image bytes (metadata: content type)

const JSON_HEADERS = { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' };
const TICKER_RE = /^[A-Z0-9][A-Z0-9._:\-]{0,19}$/;
const MAX_IMG = 8 * 1024 * 1024;

const json = (obj, status = 200) => new Response(JSON.stringify(obj), { status, headers: JSON_HEADERS });
const bad = (msg, status = 400) => json({ error: msg }, status);

async function sha256hex(text) {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

function sameHex(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string' || a.length !== b.length) return false;
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}

async function isEditor(request, env) {
  const code = request.headers.get('x-editor-code') || '';
  if (!code || !env.EDITOR_HASH) return false;
  return sameHex(await sha256hex(code), String(env.EDITOR_HASH).toLowerCase());
}

async function getJSON(env, key, fallback) {
  const v = await env.KV.get(key, 'json');
  return v == null ? fallback : v;
}

function cleanDoc(body, ticker) {
  const s = (v, n = 4000) => (v == null ? '' : String(v).slice(0, n));
  const doc = {
    ticker,
    name: s(body.name, 200), sector: s(body.sector, 120), bias: ['bull', 'bear', 'neutral', 'watch'].includes(body.bias) ? body.bias : 'neutral',
    horizon: ['short', 'mid', 'long'].includes(body.horizon) ? body.horizon : '',
    price: body.price === '' || body.price == null || !isFinite(+body.price) ? null : +body.price,
    headline: s(body.headline, 600),
    points: Array.isArray(body.points) ? body.points.slice(0, 20).map((p) => s(p, 600)).filter(Boolean) : [],
    support: s(body.support, 200), resistance: s(body.resistance, 200), stop: s(body.stop, 200), target: s(body.target, 200),
    setup: s(body.setup, 300), body: s(body.body, 6000),
    tvUrl: /^https:\/\/([a-z0-9-]+\.)*tradingview\.com\//i.test(body.tvUrl || '') ? s(body.tvUrl, 500) : '',
    img: typeof body.img === 'string' && /^[a-f0-9]{32}$/.test(body.img) ? body.img : null,
    status: body.status === 'pending' ? 'pending' : 'active',
    updatedAt: body.status === 'pending' ? '' : new Date().toISOString(),
  };
  return doc;
}

async function handleApi(request, env, url) {
  const path = url.pathname.replace(/\/+$/, '');
  const method = request.method;

  if (path === '/api/state' && method === 'GET') {
    const [stocks, note, custom] = await Promise.all([
      getJSON(env, 'stocks', {}), getJSON(env, 'note', null), getJSON(env, 'custom', { indicators: {}, overrides: {}, points: {} }),
    ]);
    return json({ stocks, note, custom, now: new Date().toISOString() });
  }

  let m = path.match(/^\/api\/versions\/([^/]+)$/);
  if (m && method === 'GET') {
    const t = decodeURIComponent(m[1]).toUpperCase();
    if (!TICKER_RE.test(t)) return bad('bad ticker');
    return json(await getJSON(env, 'ver:' + t, []));
  }

  // ---- everything below writes and needs the editor code
  if (method === 'GET') return bad('not found', 404);
  if (!(await isEditor(request, env))) return bad('editor code required', 401);

  if (path === '/api/auth' && method === 'POST') return json({ ok: true });

  if (path === '/api/note' && method === 'PUT') {
    const body = await request.json();
    const note = { text: String(body.text || '').slice(0, 8000), at: new Date().toISOString() };
    await env.KV.put('note', JSON.stringify(note));
    return json(note);
  }

  if (path === '/api/custom' && method === 'PUT') {
    const body = await request.json();
    const custom = {
      indicators: body.indicators && typeof body.indicators === 'object' ? body.indicators : {},
      overrides: body.overrides && typeof body.overrides === 'object' ? body.overrides : {},
      points: body.points && typeof body.points === 'object' ? body.points : {},
    };
    const text = JSON.stringify(custom);
    if (text.length > 20 * 1024 * 1024) return bad('too large', 413);
    await env.KV.put('custom', text);
    return json({ ok: true, bytes: text.length });
  }

  m = path.match(/^\/api\/stocks\/([^/]+)$/);
  if (m) {
    const t = decodeURIComponent(m[1]).toUpperCase();
    if (!TICKER_RE.test(t)) return bad('bad ticker');
    const stocks = await getJSON(env, 'stocks', {});
    if (method === 'PUT') {
      const body = await request.json();
      const doc = cleanDoc(body, t);
      const prev = stocks[t];
      if (prev && prev.status !== 'pending' && doc.status !== 'pending') {
        const vers = await getJSON(env, 'ver:' + t, []);
        vers.unshift(prev);
        await env.KV.put('ver:' + t, JSON.stringify(vers.slice(0, 30)));
      }
      stocks[t] = doc;
      await env.KV.put('stocks', JSON.stringify(stocks));
      return json(doc);
    }
    if (method === 'DELETE') {
      if (stocks[t]) {
        const vers = await getJSON(env, 'ver:' + t, []);
        if (stocks[t].status !== 'pending') vers.unshift({ ...stocks[t], deletedAt: new Date().toISOString() });
        await env.KV.put('ver:' + t, JSON.stringify(vers.slice(0, 30)));
        delete stocks[t];
        await env.KV.put('stocks', JSON.stringify(stocks));
      }
      return json({ ok: true });
    }
  }

  if (path === '/api/stocks-bulk' && method === 'POST') {
    const body = await request.json();
    const stocks = await getJSON(env, 'stocks', {});
    let added = 0;
    for (const r of Array.isArray(body.items) ? body.items.slice(0, 2000) : []) {
      const t = String(r.ticker || '').toUpperCase().replace(/\s+/g, '');
      if (!TICKER_RE.test(t) || stocks[t]) continue;
      stocks[t] = cleanDoc({ name: r.name, sector: r.sector, status: 'pending' }, t);
      added++;
    }
    await env.KV.put('stocks', JSON.stringify(stocks));
    return json({ added });
  }

  if (path === '/api/img' && method === 'POST') {
    const ct = (request.headers.get('content-type') || '').split(';')[0].trim();
    if (!/^image\/(png|jpeg|webp|gif)$/.test(ct)) return bad('image type not allowed', 415);
    const buf = await request.arrayBuffer();
    if (buf.byteLength > MAX_IMG) return bad('image too large (max 8MB)', 413);
    const id = crypto.randomUUID().replace(/-/g, '');
    await env.KV.put('img:' + id, buf, { metadata: { ct } });
    return json({ id });
  }

  return bad('not found', 404);
}

async function handleImg(env, id) {
  if (!/^[a-f0-9]{32}$/.test(id)) return new Response('not found', { status: 404 });
  const { value, metadata } = await env.KV.getWithMetadata('img:' + id, 'arrayBuffer');
  if (!value) return new Response('not found', { status: 404 });
  return new Response(value, {
    headers: { 'content-type': (metadata && metadata.ct) || 'image/png', 'cache-control': 'private, max-age=31536000, immutable' },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    try {
      if (url.pathname.startsWith('/api/')) return await handleApi(request, env, url);
      const im = url.pathname.match(/^\/img\/([a-f0-9]{32})$/);
      if (im) return await handleImg(env, im[1]);
    } catch (e) {
      return bad('server error: ' + (e && e.message ? e.message : String(e)).slice(0, 200), 500);
    }
    const res = await env.ASSETS.fetch(request);
    if (url.pathname.startsWith('/data/')) {
      const h = new Headers(res.headers);
      h.set('cache-control', 'no-cache');
      return new Response(res.body, { status: res.status, headers: h });
    }
    return res;
  },
};
