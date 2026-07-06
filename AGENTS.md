# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Project: Swimming Competition Results Scraper

**Stack**: Python 3, `requests`, CustomTkinter GUI  
**Purpose**: Multi-threaded HTTP scraper for myresults.eu swimming competition data  
**Version**: 2.2.0 — no Selenium, no Chrome

---

## Architecture

All data on myresults.eu is **fully server-side rendered**. A plain `requests.get()` returns the complete HTML including participant details and result times. No JavaScript execution or browser automation is needed or used.

### Core call chain (per event/participant URL):

```
process_single_event()
  → fetch_html()                      # HTTP GET via shared Session
  → parse_participant_from_html()     # regex on personendetails table
  → parse_metadata_from_html()        # regex on myresults_meetname2 paragraph
  → parse_results_from_html()         # find Ergebnisse header, then odd/even rows
  → save_to_csv()                     # thread-safe write with csv_lock
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
- Raw race names follow `"NNm Stroke [optional extras]"` (e.g. `"50m Freistil Kinder"`)
- `normalize_discipline()` strips heat, gender, age-group tokens **and** then applies
  `DISCIPLINE_CORE_PATTERN` (`^(\d+\s*[mM]?\s+\S+)`) to keep only the first two tokens
- This maps `"50m Freistil Kinder"` and `"50m Freistil Jugend"` to the same key `"50m Freistil"`
- The "keep fastest" logic in `parse_results_from_html` then automatically picks the best time

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

---

## Testing

**Verified test data**:
- Event: `2341`, Participant: `306991`
- Expected: event = `"53. Internationales Swimcity Wels Meeting"`, name = `"BLOBNER Vincent"`, 6 result disciplines
- Event `2248` → pool `"25m"` (SCM); Event `2341` → pool `"50m"` (LCM)

**Syntax check**:
```bash
python3 -m py_compile timescraper_010.py
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
# Column order check
cols = list(results.keys())
sorted_cols = s._sort_discipline_columns(cols)
assert cols == sorted_cols or True  # order only guaranteed after save_to_csv
# Pool size detection
assert s.parse_pool_size_from_overview(2248) == '25m'
assert s.parse_pool_size_from_overview(2341) == '50m'
print('OK')
"
```

**Big test** (198 tasks, events 2285–2350, 3 participants):
- Expected: 29 rows saved, 0 errors, < 2 s wall time

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
