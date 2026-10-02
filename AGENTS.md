# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Project: Swimming Competition Results Scraper

**Stack**: Python 3, `requests`, CustomTkinter GUI  
**Purpose**: Multi-threaded HTTP scraper for myresults.eu swimming competition data  
**Version**: 2.4.0 — no Selenium, no Chrome

---

## Architecture

All data on myresults.eu is **fully server-side rendered**. A plain `requests.get()` returns the complete HTML including participant details and result times. No JavaScript execution or browser automation is needed or used.

### Core call chain (per event/participant URL):

```
process_single_event()
  → fetch_html()                        # HTTP GET via shared Session
  → parse_participant_from_html()       # regex on personendetails table
  → parse_metadata_from_html()          # regex on myresults_meetname2 paragraph
  → parse_pool_size_from_overview()     # HTTP GET to /Overview; parses "Bad" field
  → parse_results_from_html()           # find Ergebnisse header, then odd/even rows
  → save_to_csv()                       # thread-safe write with csv_lock
```

---

## Non-Obvious Patterns

### HTTP Session (shared across all threads)
- `get_http_session()` lazily creates one `requests.Session` with `pool_maxsize = MAX_WORKERS + 2`
- **MUST NOT** create per-thread sessions — defeats connection reuse
- `reset_http_session()` is called on STOP to close all pooled connections

### Metadata Extraction
- Event name / date / location come from the `myresults_meetname2` paragraph in the HTML header
- Pattern: `"EventName (DD.MM.YYYY - DD.MM.YYYY) - Location"`
- Fallback: `myresults_nav3a` `<p>` tag
- Results are cached in `event_metadata_cache` (keyed by event_id) — no second fetch needed
- **Parentheses in event names**: Some events contain `(Word)` inside the name itself, e.g.
  `"11. Ottokar Havlik Memorial (Jugendkriterium) (02.-03.04.2011) - Schwechat"`.
  The metadata regex must anchor on the **date parenthesis** specifically:
  `r'^(.*?)\s*\((\d{1,2}\.[-.\d]*\d{4})\)\s*-\s*(.*)$'`
  This requires the captured group to start with a digit+dot, skipping word-only parentheticals.

### Results Section Detection
- `ERGEBNISSE_HEADER_PATTERN` locates the `<div>` with "Ergebnisse" text
- Only HTML **after** that match is parsed — avoids false matches in "Starts" section
- Row splits on `myresults_content_divtablerow_odd` / `_even` classes

### Time Extraction
- Times are in `<div class="hidden-xs … myresults_content_divtable_right">` (NOT the points column)
- `TIME_COL_PATTERN` matches only the first right-aligned column without "points" in the class string
- `validate_time_format()` rejects values that don't match `SS.ss` or `M:SS.ss`
- Keeps **fastest** time when the same discipline appears in multiple heats

### Relay Events
- `normalize_discipline()` returns `None` if `"4x"` appears anywhere in the raw name
- Caller (`parse_results_from_html`) checks for `None` and skips the row

### Discipline Normalisation
- Raw race names from historical events include heat/gender/round prefixes:
  `"1 - 100m Brust Damen Vorlauf"`, `"50m Freestyle Men Final"`, etc.
- `normalize_discipline()` (in `timescraper_010.py`) and `_normalize_discipline()` (in
  `generate_sum_report.py`) apply the same pipeline:
  1. Return `None` for relay events (contains `"4x"`)
  2. Strip leading `"N - "` prefix (`PREFIX_PATTERN`)
  3. Strip gender tokens: Men/Women/Mixed/Herren/Damen/männlich/weiblich/Frauen/Männer
  4. Strip heat tokens: Vorlauf/Preliminary/Heats/Entscheidung/Lauf N
  5. Strip final tokens: Final/Finale/A-Final/B-Final
  6. Strip age tokens: `AK\d+.*`, `und jünger`
  7. Translate EN→DE stroke names (Freestyle→Freistil, Backstroke→Rücken, etc.)
  8. Apply `DISCIPLINE_CORE_PATTERN` (`^(\d+\s*[mM]?\s+\S+)`) — keeps only distance + stroke
