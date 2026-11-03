> Since 3.11.2026 the pipeline lives in this repo (tools/calendar/). Work on a copy in ~/work/pipeline, save changed pipeline files back here,
> and publish by copying the built data files into data/calendar/ and pushing (no Artifact publish, no Project docs).
> data/calendar/nasdaq.json (Nasdaq's earnings calendar, every dashboard run) already lists every US company >= $10B for this week and the next.

# Weekly update runbook — Forte Earnings Calendar

Artifact URL: https://claude.ai/artifact/2MsyG4HvswjUH24wiAKu6S
Pipeline source: Project docs `claude/pipeline/*` (mirror inside the artifact at `pipeline/*.txt`).
Rule: **only publish files under `data/`**. Never republish `index.html`, `css/` or `js/` in a weekly run.

Run on Sunday morning (Israel). TARGET_WEEK = the coming Monday.

## 0. Workspace
```
mkdir -p ~/work/{pipeline,raw,site/data/weeks,site/data/market,site/data/models}
```
Copy every pipeline file from the Project (`claude/pipeline/<name>`) into `~/work/pipeline/` (strip a `.txt` suffix if you took them from the artifact).

## 1. Pull the currently published data (needed so nothing is overwritten)
`Artifact` read with `url` + `paths`: `index.html` (kept unchanged, used only as the publish anchor), `data/manifest.json`, `data/profiles.json`, `data/voices.json`, the market file named in the manifest, and every `data/weeks/*.json` listed in the manifest. Copy them into `~/work/site/data/` keeping the same relative paths.

## 2. Free bulk datasets (shell; GitHub raw is reachable)
```
cd ~/work/raw
curl -sSo sp500.csv https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv
curl -sSo constituents-financials.csv https://raw.githubusercontent.com/datasets/s-and-p-500-companies-financials/main/data/constituents-financials.csv
for f in nasdaq nyse amex; do curl -sSo ${f}_full_tickers.json https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/$f/${f}_full_tickers.json; done
```
Set `ASOF` in `run_config.py` to the last US trading day.

## 3. US calendar for the target week
WebFetch `https://www.earningswhispers.com/calendar`, ask for the verbatim nav hrefs, then WebFetch each `/calendar/YYYYMMDD` for Mon–Fri (prompt: "List EVERY company: TICKER|BMO or AMC"). Write `pipeline/ew_week.py` (same shape as before). Drop `T.` (TSX) duplicates.
Cross-check big names: any S&P 500 company that a second calendar lists but EW does not, check it (it may have reported already, been taken private, or moved). Run `python3 make_universe.py`. Classify any new GLOBAL ticker in `knowledge_industries.NON_SPX` and add a Hebrew line to `knowledge_desc.DESC` for every new ticker (build prints `missing desc`).

## 4a. Consensus for the week's largest names (QuarterChart)
WebFetch `https://quarterchart.com/earnings` (prompt: "Output EVERY row of every day table as one line: DAY|TICKER|market cap|EPS estimate|revenue estimate|timing. Exact values verbatim"). Write `pipeline/qc.txt` as `TICKER|mcap|eps|revenue|timing` (map GOOG→GOOGL). build.py uses it as the primary consensus and keeps Yahoo's range/analyst count only when the two agree within 8%. QuarterChart dates/timing are marked unconfirmed there: never use them for dates (EW + company IR decide dates).

## 4b. Consensus for every other company (Earnings Whispers)
For each day page `https://www.earningswhispers.com/calendar/<YYYYMMDD>` ask for the verbatim company hrefs (`https://www.earningswhispers.com/stocks/<T>`) of tickers still missing consensus, then fetch each with: "For the UPCOMING earnings report output exactly one line and nothing else: report_date|quarter|consensus_eps|whisper_eps|revenue_estimate". Delegate in 3–4 parallel subagents (model sonnet) to keep context small. Write `pipeline/ewc.txt` as `TICKER|date|quarter|eps|whisper|revenue`. build.py uses it for names not covered by qc.txt/cons.txt. If EW's report_date differs from the calendar, move the event and add a note.

## 4. Focus list (top ~30 by market cap of the week + all Israeli events)
For each focus ticker:
- **IR announcement** — WebSearch "<company> third quarter <year> results conference call", WebFetch the company/IR/wire page, record in `focus_ir.py`: date, release time, call time **in ET**, webcast URL, source URL, period. If only last quarter's time is known, set `unconfirmedTime=True`.
- **Consensus** — WebFetch `https://finance.yahoo.com/quote/<T>/analysis/` (prompt: one line `quarter|eps_avg|eps_low|eps_high|eps_n|eps_yearago|rev_avg|rev_low|rev_high|rev_n|rev_yearago|rev_growth`) → `cons.txt`. If Yahoo shows "Oops", try MarketBeat `/stocks/<EXCH>/<T>/earnings/` and append `|MB` (flagged low quality). If sources disagree badly, leave it out.
- **Valuation** — WebFetch `https://finance.yahoo.com/quote/<T>/key-statistics/` (one line `mcap|ev|pe|fpe|peg|ps|pb|ev_rev|ev_ebitda|beta|fwd_div`) → `ks.txt`, or StockAnalysis statistics → `val.txt`.
- **Voices** — 1 search per mega-cap for notable investor/CEO commentary in the last ~3 months; add to `knowledge_manual.VOICES` with a one-line Hebrew paraphrase (never long quotes) and the real URL from the search result.
If WebFetch refuses a constructed URL (provenance), WebSearch first with `allowed_domains` so the URL comes from a result. Clear last week's lines from cons/ks/val first.

## 4c. Macro calendar (separate layer → data/macro.json)
Files: `pipeline/macro_us.jsonl`, `pipeline/macro_il.jsonl` (one JSON per line: date, time [ET for US / Israel time for IL], country, cat, imp 1–3, en, he, period, prev, fcst, src, note). Keep a rolling window of ~8 weeks ahead.
Each week: (a) add `actual` to last week's events and refresh `prev` for the coming ones; (b) add consensus (`fcst`) for the next 2 weeks from a reputable source; (c) extend the window and confirm new dates from official calendars (federalreserve.gov, bls.gov, bea.gov, census.gov, ISM, boi.org.il, cbs.gov.il); unconfirmed dates get a note with "לא אומת"/"משוער". Delegate US and Israel to two parallel subagents (model sonnet). Then `python3 build_macro.py` and publish `data/macro.json`.

## 5. Israel (TA-125 / All-Share)
Search announcements (PR Newswire IL, GlobeNewswire, Hebrew press: "מועד פרסום דוחות רבעון", "to report third quarter results"). Add to `knowledge_manual.IL_EVENTS` (keep older entries), with `IL_SECTORS` in `run_config.py` and a Hebrew description for new tickers. Banks/insurers usually announce ~2 weeks ahead.

## 6. Back-fill last week (links only)
For focus companies that reported last week: search the press release, the call replay page and a call transcript; put them in `links.py` keyed by event id `TICKER-YYYY-MM-DD`. Link only — never paste transcript or report text.

## 7. Build, check, publish
```
cd ~/work/pipeline && python3 build.py
```
- Update `run_config.py` first: `TARGET_WEEK`, `WEEK_META` labels/notes (coverage US: full | preview | none).
- Check the printout: event counts, `missing desc: []`.
- Spot-check 3 events in the JSON against sources (date, ET time, consensus).
- Publish with `Artifact` (`url` = artifact URL, `file_path` = `~/work/site/index.html` exactly as downloaded, `files` = the list printed after `PUBLISH THESE FILES`, `root` = `~/work/site`). Do not pass `capabilities` (keeps `downloads`) or `icon`.

## 8. Report
Send the user one short message: weeks covered, how many events, what was verified, anything that could not be verified (with the reason). Per Forte's instruction: if something is uncertain or was wrong last week, say so explicitly.
