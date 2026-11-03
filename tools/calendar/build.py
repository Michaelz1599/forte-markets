"""
Forte Earnings Calendar — data builder.
Assembles the DATA LAYER only (site/data/*). Never touches css/js.

Inputs (pipeline/):
  ew_week.py            Earnings Whispers week list (date -> BMO/AMC tickers)
  universe.json         filtered universe (built from EW + S&P/NDX + GLOBAL)
  focus_ir.py           verified release/call details from company IR
  val.txt               stockanalysis statistics lines (focus)
  ks.txt                Yahoo key-statistics lines (focus)
  cons.txt              consensus lines (Yahoo analysis / MarketBeat flagged MB)
  knowledge_*.py        static knowledge (Hebrew descriptions, industries, peers, voices, IL events)
  raw/                  GitHub datasets: sp500.csv, constituents-financials.csv, *_full_tickers.json
Outputs (site/data/):
  manifest.json, weeks/<monday>.json, market/<asof>.json, profiles.json, voices.json, logos.json
"""
import csv, json, os, re, sys, statistics, datetime as dt
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
RAW = os.path.join(HERE, '..', 'raw')
OUT = os.path.join(HERE, '..', 'site', 'data')
os.makedirs(os.path.join(OUT, 'weeks'), exist_ok=True)
os.makedirs(os.path.join(OUT, 'market'), exist_ok=True)

from ew_week import EW
from focus_ir import IR
from knowledge_industries import SECTOR_HE, SUB, NON_SPX
from knowledge_desc import DESC
from knowledge_manual import PEERS, LI_OVERRIDE, VOICES, IL_EVENTS, PREVIEW_US

from run_config import ASOF
UPDATED = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

# ---------- helpers
def num(s):
    if s is None: return None
    s = str(s).strip().replace(',', '').replace('$', '')
    if s in ('', 'NA', 'N/A', 'n/a', '--', '-'): return None
    mult = 1
    if s.endswith('%'): s = s[:-1]
    m = re.match(r'^(-?\d+(?:\.\d+)?)([TBMK]?)$', s)
    if not m: return None
    v = float(m.group(1)); u = m.group(2)
    mult = {'T': 1e12, 'B': 1e9, 'M': 1e6, 'K': 1e3, '': 1}[u]
    return v * mult

def lines(path):
    if not os.path.exists(path): return []
    return [l.strip() for l in open(path) if l.strip() and not l.startswith('#')]

# ---------- raw datasets
sp = {r['Symbol'].replace('.', '-'): r for r in csv.DictReader(open(os.path.join(RAW, 'sp500.csv')))}
fin = {r['Symbol'].replace('.', '-'): r for r in csv.DictReader(open(os.path.join(RAW, 'constituents-financials.csv')))}
lst = {}
for f in ['nasdaq', 'nyse', 'amex']:
    p = os.path.join(RAW, f'{f}_full_tickers.json')
    if os.path.exists(p):
        for x in json.load(open(p)):
            lst[x['symbol']] = dict(x, _exch=f.upper())
NDX = set(open(os.path.join(HERE, 'ndx.txt')).read().split())
U = json.load(open(os.path.join(HERE, 'universe.json')))

# ---------- market snapshot
market = {}
def put(t, **kw):
    d = market.setdefault(t, {'src': {}})
    for k, v in kw.items():
        if v is not None and k != 'src': d[k] = v

for t, r in fin.items():
    price = num(r['Price']); lo = num(r['52 Week Low']); hi = num(r['52 Week High'])
    put(t, price=price, mcap=num(r['Market Cap']), pe=num(r['Price/Earnings']), eps=num(r['Earnings/Share']),
        div=(num(r['Dividend Yield']) or 0) * 100, w52lo=lo, w52hi=hi, ebitda=num(r['EBITDA']),
        ps=num(r['Price/Sales']), pb=num(r['Price/Book']))
    market[t]['src']['base'] = 'S&P 500 financials (GitHub datasets)'