- Result: `"1 - 100m Brust Damen Vorlauf"` → `"100m Brust"`, `"50m Freestyle Men Final"` → `"50m Freistil"`
- After normalisation, dedup per `(swimmer_id, event_id, discipline)` keeps the fastest time

### Pool Size Detection
- `parse_pool_size_from_overview(event_id)` fetches `https://myresults.eu/de-AT/Meets/Recent/{event}/Overview`
- Parses the **"Bad"** field: text like `"25m (SCM) Hallenbad"` or `"50m (LCM) Freibad"`
- `POOL_SIZE_PATTERN` matches the leading `\d+m` token before the `<span …>Bad<` label
- Returns `"25m"` or `"50m"` (lowercase); defaults to `"50m"` if the page or field is missing
- Result is cached in `event_metadata_cache[event_id]["pool"]` — only one Overview fetch per event across all threads
- Called from `process_single_event()` after metadata is resolved; stored as `meta["pool"]`

### CSV Thread Safety
- **ALWAYS** acquire `csv_lock` before reading or writing the CSV
- File is **always** fully re-written on every save (never appended to)
- Static columns (8): `Date`, `Event Name`, `Location`, `ID`, `Name`, `Year`, `Club`, **`Pool`**
- Discipline columns are re-sorted on every write: Freistil → Brust → Schmetterling → Rücken → Lagen → other; distance ascending within each stroke (`_sort_discipline_columns`)
- All existing rows are rebuilt via header→value map to track column reordering correctly
- Data rows are sorted by date descending (`_sort_key_date_desc`) before writing
- Delimiter is `;` (semicolon), encoding is `utf-8-sig` (BOM for Excel)

### stop_scraping Flag
- Global `bool`; set to `True` by `stop_process()` / STOP button
- Checked at the start of `process_single_event()` and inside the retry loop
- `reset_http_session()` is called concurrently to abort in-flight connections

### Season / Multi-Event & Medal Reports (Club Scraper)
- Script: `generate_sum_report.py`
- **Two modes**:
  - `python3 generate_sum_report.py` (default `recent`): scans events 2000–2459, date-filtered
    01/2025–08/2026 → `SUM_Ergebnisse_2025_2026_Alle.csv` + `SUM_Medaillen_2025_2026.csv`
  - `python3 generate_sum_report.py --mode history`: scans events 504–2460, **no date filter**
    → `SUM_Ergebnisse_2010_2026_Alle.csv` — full Club 6614 history (mid-2010 to present)
- **Both modes produce the same enriched schema**:
  `event_id | swimmer_id | date | event_name | location | name | birth_year | club | pool |`
  `discipline | time_str | time_sec | place | medal | age_group`
- **Club-First URL Discovery**: `https://myresults.eu/de-AT/Meets/Recent/{event_id}/Club/{club_id}`
- **3-phase execution**: (1) scan club pages → (2) fetch pool sizes → (3) fetch participant pages
- **Strict validation** (both modes):
  - Drop blank / `"Unknown"` / `"Unbekannt"` swimmer names
  - Drop relay teams: name matches `MANNSCHAFT|STAFFEL`, or discipline contains `4x`
  - Drop blank / `"Unknown"` event names
  - Drop rows where time doesn't match `^[0-5]?\d:[0-5]\d\.\d{2}$|^[0-5]\d\.\d{2}$`
  - Post-normalisation dedup: keep fastest time per `(swimmer_id, event_id, discipline)`
- **Historical Data Availability (myresults.eu Archive Analysis)**:
  - **Club ID `6614`**: 401 events found (IDs 504–2460), 7,252 participant pages, 25,520 clean rows
    after normalisation and dedup. Verified: 29 unique canonical disciplines, 0 bad dates, 0 Unknown entries.
  - **Legacy Club ID `1678`**: covers 10/2000–06/2010 if pre-2010 history is ever needed
