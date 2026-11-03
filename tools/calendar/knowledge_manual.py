# Manual knowledge layer: peers overrides, voices (investor/CEO commentary links), Israeli events.

PEERS = {
 "GOOGL": ["META", "MSFT", "AMZN", "AAPL"],
 "MSFT": ["GOOGL", "AMZN", "ORCL", "CRM"],
 "AMZN": ["MSFT", "GOOGL", "WMT", "SHOP"],
 "LLY": ["NVO", "MRK", "ABBV", "AZN"],
 "V": ["MA", "AXP", "PYPL"],
 "MA": ["V", "AXP", "PYPL"],
 "XOM": ["CVX", "SHEL", "TTE", "BP"],
 "CVX": ["XOM", "SHEL", "TTE", "COP"],
 "INTC": ["AMD", "NVDA", "TSM", "QCOM"],
 "KO": ["PEP", "KDP", "MNST"],
 "SKHY": ["MU", "SNDK", "Samsung Electronics"],
 "SNDK": ["MU", "WDC", "SKHY", "Kioxia"],
 "STX": ["WDC", "SNDK", "NTAP"],
 "KLAC": ["AMAT", "LRCX", "ASML", "NVMI"],
 "NOW": ["CRM", "WDAY", "SAP", "ADBE"],
 "TMUS": ["VZ", "T", "CMCSA"],
 "VZ": ["T", "TMUS", "CMCSA"],
 "GEV": ["SIEGY", "Mitsubishi Heavy", "ETN", "HUBB"],
 "CAT": ["DE", "Komatsu", "PCAR"],
 "LIN": ["APD", "Air Liquide"],
 "BA": ["Airbus", "GE", "RTX"],
 "SBUX": ["MCD", "CMG", "QSR"],
 "HOOD": ["SCHW", "IBKR", "COIN"],
 "HSBC": ["Standard Chartered", "JPM", "SAN"],
 "AZN": ["NVS", "LLY", "MRK", "GSK"],
 "NVS": ["AZN", "RHHBY", "MRK", "SNY"],
 "SHEL": ["BP", "TTE", "XOM", "CVX"],
 "TTE": ["SHEL", "BP", "XOM", "EQNR"],
 "BP": ["SHEL", "TTE", "XOM"],
 "MSTR": ["COIN", "Bitcoin ETFs (IBIT)"],
 "COIN": ["HOOD", "MSTR", "CME"],
 "TEVA": ["Viatris", "Sandoz", "Hikma"],
 "TSEM": ["GFS", "UMC", "X-FAB"],
 "CAMT": ["KLAC", "ONTO", "NVMI"],
 "NVMI": ["KLAC", "ONTO", "CAMT"],
 "ENLT": ["NEE", "ORA", "BEP", "OPCE"],
 "TASE": ["ICE", "CBOE", "LSEG", "Deutsche Börse"],
 "OPCE": ["ENLT", "אנרג'יקס", "דוראל"],
 "MTAV": ["מור בית השקעות", "אלטשולר שחם", "IBI"],
 "ORA": ["ENLT", "NEE", "BEP"],
 "GILT": ["VSAT", "Hughes (SATS)", "COMM"],
 "ICL": ["MOS", "NTR", "ALB"],
}

