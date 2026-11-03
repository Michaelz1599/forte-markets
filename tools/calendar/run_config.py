# Per-run settings (edit each weekly run)
ASOF = "2026-10-23"          # last US trading day of the market snapshot
TARGET_WEEK = "2026-10-26"   # Monday of the first week this run rebuilds; earlier weeks are only link-patched
WEEK_META = {
 '2026-10-26': {'label': '26–30 באוקטובר 2026', 'coverage': {'US': 'full', 'IL': 'none'}, 'note': 'עונת הדוחות של Q3 בארה"ב בשיאה. בישראל רוב הדוחות יתפרסמו בנובמבר.'},
 '2026-11-02': {'label': '2–6 בנובמבר 2026', 'coverage': {'US': 'preview', 'IL': 'announced'}, 'note': 'תצוגה מקדימה: רק מועדים שהחברות כבר הודיעו. הרשימה המלאה לארה"ב תתעדכן בעדכון השבועי הבא.'},
 '2026-11-09': {'label': '9–13 בנובמבר 2026', 'coverage': {'US': 'none', 'IL': 'announced'}, 'note': 'מועדים שהודיעו חברות ישראליות עד כה.'},
 '2026-11-16': {'label': '16–20 בנובמבר 2026', 'coverage': {'US': 'none', 'IL': 'announced'}, 'note': 'מועדים שהודיעו חברות ישראליות עד כה.'},
}
# GICS-style classification for Israeli tickers (TASE-only names are not in the US datasets)
IL_SECTORS = {
 'TEVA': ('Health Care', 'Pharmaceuticals'), 'TSEM': ('Information Technology', 'Semiconductors'),
 'ENLT': ('Utilities', 'Renewable Electricity'), 'CAMT': ('Information Technology', 'Semiconductor Materials & Equipment'),
 'NVMI': ('Information Technology', 'Semiconductor Materials & Equipment'), 'TASE': ('Financials', 'Financial Exchanges & Data'),
 'OPCE': ('Utilities', 'Independent Power Producers & Energy Traders'), 'MTAV': ('Financials', 'Asset Management & Custody Banks'),
 'ORA': ('Utilities', 'Renewable Electricity'), 'GILT': ('Information Technology', 'Communications Equipment'),
 'ICL': ('Materials', 'Fertilizers & Agricultural Chemicals'),
}