def from_list(t):
    x = lst.get(t)
    if not x: return
    if t not in market or market[t].get('mcap') is None:
        put(t, price=num(x['lastsale']), mcap=num(x['marketCap']))
        market[t]['src']['base'] = 'Nasdaq listings (GitHub mirror), סגירה קודמת'

for line in lines(os.path.join(HERE, 'val.txt')):
    p = line.split('|'); t = p[0]
    mc, ev = num(p[1]), num(p[2])
    put(t, ev=ev, pe=num(p[3]), fpe=num(p[4]), ps=num(p[5]), evEbitda=num(p[6]), peg=num(p[7]), beta=num(p[8]), div=num(p[9]))
    if t not in fin: put(t, mcap=mc, price=num(p[11]))
    elif mc and ev:  # keep dataset mcap, carry net debt
        market[t]['ev'] = market[t]['mcap'] + (ev - mc)
    market[t]['src']['valuation'] = 'StockAnalysis'

for line in lines(os.path.join(HERE, 'ks.txt')):
    p = line.split('|'); t = p[0]
    mc, ev = num(p[1]), num(p[2])
    d = market.get(t, {})
    base_mc = d.get('mcap')
    put(t, fpe=num(p[4]), peg=num(p[5]), evEbitda=num(p[9]), beta=num(p[10]))
    if base_mc is None: put(t, mcap=mc, pe=num(p[3]), ps=num(p[6]), pb=num(p[7]))
    if ev and mc: market[t]['ev'] = (market[t].get('mcap') or mc) + (ev - mc)
    if p[11] not in ('NA',) and market[t].get('div') is None: put(t, div=num(p[11]))
    market[t]['src']['valuation'] = 'Yahoo Finance (EV מותאם לשווי השוק דרך החוב נטו)'

# ---------- profiles
def sector_of(t):
    if t in sp: return sp[t]['GICS Sector'], sp[t]['GICS Sub-Industry']
    if t in NON_SPX: return NON_SPX[t][0], NON_SPX[t][1]
    return None, None

def name_of(t):
    if t in sp: return sp[t]['Security']
    if t in NON_SPX: return NON_SPX[t][2]
    x = lst.get(t)
    return x['name'] if x else t

def tags_of(t):
    tg = []
    if t in sp: tg.append('SPX')
    if t in NDX: tg.append('NDX')
    if t in NON_SPX and t not in sp and t not in NDX: tg.append('GLOBAL')
    return tg

# sector medians (trailing P/E) for factor calc
sec_pe = {}
for t, r in fin.items():
    s = sp.get(t, {}).get('GICS Sector'); pe = num(r['Price/Earnings'])
    if s and pe and 0 < pe < 200: sec_pe.setdefault(s, []).append(pe)
sec_med = {s: statistics.median(v) for s, v in sec_pe.items()}

def factors(t, sector):
    m = market.get(t, {}); out = []
    mc = m.get('mcap')
    if mc:
        out.append({'k': 'size', 'he': 'מגה-קאפ' if mc >= 200e9 else ('לארג\'-קאפ' if mc >= 10e9 else 'מיד-קאפ'), 'why': f"שווי שוק {mc/1e9:,.0f} מיליארד $"})
    pe = m.get('pe') or m.get('fpe'); med = sec_med.get(sector)
    if pe and med and pe > 0:
        r = pe / med
        lbl = 'Value' if r < 0.8 else ('Growth' if r > 1.25 else 'Blend')
        he = {'Value': 'ערך (Value)', 'Growth': 'צמיחה (Growth)', 'Blend': 'מעורב (Blend)'}[lbl]
        out.append({'k': 'style', 'he': he, 'why': f"מכפיל רווח {'נוכחי' if m.get('pe') else 'עתידי'} {pe:.1f} מול חציון הסקטור ב-S&P 500 ({med:.1f}), פי {r:.2f}"})
    lo, hi, pr = m.get('w52lo'), m.get('w52hi'), m.get('price')
    if lo and hi and pr and hi > lo and hi / lo < 2.6:  # skip ranges distorted by splits/corporate actions
        pos = (pr - lo) / (hi - lo)
        he = 'מומנטום חיובי' if pos >= 0.8 else ('מומנטום שלילי' if pos <= 0.2 else 'מומנטום ניטרלי')
        out.append({'k': 'momentum', 'he': he, 'why': f"המחיר ב-{pos*100:.0f}% מטווח 52 השבועות"})
    dv = m.get('div')
    if dv and dv >= 3:
        out.append({'k': 'yield', 'he': 'דיבידנד גבוה', 'why': f"תשואת דיבידנד {dv:.1f}%"})
    b = m.get('beta')
    if b is not None:
        if b < 0.7: out.append({'k': 'lowvol', 'he': 'תנודתיות נמוכה', 'why': f"בטא {b:.2f}"})
        elif b > 1.4: out.append({'k': 'highbeta', 'he': 'בטא גבוהה', 'why': f"בטא {b:.2f}"})
    return out