LI_OVERRIDE = {
 "GOOGL": ["תקציבי פרסום דיגיטלי", "צמיחת Google Cloud וצבר הזמנות (backlog)", "קצב Capex של ההייפרסקיילרים (TPU)"],
 "MSFT": ["צמיחת Azure ו-RPO מסחרי", "Capex ענן ו-AI", "אימוץ Copilot בארגונים"],
 "AMZN": ["צמיחת AWS וזמינות קיבולת AI", "מכירות קמעונאיות מקוונות בארה\"ב", "תקציבי פרסום דיגיטלי"],
 "INTC": ["משלוחי מחשבים (IDC/Gartner)", "תמחור מעבדי שרתים מול AMD", "התקדמות 18A וחוזי Foundry"],
 "LLY": ["נתוני מרשמים שבועיים ל-Zepbound/Mounjaro (IQVIA)", "השקת תרופת ה-GLP-1 בכדור", "רגולציית מחירי תרופות"],
 "SKHY": ["מחירי DRAM ו-HBM (TrendForce)", "Capex AI של ההייפרסקיילרים", "יצוא שבבים מקוריאה (נתונים חודשיים)"],
 "SNDK": ["מחירי NAND חוזים (TrendForce)", "ביקוש SSD ארגוני לדאטה סנטרים", "Capex ההייפרסקיילרים"],
 "STX": ["מחירי HDD ומשלוחי Exabytes", "Capex ענן", "זמני אספקה (lead times)"],
 "GEV": ["הזמנות טורבינות גז וצבר ב-GW", "ביקוש לחשמל של דאטה סנטרים", "Capex חברות חשמל"],
 "XOM": ["מחיר ברנט ו-WTI", "מרווחי זיקוק", "הפקה בגיאנה ובפרמיאן"],
 "CVX": ["מחיר ברנט ו-WTI", "מרווחי זיקוק", "תפוקת Hess/גיאנה"],
 "V": ["נפחי תשלומים בארה\"ב (נתוני בנקים)", "נסיעות חוצות גבולות", "מכירות קמעונאיות"],
 "MA": ["נפחי תשלומים גלובליים", "נסיעות חוצות גבולות", "מכירות קמעונאיות"],
 "HOOD": ["מחזורי מסחר קמעונאי וקריפטו", "נכסים נטו (net deposits)", "ריבית על יתרות מזומן"],
 "COIN": ["מחיר ביטקוין ומחזורי מסחר קריפטו", "היקף USDC במחזור", "רגולציה"],
 "MSTR": ["מחיר ביטקוין", "פרמיית mNAV", "גיוסי הון"],
 "TEVA": ["מרשמי Austedo ו-Ajovy (IQVIA)", "תחרות גנרית ותמחור בארה\"ב", "מכסים על תרופות"],
 "TSEM": ["ביקוש למודולים אופטיים 800G/1.6T", "ניצולת מפעלים", "Capex דאטה סנטרים"],
 "CAMT": ["Capex ל-HBM ואריזה מתקדמת", "השקעות TSMC ב-CoWoS", "יצוא שבבים מטאיוואן"],
 "NVMI": ["הוצאות WFE (ציוד ייצור שבבים)", "Capex של TSMC וסמסונג", "מגבלות יצוא לסין"],
 "ENLT": ["ריבית ארוכה", "מחירי חשמל בישראל ובאירופה", "אישורי חיבור לרשת וזיכויי מס בארה\"ב"],
 "TASE": ["מחזורי מסחר יומיים בבורסה", "גיוסי הון והנפקות", "השקעות זרים בשוק המקומי"],
 "OPCE": ["ביקוש לחשמל ותעריף רשות החשמל", "מחירי גז טבעי", "צמיחת פעילות בארה\"ב (CPV)"],
 "MTAV": ["צבירות נטו בגמל ופנסיה", "תשואות שוק ההון", "מחזורי מסחר (ברוקראז')"],
}