- **Placements & Medals**:
  - Placements are in `<span class="msecm-place...">` (e.g., `1.`, `2.`, `3.`)
  - Medals: classes `msecm-place-gold`, `msecm-place-silver`, `msecm-place-bronze`
- **Age Categories / Altersklasse**:
  - Found in `<span class="myresults_content_divtable_details_black">` within result rows

---

## Testing

**Verified test data**:
- Event: `2341`, Participant: `306991`
- Expected: event = `"53. Internationales Swimcity Wels Meeting"`, name = `"BLOBNER Vincent"`, 6 result disciplines
- Event `2248` → pool `"25m"` (SCM); Event `2341` → pool `"50m"` (LCM)

**Syntax check**:
```bash
python3 -m py_compile timescraper_010.py
python3 -m py_compile generate_sum_report.py
python3 -m py_compile streamlit-dashboard/i18n.py
python3 -m py_compile streamlit-dashboard/views/swimmer.py
python3 -m py_compile streamlit-dashboard/views/leaderboard.py
python3 -m py_compile streamlit-dashboard/views/team_overview.py
python3 -m py_compile streamlit-dashboard/views/recent.py
python3 -m py_compile streamlit-dashboard/views/medals.py
```

**Functional test** (no GUI, no display needed):
```bash
python3 -c "
import sys; sys.path.insert(0,'.')
import timescraper_010 as s
html = s.fetch_html('https://myresults.eu/de-AT/Meets/Recent/2341/Participant/306991')
assert s.parse_metadata_from_html(html, 2341)['event'] == '53. Internationales Swimcity Wels Meeting'
name, _, _ = s.parse_participant_from_html(html)
assert name == 'BLOBNER Vincent'
results = s.parse_results_from_html(html)
assert len(results) == 6
# All keys must be 'NNm Stroke' — no trailing suffixes
for k in results:
    assert len(k.split()) <= 2, f'Unexpected suffix in discipline key: {k!r}'
# Pool size detection
assert s.parse_pool_size_from_overview(2248) == '25m'
assert s.parse_pool_size_from_overview(2341) == '50m'
print('OK')
"
```

**i18n + search unit test**:
```bash
python3 -c "
import sys; sys.path.insert(0, 'streamlit-dashboard')
from i18n import t, format_discipline

# Placeholders
assert t('search_placeholder', 'de') == 'z.B. Max Mustermann'
assert t('search_placeholder', 'en') == 'e.g. Alex Smith'

# Dual date keys
assert t('filter_date_from', 'de') == 'Von'
assert t('filter_date_to',   'en') == 'To'

# Discipline translations
assert format_discipline('50m Freistil',       'en') == '50m Freestyle'
assert format_discipline('100m Schmetterling', 'en') == '100m Butterfly'
assert format_discipline('400m Lagen',         'en') == '400m Medley'
assert format_discipline('50m Freistil',       'de') == '50m Freistil'
print('OK')
"
```

**generate_sum_report validation test**:
```bash
python3 -c "
import generate_sum_report as g, datetime
assert g.is_valid_swimmer('BLOBNER Vincent')
assert not g.is_valid_swimmer('Unknown')
assert not g.is_valid_swimmer('1. MANNSCHAFT')
assert g.time_to_seconds('30.45') == 30.45
assert g.time_to_seconds('99:00.00') is None
assert g._normalize_discipline('1 - 100m Brust Damen Vorlauf') == '100m Brust'
assert g._normalize_discipline('4x100m Freistil') is None
assert g.parse_date_str('01.-02.04.2017') == datetime.date(2017, 4, 2)
assert g.parse_date_str('11. Ottokar Havlik Memorial (Jugendkriterium) (02.-03.04.2011) - Schwechat') is None  # not a date string
print('OK')
"
```

---

## GAS / Google Sheets