def auto_peers(t, sub):
    if not sub: return []
    c = [(num(fin.get(s, {}).get('Market Cap')) or 0, s) for s, r in sp.items() if r['GICS Sub-Industry'] == sub and s != t]
    return [s for _, s in sorted(c, reverse=True)[:5]]

profiles = {}
def make_profile(t, name=None, tags=None, sector=None, sub=None, country=None):
    if t in profiles: return
    sec, sb = sector_of(t)
    sector = sector or sec; sub = sub or sb
    subhe, li = SUB.get(sub, (sub, [])) if sub else (None, [])
    from_list(t)
    p = {
        'name': name or name_of(t),
        'tags': tags if tags is not None else tags_of(t),
        'sector': sector, 'sectorHe': SECTOR_HE.get(sector, sector),
        'sub': sub, 'subHe': subhe,
        'desc': DESC.get(t),
        'peers': PEERS.get(t) or auto_peers(t, sub),
        'peersAuto': t not in PEERS,
        'li': LI_OVERRIDE.get(t) or li,
        'liLevel': 'company' if t in LI_OVERRIDE else 'industry',
        'factors': factors(t, sector),
        'country': country or (NON_SPX[t][3] if t in NON_SPX else 'US'),
        'cik': sp[t]['CIK'] if t in sp else None,
        'exchange': (lst.get(t) or {}).get('_exch'),
    }
    profiles[t] = p

# ---------- existing published data (download it from the artifact first; see RUNBOOK)
def load_json(path, default):
    try: return json.load(open(path))
    except Exception: return default
OLD_MANIFEST = load_json(os.path.join(OUT, 'manifest.json'), {})
OLD_PROFILES = load_json(os.path.join(OUT, 'profiles.json'), {}).get('companies', {})
OLD_MARKET = load_json(os.path.join(OUT, OLD_MANIFEST.get('market', 'data/market/none.json').replace('data/', '', 1)), {})
OLD_VOICES = load_json(os.path.join(OUT, 'voices.json'), {}).get('items', {})

from run_config import TARGET_WEEK, WEEK_META, IL_SECTORS
try:
    from links import LINKS          # post-event links: {event_id: {pressRelease, replay, transcriptCall, transcriptReport, ...}}
except ImportError:
    LINKS = {}

# ---------- events
weeks = {}
def monday(d):
    x = dt.date.fromisoformat(d); return (x - dt.timedelta(days=x.weekday())).isoformat()

def cons_map():
    m = {}
    for line in lines(os.path.join(HERE, 'cons.txt')):
        p = line.split('|'); t = p[0]
        flagged = len(p) > 13 and p[13] == 'MB'
        m[t] = {
            'period': p[1], 'eps': num(p[2]), 'epsLow': num(p[3]), 'epsHigh': num(p[4]), 'epsN': num(p[5]), 'epsYearAgo': num(p[6]),
            'rev': num(p[7]), 'revLow': num(p[8]), 'revHigh': num(p[9]), 'revN': num(p[10]), 'revYearAgo': num(p[11]), 'revGrowth': num(p[12]),
            'source': 'MarketBeat (הערכה; פחות אמין — מקורות סותרים בעמוד)' if flagged else 'Yahoo Finance — Analysis (Current Qtr)',
            'quality': 'low' if flagged else 'normal', 'asof': ASOF,
        }
    return m