# Investor / executive commentary and notable coverage. Summaries are paraphrased from headlines.
VOICES = {
 "GOOGL": [
  {"who": "ברקשייר האת'וויי (גרג אבל)", "type": "article", "date": "2026-08", "he": "ברקשייר כמעט הכפילה את האחזקה באלפבית עם קניות של כ-17 מיליארד דולר ברבעון השני של 2026 (דו\"ח 13F).", "src": "Morningstar", "url": "https://global.morningstar.com/en-gb/stocks/berkshire-hathaway-13f-purchases-outweighed-sales-alphabet-most-traded-q2"},
 ],
 "INTC": [
  {"who": "ג'נסן הואנג, אנבידיה", "type": "article", "date": "2026", "he": "הואנג תיאר את השקעת 5 מיליארד הדולר של אנבידיה באינטל כהשקעה מצוינת ושותפות לפיתוח מוצרים משותפים.", "src": "Yahoo Finance", "url": "https://finance.yahoo.com/news/nvidia-nvda-investment-intel-supports-111001416.html"},
 ],
 "AMZN": [
  {"who": "אנדי ג'סי, מנכ\"ל אמזון", "type": "article", "date": "2026-02-06", "he": "אמזון העלתה את תקציב ההשקעות ל-2026 לכ-200 מיליארד דולר כי ביקושי ה-AI ב-AWS עולים על הקיבולת הזמינה.", "src": "The Register", "url": "https://www.theregister.com/2026/02/06/amazon_earnings_q4_2025/"},
  {"who": "אנדי ג'סי, מנכ\"ל אמזון", "type": "article", "date": "2026", "he": "ג'סי פירט שש 'אמיתות' על AI ועל מקומה של אמזון בגל הנוכחי.", "src": "AI Magazine", "url": "https://aimagazine.com/news/amazon-ceo-andy-jassy-six-key-truths-of-ai"},
 ],
 "MSFT": [
  {"who": "סאטיה נאדלה, מנכ\"ל מיקרוסופט", "type": "interview", "date": "2026", "he": "נאדלה על כיוון ה-AI ב-2026: מעבר ארגונים מניסויים לפריסה רחבה.", "src": "IDN Financials", "url": "https://www.idnfinancials.com/news/60125/microsoft-ceo-satya-nadella-talks-about-where-ai-is-headed-in-2026"},
 ],
 "SKHY": [
  {"who": "ג'נסן הואנג, אנבידיה (CES 2026)", "type": "article", "date": "2026-01-07", "he": "הואנג התייחס במהלך CES למחסור בזיכרון HBM ולצורך של יצרניות הזיכרון להרחיב קיבולת.", "src": "DigiTimes", "url": "https://apps.digitimes.com/news/a20260107PD250/nvidia-jensen-huang-hbm-ces-2026.html"},
 ],
 "SNDK": [
  {"who": "ג'נסן הואנג, אנבידיה (CES 2026)", "type": "article", "date": "2026-01-07", "he": "דברי הואנג על מחסור בזיכרון ל-AI תמכו בציפייה למחזור זיכרון חזק גם ב-NAND.", "src": "DigiTimes", "url": "https://apps.digitimes.com/news/a20260107PD250/nvidia-jensen-huang-hbm-ces-2026.html"},
 ],
 "LLY": [
  {"who": "דייב ריקס, מנכ\"ל אלי לילי", "type": "interview", "date": "2025", "he": "בראיון ל-Bloomberg TV ריקס צפה אישור לגלולת ההרזיה orforglipron במהלך 2026.", "src": "TipRanks / The Fly", "url": "https://www.tipranks.com/news/the-fly/eli-lilly-ceo-tells-bloomberg-tv-company-sees-weight-loss-pill-approval-in-2026"},
 ],
 "GEV": [
  {"who": "הנהלת GE Vernova", "type": "article", "date": "2026", "he": "החברה העלתה את תחזית 2026 בזכות ביקוש לציוד חשמל מצד דאטה סנטרים של AI.", "src": "Investing.com", "url": "https://www.investing.com/news/stock-market-news/ge-vernova-lifts-annual-forecast-on-data-center-demand-4628562"},
 ],
 "V": [
  {"who": "ויזה ומאסטרקארד", "type": "article", "date": "2026", "he": "שתי החברות מדווחות על צרכן עמיד ומהמרות על סטייבלקוין ופתרונות שיווק כמנועי צמיחה.", "src": "eMarketer", "url": "https://www.emarketer.com/content/visa-mastercard-note-consumer-resilience--wager-on-stablecoin-marketing-solutions-growth"},
 ],
 "MA": [
  {"who": "ויזה ומאסטרקארד", "type": "article", "date": "2026", "he": "שתי החברות מדווחות על צרכן עמיד ומהמרות על סטייבלקוין ופתרונות שיווק כמנועי צמיחה.", "src": "eMarketer", "url": "https://www.emarketer.com/content/visa-mastercard-note-consumer-resilience--wager-on-stablecoin-marketing-solutions-growth"},
 ],
}

