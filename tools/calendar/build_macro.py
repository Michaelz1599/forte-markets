"""Macro layer builder: macro_us.jsonl + macro_il.jsonl -> site/data/macro.json (separate from earnings data).
Adds ids, time zones and a one-line Hebrew 'why it matters' per event type."""
import json, os, re, datetime as dt
HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, '..', 'site', 'data')

WHY = [  # (country, regex on English name, Hebrew explanation)
 ('US', r'FOMC.*(decision|rate)|Federal Funds|Rate Decision', 'החלטת הריבית של הפד קובעת את מחיר הכסף בארה"ב; משפיעה ישירות על אג"ח, דולר ומכפילי המניות. מסיבת העיתונאים חשובה לא פחות מההחלטה.'),
 ('US', r'Minutes', 'הפרוטוקול חושף את הוויכוח בתוך הוועדה ואת הנטייה לצעד הבא; עשוי להזיז את ציפיות הריבית.'),
 ('US', r'\bCPI\b|Consumer Price', 'מדד האינפלציה המרכזי בארה"ב; הפתעה כלפי מעלה מעלה תשואות ומקשה על הפד להוריד ריבית.'),
 ('US', r'PCE|Personal Income', 'מדד האינפלציה המועדף על הפד (PCE ליבה) ונתוני הצריכה וההכנסה של משקי הבית.'),
 ('US', r'Employment Situation|Payroll|Jobs', 'דוח התעסוקה החודשי: משרות חדשות, שיעור אבטלה ושכר. אחד הנתונים שמזיזים הכי הרבה את השוק.'),
 ('US', r'GDP', 'קצב הצמיחה של הכלכלה האמריקאית; ההערכה הראשונה היא המשמעותית ביותר.'),
 ('US', r'PPI|Producer Price', 'אינפלציית מחירי היצרן; אינדיקציה מוקדמת ללחצי מחירים שיגיעו לצרכן.'),
 ('US', r'Retail Sales', 'מכירות קמעונאיות: מדד מהיר לצריכה הפרטית, כ-70% מהכלכלה האמריקאית.'),
 ('US', r'ISM.*Manufactur', 'סקר מנהלי רכש בתעשייה: מעל 50 מעיד על התרחבות. אינדיקטור מקדים למחזור התעשייתי.'),
 ('US', r'ISM.*Serv', 'סקר מנהלי רכש בשירותים, החלק הגדול של הכלכלה; כולל רכיב מחירים שעוקבים אחריו לאינפלציה.'),
 ('US', r'JOLTS|Job Openings', 'משרות פנויות ותחלופת עובדים; מראה את מצב הביקוש לעובדים לפני דוח התעסוקה.'),
 ('US', r'Michigan|Sentiment', 'אמון הצרכנים וציפיות האינפלציה של משקי הבית (סקר מישיגן).'),
 ('US', r'Conference Board|Confidence', 'אמון הצרכנים של הקונפרנס בורד; משקף את תחושת שוק העבודה בקרב הצרכנים.'),
 ('US', r'[Ee]lection', 'חלוקת הכוחות בקונגרס תשפיע על מדיניות פיסקלית, מכסים ורגולציה בשנתיים הבאות.'),
 ('IL', r'[Ii]nterest [Rr]ate|Rate Decision|Monetary', 'החלטת הריבית של בנק ישראל: משפיעה על המשכנתאות, השקל, אג"ח ממשלתיות ובנקים.'),
 ('IL', r'[Mm]inutes|[Dd]iscussion', 'סיכום הדיונים חושף כמה חברי ועדה תמכו בכל צעד ואת השיקולים להחלטה הבאה.'),
 ('IL', r'CPI|Consumer Price', 'מדד המחירים לצרכן: קובע את האינפלציה בישראל, משפיע על החלטות בנק ישראל ועל האג"ח הצמודות. מתפרסם יחד עם מדד מחירי הדירות.'),
 ('IL', r'GDP', 'קצב הצמיחה של המשק הישראלי ברבעון; האומדן הראשון זוכה לתשומת הלב הרבה ביותר.'),
 ('IL', r'[Uu]nemployment|Labour|Labor', 'שיעור האבטלה מסקר כוח אדם; מדד להדיקות שוק העבודה ולחצי השכר.'),
 ('IL', r'[Ee]lection', 'הרכב הממשלה הבאה ישפיע על התקציב, הגירעון ודירוג האשראי של ישראל.'),
 ('IL', r'[Dd]eficit|[Bb]udget', 'הגירעון התקציבי ביחס לתוצר; משפיע על היקף הנפקות האג"ח הממשלתיות ועל דירוג האשראי.'),
]
SRC_LABEL = [(r'federalreserve\.gov', 'הפדרל ריזרב'), (r'bls\.gov', 'הלשכה לסטטיסטיקת עבודה (BLS)'), (r'bea\.gov', 'הלשכה לניתוח כלכלי (BEA)'),
             (r'census\.gov', 'הלשכה לסטטיסטיקה (Census)'), (r'ismworld', 'ISM'), (r'boi\.org\.il', 'בנק ישראל'), (r'cbs\.gov\.il', 'הלמ"ס'),
             (r'tradingeconomics', 'Trading Economics'), (r'fec\.gov', 'ועדת הבחירות הפדרלית')]

def why(c, en):
    for cc, rx, txt in WHY:
        if cc == c and re.search(rx, en or ''): return txt
    return None
def src_label(u):
    for rx, l in SRC_LABEL:
        if re.search(rx, u or ''): return l
    m = re.match(r'https?://(?:www\.)?([^/]+)', u or ''); return m.group(1) if m else 'מקור'

events = []
for f in ['macro_us.jsonl', 'macro_il.jsonl']:
    p = os.path.join(HERE, f)
    if not os.path.exists(p): continue
    for l in open(p):
        if not l.strip(): continue
        d = json.loads(l)
        c = d['country']
        e = {'id': f"M-{c}-{d['date']}-{re.sub(r'[^A-Za-z0-9]+', '', d['en'])[:24]}", 'kind': 'macro', 'country': c, 'date': d['date'], 'time': d.get('time'),
             'tz': 'America/New_York' if c == 'US' else 'Asia/Jerusalem', 'cat': d.get('cat'), 'imp': int(d.get('imp') or 1),
             'he': d['he'], 'en': d['en'], 'period': d.get('period'), 'prev': d.get('prev'), 'fcst': d.get('fcst'), 'actual': d.get('actual'),
             'note': d.get('note'), 'why': why(c, d['en']), 'src': {'label': src_label(d.get('src')), 'url': d.get('src')},
             'tentative': bool(d.get('note') and ('משוער' in d['note'] or 'לא אומת' in d['note'] or 'צפוי' in d['note']))}
        events.append(e)
events.sort(key=lambda e: (e['date'], e['time'] or '99', -e['imp']))
out = {'generated': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'events': events}
json.dump(out, open(os.path.join(OUT, 'macro.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
print(len(events), 'macro events ->', os.path.join(OUT, 'macro.json'), '| no why:', [e['en'] for e in events if not e['why']])
