# Swimming Competition Results Scraper

**Version:** 2.2.0
**Author:** Swimming Results Team
**Last Updated:** July 2026

---

## Overview

A multi-threaded web scraper that extracts swimming competition results from **myresults.eu** and writes them to a semicolon-delimited CSV file. It runs 20 parallel workers and completes 200 requests in under one second — no browser automation required.

### Key Features

- ✅ **No Chrome / Selenium** — pure HTTP fetch; data is server-side rendered in the HTML
- ✅ **20 parallel workers** — ~200 requests/second via a shared connection-pooled session
- ✅ **Date & Location extraction** — parsed directly from the page header paragraph
- ✅ **Automatic retry** — exponential backoff on network errors
- ✅ **Thread-safe CSV** — dynamic discipline columns, proper locking
- ✅ **Multi-participant input** — unlimited IDs (one per line or comma-separated)
- ✅ **Live result counters** — real-time Saved / Skipped / Errors badges in GUI
- ✅ **Elapsed + ETA display** — progress label shows runtime and estimated time remaining
- ✅ **Input validation** — IDs, event ranges, file paths validated with inline field highlighting
- ✅ **Debug mode** — verbose logging toggle in settings strip
- ✅ **Config file** — all tunable settings in `config.json`
- ✅ **Discipline normalisation** — strips age-group / heat / gender suffixes; keeps only `NNm Stroke`
- ✅ **Fastest time per discipline** — when the same stroke appears under multiple category suffixes, only the best time is kept
- ✅ **CSV sorted by date descending** — newest competition always on top
- ✅ **Discipline columns in canonical order** — Freistil → Brust → Schmetterling → Rücken → Lagen → other; shortest distance first within each stroke

---

## Quick Start

### Prerequisites

- Python 3.10+
- Internet connection to myresults.eu

### Installation

```bash
# 1. Create virtual environment
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install requests customtkinter

# 3. Run
python timescraper_010.py
```

---

## Usage

### GUI

1. Launch: `python timescraper_010.py`
2. Enter one or more **Teilnehmer-IDs** in the text area — one per line or comma-separated (no upper limit)
3. Enter **Start Event Nr.** and **End Event Nr.**
4. Click **💾 Wählen…** to choose the output CSV file
5. Click **🚀 START** — progress bar, elapsed time, and ETA update in real time
6. Watch the **Gespeichert / Übersprungen / Fehler** counters for a live summary
7. Click **🛑 STOP** to cancel at any time
8. Enable **Debug-Modus** in the settings strip at the bottom for verbose log output

### Configuration

All settings live in `config.json` (auto-created on first run):

```json
{
    "performance": {
        "max_workers": 20
    },
    "timeouts": {
        "page_load": 15
    },
    "retry": {
        "max_attempts": 3,
        "delays": [1, 2, 4]
    },
    "translations": {
        "Backstroke": "Rücken",
        "Freestyle": "Freistil"
    }
}
```

---

## Output Format

Semicolon-delimited CSV (`utf-8-sig` encoding for Excel compatibility):

```
Date;Event Name;Location;ID;Name;Year;Club;25m Freistil;50m Freistil;100m Freistil;...;50m Brust;...
24/05/2026;53. Internationales Swimcity Wels Meeting;Welldorado Wels;306991;BLOBNER Vincent;2014;SU MöDLING;...
```

### Static columns

| Column | Content |
|---|---|
| Date | Last day of the competition — `DD/MM/YYYY` |
| Event Name | Full competition name |
| Location | Venue / pool name |
| ID | myresults.eu participant ID |
| Name | `LASTNAME Firstname` |
| Year | Birth year |
| Club | Swim club name |

### Dynamic discipline columns

- One column per unique `NNm Stroke` combination (e.g. `50m Freistil`, `100m Brust`)
- **Column order:** Freistil → Brust → Schmetterling → Rücken → Lagen → other strokes; within each stroke, distances are ascending (25 m, 50 m, 100 m, 200 m, …)
- **Cell value:** fastest valid time in `SS.ss` or `M:SS.ss` format across all heats of that event
- Empty cell = participant did not compete in that discipline at that event
- Relay events (4×…) are automatically excluded

### Row order

Rows are sorted **by date descending** — the most recent competition appears first.

---

## Discipline Normalisation

Race names on myresults.eu follow the pattern `NNm Stroke [optional extras]`, for example:

| Raw name from site | Normalised column |
|---|---|
| `50m Freistil Kinder` | `50m Freistil` |
| `100m Backstroke AK 12` | `100m Rücken` |
| `200m Breaststroke Men Final` | `200m Brust` |
| `100m Butterfly Damen Vorlauf` | `100m Schmetterling` |
| `4x100m Freestyle Relay` | *(skipped — relay)* |

The optional suffix (age group, heat label, gender qualifier) is stripped so that times from different category heats of the same stroke map to one column. When more than one valid time exists for a stroke after this normalisation, the **fastest time** is kept.

---

## Architecture

```
timescraper_010.py
├── load_config()                   # Loads config.json, writes defaults if missing
├── get_http_session()              # Lazily creates shared requests.Session (pool = workers+2)
├── fetch_html(url)                 # Single HTTP GET, returns HTML string or None
├── parse_metadata_from_html()      # Extracts event name / date / location via regex
├── parse_participant_from_html()   # Extracts name / year / club via regex
├── parse_results_from_html()       # Finds "Ergebnisse" section, extracts times per discipline
├── normalize_discipline()          # Strips heat/gender/age/suffix; translates EN→DE; keeps NNm Stroke
├── _sort_discipline_columns()      # Sorts discipline column names by stroke order + distance
├── _sort_key_date_desc()           # Sort key for CSV rows: newest date first
├── save_to_csv()                   # Thread-safe write; re-sorts columns and rows on every save
├── process_single_event()          # Orchestrates fetch → parse → save for one URL
└── ScraperApp (CTk)                # GUI: inputs, progress bar, log textbox, start/stop
```

