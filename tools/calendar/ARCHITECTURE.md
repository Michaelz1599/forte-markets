# יומן הדוחות של פורטה — ארכיטקטורה

**Artifact:** https://claude.ai/artifact/2MsyG4HvswjUH24wiAKu6S
**עדכון שבועי:** משימה מתוזמנת, יום ראשון בבוקר (שעון ישראל). מעדכנת רק את שכבת הנתונים (`data/`).

## העיקרון: שכבות נפרדות
כל פיצ'ר יושב בקובץ משלו. שינוי בקובץ אחד לא דורס אף קובץ אחר, ופרסום מחדש שולח רק את הקבצים שהשתנו (קבצים שלא נשלחים נשארים כמו שהם).

| שכבה | קבצים | מה משנים שם |
|---|---|---|
| עיצוב (מותג פורטה) | `css/tokens.css` | צבעים, פונטים, גדלים. אין צבע "קשיח" בשום מקום אחר |
| פריסה ורכיבים | `css/app.css` | מראה של אריחים, טבלאות, מגירה, חלונות |
| ליבה | `js/core.js` | טעינת נתונים, אזורי זמן (ניו יורק ↔ ישראל), פורמט מספרים, רישום קטגוריות |
| לוגואים | `js/features/logos.js` + `data/logos.json` | הוספת קובצי לוגו בלי לגעת בשאר האתר |
| ייצוא ליומן | `js/features/ics.js` | Outlook לאירוע בודד, קובץ ICS לחודש/שבוע |
| תצוגות | `js/views/week.js`, `js/views/month.js` | לוח שבועי, חודשי ורשימה |
| מאקרו | `js/views/macro.js` + `data/macro.json` | לשונית נפרדת: ריבית, אינפלציה, תעסוקה, צמיחה — ארה"ב וישראל. נבנה ע"י `pipeline/build_macro.py` |
| כרטיס חברה | `js/panel/company.js` | המגירה עצמה: כותרת, מועדים, ורשימת הקטגוריות |
| קטגוריות בכרטיס | `js/modules/*.js` | כל קטגוריה = קובץ אחד (ראו למטה) |
| מעטפת | `js/app.js`, `index.html` | מסננים, ניווט, סדר טעינת הקבצים |
| נתונים | `data/**` | נבנים ע"י `pipeline/build.py` — לא עורכים ידנית |

### קטגוריות בכרטיס החברה (`js/modules`)
| קובץ | כותרת | מקור נתונים |
|---|---|---|
| `event.js` | הדוח ושיחת הוועידה | `event.call`, `event.links` |
| `consensus.js` | ציפיות האנליסטים | `event.consensus` |
| `valuation.js` | שווי ומכפילים | `data/market/<date>.json` |
| `profile.js` | על החברה (תיאור, מה אמרו עליה, סקטור, פקטורים) | `profiles.json`, `voices.json` |
| `peers.js` | קבוצת השוואה ו-Leading Indicators | `profiles.json` |
| `models.js` | מודלים של פורטה (DCF) | `data/models/<TICKER>.json` |

קטגוריה חדשה: יוצרים קובץ ב-`js/modules`, קוראים ל-`FC.sections.register({id, order, title, summary, render})`, ומוסיפים שורת `<script>` אחת ב-`index.html`.

## הוספת מודל DCF של פורטה
1. יוצרים `data/models/MSFT.json` בפורמט:
```json
{ "title": "DCF — Microsoft", "author": "פורטה מחקר", "updated": "2026-11-01",
  "price": 524.51, "fairValue": 610,
  "assumptions": [{"k": "WACC", "v": "8.5%"}, {"k": "צמיחה פרמננטית", "v": "3.0%"}],
  "table": {"head": ["FY27E","FY28E","FY29E"], "rows": [{"k": "הכנסות ($B)", "v": ["391","468","540"]}]},
  "sensitivity": {"rowLabel": "WACC", "colLabel": "g", "rows": ["8%","9%"], "cols": ["2.5%","3%"], "values": [["640","690"],["560","600"]]},
  "file": "assets/models/MSFT.xlsx" }
```
2. מוסיפים ל-`data/models/index.json`: `"models": {"MSFT": "DCF · נובמבר 2026"}`.
3. מפרסמים רק את שני הקבצים האלה.

## נתונים — סכמות עיקריות
- `manifest.json` — רשימת שבועות (`weeks[] {id, file, count, label, coverage, note}`), קבצי שוק/פרופילים.
- `weeks/<monday>.json` — `events[]`: `{id, ticker, market: US|IL, date, session: BMO|AMC|TBD, period, status: confirmed|listed, release{time,tz,text}, call{time,tz,confirmed,webcast,dial,hebrewCallIL}, links{pressRelease,replay,transcriptCall,transcriptReport}, consensus{eps,epsLow,epsHigh,epsN,epsYearAgo,rev,...,source,quality}, sources[]}`
- `market/<asof>.json` — `quotes[ticker] {price, mcap, ev, pe, fpe, ps, pb, evEbitda, peg, beta, div, w52lo, w52hi, ebitda, asof, src}`
- `profiles.json` — `companies[ticker] {name, tags[SPX|NDX|GLOBAL|TA125|TASE], sector, sectorHe, sub, subHe, desc, peers[], peersAuto, li[], liLevel, factors[], country, cik}`
- `voices.json` — `items[ticker][] {who, type, date, he, src, url}`
- `logos.json` — `logos[ticker] = "assets/logos/MSFT.png"`

שעות נשמרות בשעון המקור (ET או ישראל) ומומרות בדפדפן — כך שבוע המעבר לשעון חורף (הפרש 6 שעות בין 26.10 ל-30.10 במקום 7) מוצג נכון.

## מגבלות ידועות (גרסה 1)
- **לוגואים:** האתר מציג סמל טיקר אחיד. לא שוכפלו לוגואים של החברות; אפשר להוסיף קבצים שיש לפורטה זכות להשתמש בהם דרך `logos.json`.
- **תמלולים ודוחות:** מקושרים במקור, לא משוכפלים.
- **קונצנזוס, EV ומכפיל עתידי:** נאספים לכ-30 החברות הגדולות בכל שבוע (Yahoo/StockAnalysis). לשאר — שווי שוק ומכפילים מנתוני S&P 500 היומיים, וקישור לנתונים חיים.
- **ת"א 125 / כל המניות:** רק חברות שהודיעו על מועד. חברות שנסחרות רק בת"א עדיין בלי נתוני שווי.
- **ייצוא ICS:** נשמר כ-ZIP (התצוגה לא מאפשרת שמירת ‎.ics‎ ישירות); לאירוע בודד יש כפתור Outlook.
- **שיתוף:** הקישור פרטי עד שמשתפים אותו מתפריט Share בעמוד; שיתוף מחוץ לארגון תלוי בהגדרות מנהל הארגון.