CONS = cons_map()

# QuarterChart consensus (primary when present; covers the week's largest names with one methodology)
QC = {}
for line in lines(os.path.join(HERE, 'qc.txt')):
    p = line.split('|'); QC[p[0]] = {'eps': num(p[2]), 'rev': num(p[3])}
for t, q in QC.items():
    y = CONS.get(t)
    base = {'period': (y or {}).get('period') or 'רבעון נוכחי', 'eps': q['eps'], 'rev': q['rev'], 'asof': ASOF,
            'source': 'QuarterChart (קונצנזוס אנליסטים)', 'quality': 'normal'}
    if y and y.get('quality') != 'low':
        agree = (y.get('eps') is not None and q['eps'] is not None and abs(y['eps'] - q['eps']) <= max(0.05, 0.08 * abs(q['eps'])))
        base.update({'epsYearAgo': y.get('epsYearAgo'), 'revYearAgo': y.get('revYearAgo'), 'revN': y.get('revN'),
                     'revLow': y.get('revLow'), 'revHigh': y.get('revHigh')})
        if q['rev'] and y.get('revYearAgo'): base['revGrowth'] = (q['rev'] / y['revYearAgo'] - 1) * 100
        if agree:
            base.update({'epsLow': y.get('epsLow'), 'epsHigh': y.get('epsHigh'), 'epsN': y.get('epsN')})
            base['source'] = 'QuarterChart; טווח ומספר אנליסטים: Yahoo Finance'
        elif y.get('eps') is not None:
            base['note'] = f"Yahoo Finance מציג ממוצע EPS של {y['eps']:.2f}; ייתכן שמדובר בבסיס חישוב שונה (GAAP מול מתואם)"
            base['source'] = 'QuarterChart; נתוני שנה קודמת: Yahoo Finance'
    elif y and y.get('quality') == 'low' and y.get('eps') is not None:
        base['note'] = f"MarketBeat הציג {y['eps']:.2f}"
    CONS[t] = base

# Earnings Whispers per-company consensus (ewc.txt: TICKER|date|quarter|eps|whisper|revenue) — fills names the sources above miss
for line in lines(os.path.join(HERE, 'ewc.txt')):
    p = line.split('|')
    if len(p) < 6 or p[0] in CONS: continue
    e = num(p[3].strip('()')) if p[3] not in ('NA',) else None
    if p[3].startswith('('): e = -e if e else e
    if e is None: continue
    CONS[p[0]] = {'period': p[2], 'eps': e, 'rev': num(p[5]), 'whisper': num(p[4]), 'asof': ASOF,
                  'source': 'Earnings Whispers (קונצנזוס אנליסטים)', 'quality': 'normal'}

def add_event(ev):
    if ev['date'] < TARGET_WEEK: return          # never rebuild past weeks here
    weeks.setdefault(monday(ev['date']), []).append(ev)

for r in U['rows']:
    t = r['t']; make_profile(t)
    ir = IR.get(t)
    ev = {
        'id': f"{t}-{r['date']}", 'ticker': t, 'market': 'US',
        'date': ir['date'] if ir else r['date'], 'session': r['session'],
        'period': (ir or {}).get('period'),
        'status': 'confirmed' if ir else 'listed',
        'release': None, 'call': None, 'links': {}, 'sources': [{'label': 'Earnings Whispers', 'url': f"https://www.earningswhispers.com/calendar/{r['date'].replace('-', '')}"}],
    }
    if ir:
        ev['release'] = {'text': ir['rel'], 'tz': 'America/New_York'}
        m = re.match(r'^(\d{2}):(\d{2}) ET$', ir['rel'])
        if m: ev['release']['time'] = f"{m.group(1)}:{m.group(2)}"
        ev['call'] = {'time': ir['call'], 'tz': 'America/New_York', 'confirmed': not ir.get('unconfirmedTime'), 'note': ir.get('callNote'), 'webcast': ir['webcast'], 'dial': ir.get('dial')}
        ev['sources'].insert(0, {'label': 'הודעת החברה', 'url': ir['src']})
        if ir.get('note'): ev['note'] = ir['note']
    if t in CONS: ev['consensus'] = CONS[t]
    add_event(ev)