**Why no Selenium?** myresults.eu pages are fully server-side rendered. All participant and result data is embedded in the initial HTML — no JavaScript execution is needed. A plain `requests.get()` returns the complete page in ~0.15 s vs ~4 s for Chrome startup + render.

---

## Performance

| Metric | Value |
|---|---|
| Requests/second (20 workers) | ~200–220 |
| Latency per request | ~0.15–0.30 s |
| 198 requests (66 events × 3 IDs) | **0.93 s** |
| Old Selenium version (4 workers) | ~660 s estimated |
| Speedup | **~700×** |

---

## Testing

### Verified Test Data

```
Events:       2285–2350  (66 events)
Participants: 306991 (BLOBNER Vincent), 307558 (RIPA Matthias), 307554 (NéMETH Melina)
Tasks:        198
Results:      29 rows found, 0 errors
Time:         0.93 s
```

### Running Tests

```bash
# Syntax check
python3 -m py_compile timescraper_010.py

# Functional test (headless, no GUI)
python3 -c "
import sys; sys.path.insert(0,'.')
import timescraper_010 as s
html = s.fetch_html('https://myresults.eu/de-AT/Meets/Recent/2341/Participant/306991')
meta = s.parse_metadata_from_html(html, 2341)
name, year, club = s.parse_participant_from_html(html)
results = s.parse_results_from_html(html)
assert meta['event'] == '53. Internationales Swimcity Wels Meeting'
assert name == 'BLOBNER Vincent'
assert len(results) > 0
# All discipline keys must be exactly 2 tokens (NNm Stroke)
for k in results:
    assert len(k.split()) <= 2, f'Unexpected suffix in: {k!r}'
print('✅ OK')
"
```

---

## Project Structure

```
MyResult/
├── timescraper_010.py   # Main application (v2.2.0)
├── config.json          # Runtime configuration
├── README.md            # This file
├── AGENTS.md            # AI agent rules
├── venv/                # Python virtual environment
├── docs/                # Extra documentation
└── .bob/                # Bob AI assistant config
```

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `No module named '_tkinter'` | `brew install python-tk` (macOS) or `sudo apt install python3-tk` |
| `No module named 'requests'` | `pip install requests` in the venv |
| `File is not writable` | Close Excel if the CSV is open |
| Empty results for an event | Participant was not registered at that event — expected behaviour |
| Many "Unknown" names | Event IDs outside the participant's competition history |
| Discipline appears twice in columns | Should not happen in v2.2.0 — all suffixes are stripped before column assignment |

### Debug Mode

Check **Debug Mode** in the GUI to enable `logging.DEBUG` output — all fetch URLs, regex match results, and time extractions are logged to `scraper_YYYYMMDD_HHMMSS.log`.

---

## Version History

### v2.2.0 — July 2026 — result data quality & CSV structure
- **Discipline suffix stripping** — race names like `50m Freistil Kinder` are normalised to `50m Freistil`; age-group labels, heat labels, gender qualifiers after the stroke name are all dropped
- **Fastest-time merging** — when normalisation collapses multiple raw discipline names to the same column key, only the fastest time is kept (existing logic, now fully exercised)
- **CSV sorted by date descending** — every save re-sorts all rows so the most recent competition is always first
- **Discipline columns in canonical order** — columns are re-ordered on every save: Freistil → Brust → Schmetterling → Rücken → Lagen → other; shortest distance first within each stroke

### v2.1.0 — June 23, 2026 — GUI usability improvements
- **Multi-ID input** — unlimited participant IDs in a single text area (one per line or comma-separated); replaces the two fixed ID fields
- **Live result counters** — three badges (Gespeichert / Übersprungen / Fehler) update atomically as each task completes
- **Elapsed + ETA timer** — progress label now shows real elapsed time and estimated remaining time based on live throughput
- **Field-level validation highlighting** — invalid entries get a red border on START; valid ones turn green; event range fields validated live on focus-out
- **Debug checkbox relocated** — moved from inside the form to a dedicated settings strip at the bottom of the window
- **Resizable window** — default height increased to 740 px; log textbox expands when the window is resized vertically

### v2.0.0 — June 23, 2026 — requests rewrite ✨
- **Replaced Selenium/Chrome with `requests` + regex** — no browser dependency
- 20 parallel workers (was 4) via a shared connection-pooled `requests.Session`
- ~700× faster: 0.93 s for 198 requests (was ~660 s with Chrome)
- Metadata (event name, date, location) parsed from HTML header paragraph — no extra HTTP round-trip
- Removed all Selenium, ChromeDriver, and browser-automation code

### v1.3.3 — June 11, 2026 — performance tuned
- 54% faster than v1.3.2 via hybrid wait (fixed delay + WebDriverWait)

### v1.3.2 — June 11, 2026 — date/location fixed
- Date and location extraction at 100% success rate via participant page pattern

### v1.0.0 — June 2026 — initial production release
- Multi-threaded Selenium scraper with CustomTkinter GUI

---

## Dependencies

| Package | Purpose |
|---|---|
| `requests` | HTTP fetching with connection pooling |
| `customtkinter` | Modern GUI framework |
| `urllib3` | Connection pool + retry (bundled with requests) |

---

## License

Internal use. All rights reserved.
