"""One-off/weekly helper: add Earnings Whispers consensus (ewc.txt) to already-published week files, only where consensus is missing."""
import json, os, re, sys, glob
HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, '..', 'site', 'data', 'weeks')
ASOF = sys.argv[1] if len(sys.argv) > 1 else None
def num(s):
    s = s.strip().replace('$', '').replace(',', ''); neg = s.startswith('(') or s.startswith('-'); s = s.strip('()-')
    m = re.match(r'^([\d.]+)([TBMK]?)$', s)
    if not m: return None
    v = float(m.group(1)) * {'T': 1e12, 'B': 1e9, 'M': 1e6, 'K': 1e3, '': 1}[m.group(2)]
    return -v if neg else v
C = {}
for l in open(os.path.join(HERE, 'ewc.txt')):
    p = l.strip().split('|')
    if len(p) >= 6 and num(p[3]) is not None: C[p[0]] = p
moved = []
for f in sorted(glob.glob(os.path.join(OUT, '*.json'))):
    d = json.load(open(f)); n = 0
    for e in d['events']:
        p = C.get(e['ticker'])
        if not p or e.get('consensus'): continue
        if p[1] != e['date']: moved.append((e['ticker'], e['date'], p[1])); continue
        e['consensus'] = {'period': p[2], 'eps': num(p[3]), 'rev': num(p[5]) if p[5] != 'NA' else None, 'whisper': num(p[4]) if p[4] != 'NA' else None,
                          'asof': ASOF, 'source': 'Earnings Whispers (קונצנזוס אנליסטים)', 'quality': 'normal'}
        if e['ticker'] == 'INCY': e['consensus']['note'] = 'הקונצנזוס מוצג על בסיס GAAP (כולל הוצאה חד-פעמית צפויה); מומלץ לוודא.'
        n += 1
    if n: json.dump(d, open(f, 'w'), ensure_ascii=False, separators=(',', ':'))
    print(os.path.basename(f), 'added', n)
print('date mismatch (not applied):', moved)