for x in PREVIEW_US:
    t = x['t']; make_profile(t)
    add_event({'id': f"{t}-{x['date']}", 'ticker': t, 'market': 'US', 'date': x['date'], 'session': x['session'], 'period': x.get('period'),
               'status': 'confirmed', 'release': {'text': 'after market close' if x['session'] == 'AMC' else 'before market open', 'tz': 'America/New_York'},
               'call': {'time': x['call'], 'tz': x['callTz'], 'confirmed': True, 'webcast': x['webcast']},
               'links': {}, 'sources': [{'label': 'הודעת החברה', 'url': x['src']}]})

SUB.setdefault('Renewable Electricity', ('אנרגיה מתחדשת', ["ריבית ארוכה", "מחירי חשמל", "אישורי חיבור לרשת"]))
SUB.setdefault('Independent Power Producers & Energy Traders', ('יצרני חשמל פרטיים', ["ביקוש לחשמל", "מחירי גז", "תעריפי רגולטור"]))

for x in IL_EVENTS:
    t = x['t']
    us = x.get('usTicker')
    sec, sub = IL_SECTORS[t]
    if us: from_list(us)
    make_profile(t, name=f"{x['nameHe']} · {x['name']}", tags=x['tags'], sector=sec, sub=sub, country='IL')
    profiles[t]['factors'] = factors(t, sec)
    ev = {'id': f"{t}-{x['date']}", 'ticker': t, 'market': 'IL', 'date': x['date'], 'session': x['session'], 'period': x.get('period', 'Q3 2026'),
          'status': 'confirmed',
          'release': ({'time': x['rel'], 'tz': x.get('relTz', 'America/New_York'), 'text': ''} if x.get('rel') else {'text': 'שעה לא צוינה בהודעה'}),
          'call': {'time': x['call'], 'tz': x['callTz'], 'confirmed': True, 'webcast': x['webcast'], 'hebrewCallIL': x.get('callHe')},
          'links': {}, 'sources': [{'label': 'הודעת החברה', 'url': x['src']}]}
    if x.get('note'): ev['note'] = x['note']
    add_event(ev)

for t, p in profiles.items():
    if p['sub'] and not p['subHe']:
        p['subHe'], li = SUB.get(p['sub'], (p['sub'], []))
        if not p['li']: p['li'] = li

# ---------- write: rebuilt weeks (>= TARGET_WEEK)
def sort_key(e):
    return (e['date'], {'BMO': 0, 'DMT': 1, 'TBD': 2, 'AMC': 3}.get(e['session'], 2), -(market.get(e['ticker'], {}).get('mcap') or 0))
for mon, evs in weeks.items():
    for e in evs:
        if e['id'] in LINKS: e['links'].update(LINKS[e['id']])
    evs.sort(key=sort_key)
    json.dump({'week': mon, 'generated': UPDATED, 'events': evs}, open(os.path.join(OUT, 'weeks', f'{mon}.json'), 'w'), ensure_ascii=False, separators=(',', ':'))

# ---------- patch past weeks: only links (recordings / transcripts / press releases)
patched = []
for w in OLD_MANIFEST.get('weeks', []):
    if w['id'] in weeks: continue
    path = os.path.join(OUT, 'weeks', f"{w['id']}.json")
    data = load_json(path, None)
    if not data: continue
    hit = False
    for e in data['events']:
        if e['id'] in LINKS:
            e.setdefault('links', {}).update(LINKS[e['id']]); hit = True
    if hit:
        data['generated'] = UPDATED
        json.dump(data, open(path, 'w'), ensure_ascii=False, separators=(',', ':')); patched.append(w['id'])