### Events sheet column layout
- Columns A–G: `event_id | event_name | date | location | last_updated | modling_participant_count | pool`
- Column G (`pool`) was added in v2.3.0 — **header `pool` must be in cell G1** (add once manually)
- `upsertEvent(id, name, date, location, modlingCount, pool)` — 6th arg is optional; keeps existing value if omitted
- `loadEventsCache()` reads 7 columns and exposes `pool` key; falls back to `"50m"` for blank cells
- `backfillPoolSize()` in `Sheets.gs` — one-shot backfill for pre-existing rows; skips rows already set; respects 5-min GAS time budget; safe to re-run
- GAS does **not** auto-sync from GitHub — any new functions must be pasted into the Apps Script editor manually

### Results sheet column layout (v2.4+)
- Columns A–G: `event_id | swimmer_id | discipline | time_str | time_sec | fetched_at | source`
- Columns H–J: `place | medal | age_group`
- Older rows without H–J are safe — `load_results()` and `load_medals()` fill in empty strings
- **Header row must include `place`, `medal`, `age_group` in cells H1–J1**

### Direct Python → Sheets batch uploader (`upload_history_to_sheets.py`)
Replaces the old GAS chunk-paste workflow for large backfills.

```bash
# Dry-run (validate only, no writes):
streamlit-dashboard/.venv/bin/python3 upload_history_to_sheets.py --dry-run

# Live upload:
streamlit-dashboard/.venv/bin/python3 upload_history_to_sheets.py

# Custom CSV path:
streamlit-dashboard/.venv/bin/python3 upload_history_to_sheets.py --csv SUM_Ergebnisse_2010_2026_Alle.csv
```

- Reads `oauth_token.json` (produced by `generate_streamlit_token.py`); auto-refreshes if expired
- Pre-upload validation: skips rows with blank/Unknown name or event_name
- Deduplicates against existing sheet rows using composite key `(event_id, swimmer_id, discipline)`
  and keeps the fastest time within the CSV itself
- Batch-appends in chunks of 2,000 rows to avoid API payload limits
- Writes Events (A–G), Swimmers (A–D), Results (A–J)
- **Completed backfill (2010–2026)**: 25,520 rows → 472 Events, 411 Swimmers, 25,520 Results in SwimmingResults_DB
- **Date normalisation**: raw date strings from the CSV (e.g. `"01.-02.04.2017"`) are converted to
  `DD/MM/YYYY` by `_normalise_date()` before writing to the Events sheet. Existing rows are never
  re-written by the uploader (dedup by event_id skips them).

### One-shot date patch (`patch_event_dates.py`)
Fixes Events rows that were uploaded before the date normalisation fix — converts any non-`DD/MM/YYYY`
date in column C to the correct format in a single batch API call.

```bash
# Dry-run (preview only):
streamlit-dashboard/.venv/bin/python3 patch_event_dates.py --dry-run

# Live patch:
streamlit-dashboard/.venv/bin/python3 patch_event_dates.py
```

- Safe to re-run — rows already in `DD/MM/YYYY` format are skipped
- Reads `oauth_token.json` for auth (same as uploader)
- After patching, wait up to 5 minutes for the Streamlit cache TTL to expire (or rerun the app)

### Streamlit deployment
- Streamlit Cloud watches the **`feature/google-workspace-migration`** branch, **not** `main`
- Merge flow: feature branch → `feature/google-workspace-migration` → push (Streamlit auto-redeploys)
- For `main`: merge separately when ready for a formal release
- The Apps Script project is a separate copy; GitHub pushes do not update it automatically

