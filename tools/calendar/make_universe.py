"""Build universe.json from ew_week.py (Earnings Whispers lists) + S&P 500 / Nasdaq-100 / GLOBAL filter.
GLOBAL = non-index companies listed in the US with market cap >= $30B (ADRs and large caps), minus preferreds/LP duplicates."""
import csv, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
RAW = os.path.join(HERE, '..', 'raw')
from ew_week import EW
sp = {r['Symbol'].replace('.', '-') for r in csv.DictReader(open(os.path.join(RAW, 'sp500.csv')))}
ndx = set(open(os.path.join(HERE, 'ndx.txt')).read().split())
mc = {}
for f in ['nasdaq', 'nyse', 'amex']:
    for x in json.load(open(os.path.join(RAW, f'{f}_full_tickers.json'))):
        try: mc[x['symbol']] = (float(x['marketCap'] or 0), x['name'])
        except Exception: pass
EXCLUDE = {'STRF', 'STRK', 'STRD', 'CQP', 'GOOG'}   # preferreds / LP twins / share-class duplicates
rows = []
for d, s in EW.items():
    for sess, t in s.items():
        for tk in t.split():
            if tk.startswith('T.') or tk in EXCLUDE: continue
            tags = []
            if tk in sp: tags.append('SPX')
            if tk in ndx: tags.append('NDX')
            m = mc.get(tk, (0, ''))
            if not tags and m[0] >= 30e9: tags.append('GLOBAL')
            if tags: rows.append(dict(t=tk, date=d, session=sess, tags=tags, mcap=m[0]))
json.dump({'rows': rows}, open(os.path.join(HERE, 'universe.json'), 'w'), indent=0)
print(len(rows), 'events;', sum('GLOBAL' in r['tags'] for r in rows), 'GLOBAL')
missing = [r['t'] for r in rows if 'GLOBAL' in r['tags']]
print('GLOBAL tickers (need NON_SPX classification in knowledge_industries.py):', missing)