# Israeli Q3 2026 events with announced dates (company announcements, fetched 2026-10-24)
IL_EVENTS = [
 dict(t="TSEM", name="Tower Semiconductor", nameHe="טאואר", date="2026-11-02", session="BMO", call="10:00", callTz="America/New_York", rel=None, webcast="https://ir.towersemi.com/", src="https://www.globenewswire.com/news-release/2026/10/13/3379355/0/en/tower-semiconductor-announces-third-quarter-2026-financial-results-and-conference-call.html", tags=["TA125","TASE"], usTicker="TSEM"),
 dict(t="TEVA", name="Teva Pharmaceutical", nameHe="טבע", date="2026-11-03", session="BMO", call="08:00", callTz="America/New_York", rel="07:00", relTz="America/New_York", webcast="https://ir.tevapharm.com/Events-and-Presentations", src="https://finviz.com/news/394958/teva-to-host-conference-call-to-discuss-third-quarter-2026-financial-results-on-november-3-2026-at-8-am-et", tags=["TA125","TASE"], usTicker="TEVA"),
 dict(t="ENLT", name="Enlight Renewable Energy", nameHe="אנלייט", date="2026-11-03", session="BMO", call="08:00", callTz="America/New_York", callHe="13:00", webcast="https://edge.media-server.com/mmc/p/xho8qjz7", src="https://www.globenewswire.com/news-release/2026/10/13/3379602/0/en/enlight-to-report-third-quarter-2026-financial-results-on-tuesday-november-3-2026.html", tags=["TA125","TASE"], usTicker="ENLT"),
 dict(t="CAMT", name="Camtek", nameHe="קמטק", date="2026-11-04", session="BMO", call="09:00", callTz="America/New_York", webcast="https://us06web.zoom.us/webinar/register/WN_A25RpmzhT76YdX-pp3Jrwg", src="https://www.prnewswire.com/il/news-releases/camtek-to-report-third-quarter-2026-financial-results-on-wednesday-november-4-2026-302915313.html", tags=["TA125","TASE"], usTicker="CAMT"),
 dict(t="NVMI", name="Nova", nameHe="נובה", date="2026-11-05", session="BMO", call="08:30", callTz="America/New_York", webcast="https://www.novami.com/investors/events/", src="https://www.prnewswire.com/il/news-releases/nova-to-report-third-quarter-2026-financial-results-on-november-5-302909620.html", tags=["TA125","TASE"], usTicker="NVMI"),
 dict(t="TASE", name="Tel Aviv Stock Exchange", nameHe="הבורסה לני\"ע בת\"א", date="2026-11-10", session="AMC", call="20:00", callTz="Asia/Jerusalem", webcast="https://ir.tase.co.il/eng", src="https://www.prnewswire.com/il/news-releases/the-tel-aviv-stock-exchange-tase-schedules-third-quarter-2026-results-release-and-conference-call-for-tuesday-november-10-2026-302905831.html", tags=["TA125","TASE"]),
 dict(t="OPCE", name="OPC Energy", nameHe="או.פי.סי אנרגיה", date="2026-11-10", session="TBD", call="15:00", callTz="Asia/Jerusalem", webcast="https://www.veidan-conferencing.com/opcen", src="https://www.prnewswire.com/il/news-releases/opc-energy-to-report-third-quarter-2026-financial-results-on-tuesday-november-10-2026-302914272.html", tags=["TA125","TASE"], note="המועד כפוף לאישור הדירקטוריון"),
 # added 2026-10-25
 dict(t="ORA", name="Ormat Technologies", nameHe="אורמת טכנולוגיות", date="2026-11-04", session="AMC", call=None, callTz="America/New_York", webcast="https://investor.ormat.com/", src="https://www.globenewswire.com/news-release/2026/10/06/3375439/26372/en/index.html", tags=["TA125","TASE"], usTicker="ORA", note="שיחת הוועידה ביום חמישי 5.11 בשעה 10:00 ET (למחרת הפרסום)"),
 dict(t="GILT", name="Gilat Satellite Networks", nameHe="גילת רשתות לוויין", date="2026-11-10", session="TBD", call="09:30", callTz="America/New_York", webcast="https://www.veidan-conferencing.com/gilat", src="https://www.globenewswire.com/news-release/2026/10/15/3381536/11105/en/gilat-to-report-third-quarter-2026-results-on-tuesday-november-10.html", tags=["TASE"], usTicker="GILT", note="שיחה בעברית ביום רביעי 11.11 בשעה 10:00 שעון ישראל"),
 dict(t="ICL", name="ICL Group", nameHe="כי\"ל", date="2026-11-11", session="BMO", call="08:30", callTz="America/New_York", webcast="https://investors.icl-group.com/reports-news-and-events/default.aspx", src="https://www.businesswire.com/news/home/20261021227648/en/", tags=["TA125","TASE"], usTicker="ICL"),
 dict(t="MTAV", name="Meitav Investment House", nameHe="מיטב בית השקעות", date="2026-11-19", session="TBD", call="15:30", callTz="Asia/Jerusalem", callHe="11:00", webcast="https://zoom.us/j/91264073788", src="https://www.prnewswire.com/il/news-releases/meitav-investment-house-to-report-third-quarter-2026-financial-results-and-hold-a-conference-call-on-thursday-november-19-2026-302915402.html", tags=["TASE"]),
]

# Next-week US preview (confirmed by company announcements)
PREVIEW_US = [
 dict(t="AAPL", name="Apple", date="2026-11-02", session="AMC", call="17:00", callTz="America/New_York", webcast="https://investor.apple.com/", src="https://www.mactrast.com/2026/10/apple-to-announce-fiscal-q4-2026-earnings-on-november-2/", period="Q4 FY2026", tags=["SPX","NDX"]),
]