### Local Streamlit development
```bash
cd streamlit-dashboard
.venv/bin/streamlit run app.py
```
- The `.venv` is inside `streamlit-dashboard/` — create once with:
  `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
- Secrets: `streamlit-dashboard/.streamlit/secrets.toml` (gitignored) — copy from
  `oauth_token.json` into the `[gcp_oauth_token]` TOML block (see `secrets.toml.example`)

---

## Streamlit Dashboard

### i18n (`streamlit-dashboard/i18n.py`)
- All UI strings in `STRINGS["de"]` and `STRINGS["en"]` dicts; retrieved via `t(key, lang)`
- `format_discipline(disc, lang) -> str` — display-only translation of canonical German discipline
  strings to English: Freistil→Freestyle, Brust→Breaststroke, Schmetterling→Butterfly,
  Rücken→Backstroke, Lagen→Medley. Returns the string unchanged in DE mode.
  **The canonical German key in the dataframe is never modified — only the display label.**

### Discipline display pattern (views)
- Always build a `disc_label_to_key = {format_discipline(d, lang): d for d in disciplines}` map
  when disciplines are shown in a dropdown or selectbox, so the translated label can be resolved
  back to the canonical German key for dataframe filtering.
- Use `format_discipline(d, lang)` for tab labels, chart y-axes, and table column headers.
- Filter the dataframe using the canonical German key, never the display label.

### Swimmer search (order-agnostic)
- All query tokens must appear in the swimmer name (case-insensitive), in any order:
  `all(tok in name.lower() for tok in query.lower().split())`
- "Vincent Blobner", "blobner vincent", "BLOBNER" all find "BLOBNER Vincent"

### Date filters (Von / Bis)
- All views (Swimmer, Leaderboard, Team Overview, Medals) use **two separate `st.date_input`
  widgets** (keys `filter_date_from` / `filter_date_to` in i18n) instead of a tuple-returning
  range picker. Guard: only apply filter when `date_from <= date_to`.

### Event date parsing (`streamlit-dashboard/data.py`)
- `load_events()` uses `_parse_event_date_series()` instead of a strict `pd.to_datetime(format=…)` call.
- Handles **both** date formats found in the Events sheet:
  - `"DD/MM/YYYY"` — produced by GAS `parseLastDate()` and current uploader
  - Raw range strings — e.g. `"01.-02.04.2017"`, `"28.02.-01.03.2025"` — written by the
    historical backfill before the normalisation fix was applied
- Strategy: try `%d/%m/%Y` then `%d.%m.%Y`; fall back to regex extraction of the last
  `dd.mm.yyyy` occurrence in the string (= event end date). Returns `NaT` only if no
  date digits are found at all.
- **Root cause of the pre-2025 date picker bug**: the old strict parser silently coerced all
  range-style dates to `NaT`, so `min_d` was never earlier than the first GAS-uploaded event.
  Fixed by `_parse_event_date_series()` + the one-shot `patch_event_dates.py` sheet fix.

### Manual sheet edits — persistence rules
- **Event name / date / location**: GAS `upsertEvent()` overwrites these fields on the next
  nightly run if the scraped value is non-blank and non-`"Unknown"`. Edits to recent events
  may be lost; edits to historical events (outside the nightly scan window) are permanent.
- **Pool size** (column G): never overwritten by GAS if already set (`pool || row[6]`).
  Manual corrections to pool size are **always persistent**.
- **Swim times / Results rows**: `appendResults()` only appends — it never updates existing rows.
  The nightly scraper skips any `(event_id, swimmer_id)` pair already in the sheet (skip set).
  Manual time edits are **persistent** unless a `Rescan_Queue` entry is added for that
  swimmer+event, which triggers `deleteResults()` and a full re-fetch.

---

## Git Workflow

- **NEVER** commit directly to `main`
- Before making changes, create or switch to a dedicated branch
- Use branch prefixes based on change type:
  - `feature/<short-description>` for new functionality
  - `fix/<short-description>` for bug fixes
  - `chore/<short-description>` for maintenance, config, docs, and tooling changes
- Keep branch names short, lowercase, and hyphenated
- Example branch names:
  - `feature/csv-export-options`
  - `fix/metadata-location-parse`
  - `chore/update-gitignore`

---

## Code Style (Project-Specific)

- German UI strings and log messages (intentional — German-speaking users)
- English docstrings and inline comments for code logic
- Global state only for `stop_scraping` flag (thread coordination) and `_http_session`
- Log files: `scraper_YYYYMMDD_HHMMSS.log` written to the working directory
- `Optional[str]` return convention: `None` means "not found / skip"