# ---------- market snapshot (merge: keep older quotes, stamp their as-of)
old_q = OLD_MARKET.get('quotes', {})
for t, q in old_q.items(): q.setdefault('asof', OLD_MARKET.get('asof'))
mk = dict(old_q)
for t in list(profiles) + ['TEVA', 'TSEM', 'ENLT', 'CAMT', 'NVMI']:
    if t in market:
        q = dict(market[t]); q['asof'] = ASOF; mk[t] = q
json.dump({'asof': ASOF, 'generated': UPDATED, 'quotes': mk}, open(os.path.join(OUT, 'market', f'{ASOF}.json'), 'w'), ensure_ascii=False, separators=(',', ':'))

# ---------- profiles (merge: new data wins, older companies are kept)
allp = dict(OLD_PROFILES); allp.update(profiles)
json.dump({'generated': UPDATED, 'companies': allp}, open(os.path.join(OUT, 'profiles.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
allv = dict(OLD_VOICES); allv.update(VOICES)
json.dump({'generated': UPDATED, 'items': allv}, open(os.path.join(OUT, 'voices.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
if not os.path.exists(os.path.join(OUT, 'logos.json')):
    json.dump({'note': 'ticker -> asset path or URL in this artifact; empty = monogram', 'logos': {}}, open(os.path.join(OUT, 'logos.json'), 'w'))

# ---------- manifest (merge weeks)
wk = {w['id']: w for w in OLD_MANIFEST.get('weeks', [])}
for m_, evs in weeks.items():
    wk[m_] = dict(id=m_, file=f'data/weeks/{m_}.json', count=len(evs), **WEEK_META.get(m_, {}))
for m_ in list(wk):
    if m_ in WEEK_META and m_ not in weeks: wk[m_].update(WEEK_META[m_])
manifest = {
    'app': 'Forte Earnings Calendar', 'schema': 1, 'updated': UPDATED, 'marketAsOf': ASOF,
    'nextUpdate': 'כל יום ראשון בבוקר (שעון ישראל)',
    'weeks': [wk[k] for k in sorted(wk)],
    'market': f'data/market/{ASOF}.json', 'profiles': 'data/profiles.json', 'voices': 'data/voices.json', 'logos': 'data/logos.json', 'macro': 'data/macro.json',
    'universes': [
        {'id': 'SPX', 'he': 'S&P 500'}, {'id': 'NDX', 'he': 'נאסד"ק 100'}, {'id': 'GLOBAL', 'he': 'גלובלי (ADR)'},
        {'id': 'TA125', 'he': 'ת"א 125'}, {'id': 'TASE', 'he': 'ת"א כל המניות'},
    ],
    'sources': [
        {'label': 'Earnings Whispers — לוח שבועי', 'url': 'https://www.earningswhispers.com/calendar'},
        {'label': 'הודעות חברות (IR / PR Newswire / GlobeNewswire)', 'url': None},
        {'label': 'S&P 500 constituents + financials (GitHub datasets)', 'url': 'https://github.com/datasets/s-and-p-500-companies-financials'},
        {'label': 'Yahoo Finance — Analysis / Key statistics', 'url': 'https://finance.yahoo.com'},
        {'label': 'StockAnalysis — Statistics', 'url': 'https://stockanalysis.com'},
    ],
}
json.dump(manifest, open(os.path.join(OUT, 'manifest.json'), 'w'), ensure_ascii=False, indent=1)
print('rebuilt weeks:', {m_: len(v) for m_, v in weeks.items()}, '| patched past weeks:', patched, '| profiles:', len(allp), '| quotes:', len(mk))
print('missing desc:', [t for t in profiles if not profiles[t]['desc']])
print('PUBLISH THESE FILES:', ['data/manifest.json', f'data/market/{ASOF}.json', 'data/profiles.json', 'data/voices.json'] + [f'data/weeks/{m_}.json' for m_ in sorted(weeks)] + [f'data/weeks/{m_}.json' for m_ in patched])
