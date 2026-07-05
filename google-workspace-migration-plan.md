# Google Workspace Migration Plan
## Swimming Competition Results Scraper → Google Apps Script + Sheets + Streamlit

**Status:** Draft — pending implementation  
**Source version:** timescraper_010.py v2.2.0  
**Target:** Google Apps Script (V8) + Google Sheets + Streamlit Community Cloud  
**Licence tier:** Google Workspace for Nonprofits (free) + Streamlit Community Cloud (free)

---

## Overview

The current tool is a desktop Python application that writes results to a local CSV file.
This plan migrates everything to Google's cloud with a public Streamlit dashboard.

The system has **two distinct data-acquisition paths**:

### Path A — Live / ongoing (automated nightly)
The myresults.eu "Recent" page lists the **100 most recent competitions** (currently
event IDs 2163–2391, all with published results). Every competition has a dedicated
`/de-AT/Meets/Recent/{event_id}/Club/6614` page that lists only **SU MöDLING**
participants (club ID 6614, fixed across all events). The nightly script:
1. Fetches the Recent page and extracts all currently listed event IDs with their dates.
2. For each event not already in the Events tab, fetches the club page and collects
   participant IDs for SU MöDLING (club 6614).
3. For each `(event_id, participant_id)` pair not already in Results, fetches and
   parses the individual participant page.
4. Writes metadata, swimmer info, and result times to Sheets.

No static swimmer registry is needed — new team members appear automatically as soon
as they compete and their club page shows them.

### Path B — Historic CSV import (deferred)
Historical CSV files in the format produced by `timescraper_010.py` can be bulk-imported
into the Sheets workbook at any future point. This will be **designed now but implemented
later** — the import format is documented in the Data Model section, and a dedicated
import function will be added to the Apps Script project.

### Key facts from live site investigation (07/2025)

| Fact | Value |
|---|---|
| Recent page URL | `https://myresults.eu/de-AT/Meets/Recent` |
| Events listed | 100 competitions (IDs 2163–2391 on last check) |
| Events with published results | 97 of 100 |
| SU MöDLING club ID | **6614** (stable across all events) |
| Club page URL pattern | `/de-AT/Meets/Recent/{event_id}/Club/6614` |
| Participant page URL | `/de-AT/Meets/Recent/{event_id}/Participant/{participant_id}` |
| Participants page | AJAX-rendered — not parseable with plain GET |
| Results page | Server-side rendered — contains club links with IDs |

### Scope

| In scope | Out of scope |
|---|---|
| GAS scraper — club-first discovery (Path A) | Looker Studio |
| Sheets data model (6 tabs) | Email / Chat notifications (optional later) |
| Historic CSV import function (Path B, designed now, implemented later) | Mobile native app |
| Nightly trigger | Custom authentication / access control |
| Streamlit dashboard (public, single unified area) | Changes to scraping logic beyond porting |

### Non-goals

- The Python desktop tool is **not deleted** during this migration; it runs in parallel
  until the GAS version is validated.
- No historic data is imported on initial launch. The import function is designed and
  ready but activated only when Martin provides the CSV files.
- No manual swimmer registration form is needed — team members are discovered automatically
  from the SU MöDLING club page.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Google (free for Nonprofits)                                           │
│                                                                         │
│  ┌──────────────────────┐    R/W    ┌──────────────────────────────┐   │
│  │  Apps Script project  │ ────────▶│  Google Sheets workbook      │   │
│  │  (Martin's account)   │          │  (Martin's Google Drive)     │   │
│  │                       │          │                              │   │
│  │  Code.gs    main()    │          │  Tab: Swimmers               │   │
│  │  Config.gs            │          │  Tab: Events                 │   │
│  │  Fetch.gs             │          │  Tab: Results                │   │
│  │  Parser.gs            │          │  Tab: Rescan_Queue           │   │
│  │  Sheets.gs            │          │  Tab: Config                 │   │
│  │  Import.gs            │          │  Tab: Log                    │   │
│  │                       │          └──────────────────────────────┘   │
│  └──────────┬────────────┘                    ▲                        │
│             │  UrlFetchApp.fetchAll()          │ gspread (read-only)    │
└─────────────┼──────────────────────────────────┼────────────────────────┘
              │                                   │
              ▼                        ┌──────────┴─────────┐
       myresults.eu                    │  Streamlit app      │
       (/Meets/Recent)                 │  Community Cloud    │
       (/Club/6614 per event)          │  (public URL)       │
       (/Participant/ID per swimmer)   └─────────────────────┘
                                               ▲
                  Nightly data flow:    anyone with the link
                  1. Fetch Recent page → event IDs
                  2. Fetch Club/6614   → participant IDs
                  3. Fetch Participant → times + metadata
```

### Where each component lives

| Component | Hosted / stored where | Managed by |
|---|---|---|
| Scraper code (6 `.gs` files) | Google Apps Script — Google's servers | Developer edits at script.google.com |
| Sheets workbook | Martin Stegmayer's Google Drive (Workspace for Nonprofits) | Martin as admin |
| Config values | "Config" tab | Martin edits cells directly |
| Known swimmers | "Swimmers" tab | Auto-discovered from Club/6614 page; no manual entry needed |
| Event metadata cache | "Events" tab | Auto-populated; never re-fetched |
| Raw results | "Results" tab | Written by script |
| Force-rescan queue | "Rescan_Queue" tab | Admin-editable for edge cases |
| Execution log | "Log" tab | Written after every run |
| Nightly scheduler | Apps Script time-based trigger | Set up once by developer |
| Dashboard | Streamlit Community Cloud (public URL) | Developer deploys from GitHub repo |

---

## Data Model (Google Sheets — 6 tabs)

### Tab 1 — Swimmers

| Column | Type | Description |
|---|---|---|
| `swimmer_id` | String (PK) | myresults.eu participant ID |
| `name` | String | `LASTNAME Firstname` — filled on first successful scrape |
| `birth_year` | String | 4-digit year — filled on first successful scrape |
| `club` | String | `SU MöDLING` (or as scraped — AUT suffix stripped) |
| `first_seen_event_id` | Integer | Event ID where swimmer was first discovered via Club page |
| `last_updated` | Timestamp | ISO datetime of last successful fetch |

One row per known SU MöDLING swimmer. Created automatically the first time a swimmer
appears on the `/Club/6614` page for any event. `name`, `birth_year`, `club` are filled
by the first individual participant-page fetch.

**No manual registration form is needed.** New team members appear automatically.

### Tab 2 — Events

| Column | Type | Description |
|---|---|---|
| `event_id` | Integer (PK) | myresults.eu event number |
| `event_name` | String | Full competition name |
| `date` | String | `DD/MM/YYYY` (last day of competition) |
| `location` | String | Venue / pool name |
| `last_updated` | Timestamp | ISO datetime last metadata was verified |
| `modling_participant_count` | Integer | Number of SU MöDLING swimmers at this event |

One row per known event. Before any HTTP fetch the script looks up `event_id` here — if
found, metadata is reused without a network call.

The `modling_participant_count` value is set when the Club/6614 page is parsed. An event
with count = 0 means no SU MöDLING swimmers competed (still logged to avoid re-checking).

### Tab 3 — Results (normalised)

| Column | Type | Description |
|---|---|---|
| `event_id` | Integer (FK → Events) | |
| `swimmer_id` | String (FK → Swimmers) | |
| `discipline` | String | Normalised `NNm Stroke` key (e.g. `50m Freistil`) |
| `time_str` | String | `SS.ss` or `M:SS.ss` |
| `time_sec` | Float | Numeric seconds (for sorting / personal-best logic) |
| `fetched_at` | Timestamp | When this row was written |
| `source` | String | `"scraper"` or `"csv_import"` (Path A vs Path B) |

Composite unique key: `(event_id, swimmer_id, discipline)`.

**Skip logic:** before building the URL batch, the script reads all `(event_id, swimmer_id)`
pairs from this tab into a JS `Set`. Any pair already present is skipped — no HTTP request
is made for it.

**CSV import rows** set `source = "csv_import"` so they are identifiable and can be
re-verified or corrected independently.

### Tab 4 — Rescan_Queue

| Column | Type | Description |
|---|---|---|
| `swimmer_id` | String | Participant to rescan |
| `rescan_start` | Integer | Start event ID for rescan |
| `rescan_end` | Integer | End event ID for rescan |
| `status` | String | `pending` → `processing` → `done` |
| `submitted_at` | Timestamp | When the row was added |

Used for admin edge cases only (e.g. correcting a bad scrape). Rows are written manually
by Martin or via a simple admin script. The nightly `main()` processes all `pending` rows,
deletes matching Results rows for the swimmer+range, re-scrapes, then marks rows `done`.

### Tab 5 — Config

| Column A (key) | Column B (value) | Notes |
|---|---|---|
| `club_id` | `6614` | SU MöDLING club ID on myresults.eu — do not change |
| `club_name_match` | `SU MöDLING` | String used to verify club identity in HTML |
| `max_parallel` | `100` | UrlFetchApp.fetchAll batch size |
| `page_timeout` | `15` | HTTP timeout in seconds |
| `max_retries` | `3` | Retry attempts per URL |
| `retry_delays` | `1,2,4` | Comma-separated backoff seconds |
| `translation_Backstroke` | `Rücken` | One row per EN→DE stroke translation |
| `translation_Breaststroke` | `Brust` | |
| `translation_Butterfly` | `Schmetterling` | |
| `translation_Freestyle` | `Freistil` | |
| `translation_Ind. Medley` | `Lagen` | |
| `translation_Medley` | `Lagen` | |
| `translation_Free` | `Freistil` | |

Note: There is no `global_event_end` — the Recent page is the authoritative source of
which events exist and have published results. The script always reads from the live page.

### Tab 6 — Log

| Column | Type | Description |
|---|---|---|
| `run_at` | Timestamp | When the run started |
| `events_checked` | Integer | Events pulled from Recent page |
| `events_new` | Integer | Events not previously in Events tab |
| `swimmers_discovered` | Integer | New swimmer rows added to Swimmers tab |
| `results_added` | Integer | New result rows written |
| `results_skipped` | Integer | Tasks skipped (already in Results) |
| `errors` | Integer | Failed HTTP fetches |
| `rescans` | Integer | Force-rescan tasks processed |
| `duration_sec` | Float | Total execution time |
| `notes` | String | Any warnings or special events |

One row appended per run. Never deleted. Provides full audit trail.

---

## Automated Setup (Credential Hand-Off)

Approximately 85% of the initial setup can be fully scripted once credentials are provided.
The **one unavoidable manual step** is Martin clicking "Allow" in the Google OAuth consent
dialog — this cannot be automated by policy.

### What can be automated (with credentials)

| Task | How |
|---|---|
| Create `SwimmingResults_DB` Sheets workbook | Google Sheets API `spreadsheets.create` |
| Create all 6 tabs + column headers | Sheets API `batchUpdate` |
| Write all `.gs` files to Apps Script project | Apps Script API `projects.create` + `projects.updateContent` |
| Push Streamlit app code to GitHub | `git push` with GitHub token |
| Deploy to Streamlit Community Cloud | Auto-deploy on push (Community Cloud watches the repo) |
| Store Streamlit secrets | Streamlit CLI or Community Cloud UI |
| Run `setupTrigger()` to register the nightly cron | GAS execution API (after OAuth is granted) |

### What requires Martin to act manually (once only)

1. **OAuth consent** — open any GAS function in the editor and click "Allow" in the
   permission dialog. This binds execution credentials to Martin's account.
2. **Verify trigger** — open the Apps Script Triggers dashboard (⏰) and confirm one
   trigger is listed after `setupTrigger()` runs.

---

## Streamlit Dashboard

The dashboard is a **separate Python application**. It lives in its own GitHub repository
and is deployed to **Streamlit Community Cloud** (free). No login is required to view it.

### Data access

Uses `gspread` + a **read-only Google Service Account** to access the Sheets workbook.
Service account credentials JSON is stored as a Streamlit secret (never in the repo).

### Language support

The UI supports **German (default) and English**, switchable via a toggle in the top bar.
All labels, headings, filter names, and table headers are translated. The toggle persists
for the browser session via `st.session_state`.

### Dashboard structure — two sections, no role split

There is no separation between "public" and "coach" areas. The dashboard is one unified
app with two sections accessible to everyone via sidebar navigation:

1. **Individuelle Ergebnisse / Individual Results** — search and view a single swimmer's
   personal timeline, personal bests, and history.
2. **Mannschaft / Team** — overview of all SU MöDLING swimmers, filterable and sortable.

Both sections support **rich filtering** (discipline, birth year, event, date range).

### Views and UI specification

#### Top bar (all views)
- Left: 🏊 app title (translated) — "SU MöDLING — Schwimmergebnisse"
- Right: `DE` / `EN` language toggle buttons (active state highlighted)
- Subtitle: last scraper run timestamp (from Log tab)

#### Sidebar navigation
- **Individuelle Ergebnisse / Individual Results:** "Schwimmer suchen / Find Swimmer"
- **Mannschaft / Team:** "Mannschaftsübersicht / Team Overview",
  "Bestzeiten / Personal Bests Leaderboard", "Letzte Ergebnisse / Recent Results"
- Active item has left blue border + blue text + blue background highlight

---

#### View 1 — Schwimmer suchen / Find Swimmer (landing page, default)

```
┌─────────────────────────────────────────────────────┐
│  HERO BANNER                                        │
│  "Ergebnisse deines Kindes finden"                  │
│  [ text input: "z.B. Vincent Blobner" ] [Suchen]    │
│  ┌─────────────────────────┐  ← dropdown on type    │
│  │ 🏊 BLOBNER Vincent      │                        │
│  │    Jg. 2014 · SU Mödl.  │                        │
│  └─────────────────────────┘                        │
└─────────────────────────────────────────────────────┘
```

After selecting a swimmer:

```
┌──────────────────────────────────────────────────────┐
│ 🏊  BLOBNER Vincent                                  │
│     Jahrgang: 2014  ·  Verein: SU MöDLING            │
│                                                      │
│  Filter: [Disziplin ▼] [Wettkampf ▼] [Zeitraum ▼]   │
│                                                      │
│  [6 Disziplinen]  [8 Wettkämpfe]  [3 Bestzeiten 🏅] │ ← stat pills
│                                                      │
│  [50m Freistil ✓] [100m Freistil] [50m Brust] …     │ ← discipline tabs
│                                                      │
│  ┌──── Zeitverlauf — 50m Freistil ──────────────┐   │
│  │  27s ─────────────────────────────────────   │   │
│  │  28s ──────────────────────────── 🟢 PB      │   │
│  │  29s ─────────────────                       │   │
│  │  30s ───                                     │   │
│  │      Mär  Apr  Mai  Jun  Jul 25              │   │
│  └───────────────────────────────────────────────┘  │
│                                                      │
│  Filter: [Wettkampf ▼] [Zeitraum ▼] [Ort ▼]         │
│                                                      │
│  Datum        Wettkampf            Ort       Zeit    │
│  24/07/2025   53. Swimcity Wels    Wels      27.92🏅 │
│  15/06/2025   NÖ Landesmeister.   Wr.Nst.   28.88   │
│  …                                                   │
└──────────────────────────────────────────────────────┘
```

- Discipline tabs are pill-shaped toggles; selected tab = blue fill
- Line chart: x = date, y = time_sec inverted (lower = faster = higher on chart)
- PB annotation shown on the chart and 🏅 badge in the results table
- Filters apply to both the chart and the table simultaneously
- "Wettkampf" filter = multi-select dropdown of all events this swimmer attended

---

#### View 2 — Mannschaftsübersicht / Team Overview

```
Filter bar:
  [Disziplin ▼] [Jahrgang ▼] [Wettkampf ▼] [Zeitraum ▼] [Name___] [Anwenden] [Zurücksetzen]

Toggle: [Karten ✓]  [Tabelle]

Card mode (grid):
  ┌─────────────────┐  ┌─────────────────┐
  │ BLOBNER Vincent │  │ RIPA Matthias   │
  │ Jg.2014·SU Möd. │  │ Jg.2013·SU Möd. │
  │ 50FS  27.92 🟢  │  │ 50FS  29.44     │
  │ 100FS 1:01.44   │  │ 50BR  35.01 🟢  │
  │ 50BR  34.21     │  │ 100LA 1:14.55   │
  └─────────────────┘  └─────────────────┘

Table mode (pivot):
  Name            Jg.  50FS     100FS   50BR     50SM    100LA
  MÜLLER Jonas    2012  26.88🟢  58.44🟢  —       —       —
  BLOBNER Vincent 2014  27.92🟢  1:01.44  34.21   32.10🟢  —
  RIPA Matthias   2013  29.44    —        35.01🟢  —       1:14.55🟢
```

- Clicking a card navigates to View 1 with that swimmer pre-selected
- Green = personal best across all events
- `—` = no result for that discipline
- Table scrolls horizontally when discipline columns overflow
- All filter controls apply to both card and table mode simultaneously
- "Zeitraum" filter restricts to PBs achieved within the selected date range

---

#### View 3 — Bestzeiten / Personal Bests Leaderboard

```
Filter: [Disziplin ▼] [Jahrgang ▼] [Wettkampf ▼] [Zeitraum ▼] [Anwenden]

 #    Name              Jg.   Bestzeit   Wettkampf              Datum
 🥇1  MÜLLER Jonas      2012  26.88      NÖ Landesmeisterschaft 15/06/2025
 🥈2  BLOBNER Vincent   2014  27.92 🏅   53. Swimcity Wels      24/07/2025
 🥉3  RIPA Matthias     2013  29.44      SVMB Frühjahrsmeeting  10/05/2025
  4   NÉMETH Melina     2013  31.05 🏅   53. Swimcity Wels      24/07/2025
```

- Rows sorted by `time_sec` ascending (fastest first) within the selected discipline
- 🏅 = time set at the most recently scraped event (newly achieved PB)
- Medals shown only for top 3
- When no discipline filter is active: table shows one row per swimmer = their best
  discipline / time combination
- "Zeitraum" restricts to PBs set within the selected period

---

#### View 4 — Letzte Ergebnisse / Recent Results

```
Filter: [Wettkampf ▼] [Disziplin ▼] [Jahrgang ▼] [Anwenden]

 🕐  Letzte Scraper-Ausführung: heute 02:14 Uhr

 🏊 53. Swimcity Wels — 24/07/2025
    BLOBNER Vincent    [27.92 FS 🟢] [34.21 BR] [32.10 SM]
    RIPA Matthias      [29.44 FS] [35.01 BR 🟢]
    KYRKOU Christina   [31.05 FS 🟢]
    ZAVODSKY Leo       [29.20 FS]

 🏊 Offene NÖ LM 2026 — 06/06/2026
    BLOBNER Vincent    [27.35 FS 🟢] …
```

- Grouped by event (most recent first)
- Within each event: all SU MöDLING swimmers who competed
- Green time = personal best in that discipline
- Filter by event narrows to a single competition (useful for post-meet review)
- Filter by birth year shows only swimmers of a specific age group

---

### Hosting

- **Platform:** Streamlit Community Cloud — free tier, public URL.
- **Source:** GitHub repository (public or private).
- **Secrets:** Google Service Account JSON stored in Streamlit Cloud secrets (not in Git).
- **Refresh:** `@st.cache_data(ttl=300)` caches Sheets reads for 5 minutes.

---

## Sub-Tasks

---

### Sub-Task 1 — Google account setup and Sheets workbook

**Status:** `[ ] pending`

**Intent**  
Create the Sheets workbook, set up the 6 sheet tabs with correct column headers, and
create the bound Apps Script project. One-time infrastructure setup.

**Expected Outcomes**
- A Sheets workbook named `SwimmingResults_DB` in Martin's Google Drive.
- Six sheet tabs: `Swimmers`, `Events`, `Results`, `Rescan_Queue`, `Config`, `Log`.
- A bound Apps Script project named `SwimmingResultsScraper`.
- V8 runtime confirmed in `appsscript.json`.
- OAuth scopes declared: `spreadsheets`, `script.external_request`.
- Martin has run any function once to grant OAuth consent.

**Todo List**
1. Log in as Martin Stegmayer (the Workspace for Nonprofits admin account).
2. Create a new Google Sheets file: `SwimmingResults_DB`.
3. Rename the default tab to `Swimmers`. Add tabs: `Events`, `Results`,
   `Rescan_Queue`, `Config`, `Log`.
4. Add column headers to each tab as defined in the Data Model section above.
5. Open Extensions → Apps Script. Name the project `SwimmingResultsScraper`.
6. In the Apps Script editor: View → Show manifest (`appsscript.json`).
   Set `runtimeVersion` to `"V8"` and add `oauthScopes`:
   `"https://www.googleapis.com/auth/spreadsheets"` and
   `"https://www.googleapis.com/auth/script.external_request"`.
7. Save. Run any function (e.g. an empty `hello()`) to trigger the OAuth consent dialog.
   Grant all requested permissions as Martin.

**Relevant Context**
- The OAuth consent must be done by Martin personally — it binds the script's execution
  credentials to his account. All nightly trigger runs execute as Martin.

---

### Sub-Task 2 — Config tab and readConfig()

**Status:** `[ ] pending`

**Intent**  
Populate the Config tab with initial values and implement `readConfig()` in GAS.
Replaces `load_config()` and `config.json` from the Python tool.

**Expected Outcomes**
- Config tab has all key/value rows from the Data Model (including `club_id = 6614`).
- `readConfig()` in `Config.gs` returns a plain JS object with all settings parsed
  to their correct types.
- A `testReadConfig()` function logs the parsed config and passes visually.

**Todo List**
1. In the Sheets workbook, open the `Config` tab and enter all key/value rows.
2. Create `Config.gs` in the Apps Script editor.
3. Implement `readConfig()`:
   - Read all rows from the Config tab via `getDataRange().getValues()`.
   - Build a JS object from `{key: value}` pairs.
   - Parse: `club_id`, `max_parallel`, `page_timeout`, `max_retries` → integers.
   - Parse: `retry_delays` → split on comma, map to numbers.
   - Parse: all `translation_*` keys → build `{engName: deName}` object.
4. Write `testReadConfig()` — call `readConfig()` and log the full result.

**Relevant Context**
- Python source: `load_config()` lines 65–133.
- Unlike Python, there is no `max_workers` — parallelism is the UrlFetchApp batch size.
- `club_id` (6614) is the critical new config key — it drives the club-first discovery.

---

### Sub-Task 3 — HTTP fetch layer (UrlFetchApp)

**Status:** `[ ] pending`

**Intent**  
Implement the HTTP fetching layer using `UrlFetchApp.fetchAll()`. All HTTP requests are
batched and sent in parallel — no thread management needed.

**Expected Outcomes**
- `Fetch.gs` with `fetchHtml(url, cfg)` (single, for testing) and
  `fetchAllHtml(urls, cfg)` (batch, returns `{url: htmlString|null}` map).
- `fetchAllHtml` sends up to `cfg.max_parallel` (100) requests per batch.
- Failed requests return `null` for that URL.
- Retry logic: up to `cfg.max_retries` attempts with `Utilities.sleep()` backoff.
- Browser-mimicking headers on every request (same `User-Agent` + `Accept-Language`
  as the Python `HTTP_HEADERS` dict).
- `testFetchHtml()` fetches the known test URL and logs the first 500 chars.

**Todo List**
1. Create `Fetch.gs`.
2. Declare `HTTP_HEADERS` constant (exact values from Python source lines 148–156).
3. Implement `fetchHtml(url, cfg)`:
   - `UrlFetchApp.fetch(url, {headers: HTTP_HEADERS, muteHttpExceptions: true})`.
   - Return `response.getContentText()` if status 200, else `null`.
4. Implement `fetchAllHtml(urls, cfg)`:
   - Chunk `urls` into arrays of `cfg.max_parallel`.
   - For each chunk: call `UrlFetchApp.fetchAll(requestObjects)`.
   - Collect failed URLs (non-200); retry up to `cfg.max_retries` times.
   - Return `{url: htmlString|null}` map for all input URLs.
5. Write `testFetchHtml()`. Run it and verify HTML is returned.

**Relevant Context**
- Python source: `fetch_html()` lines 389–401, `get_http_session()` lines 223–245.
- `muteHttpExceptions: true` prevents GAS throwing on 4xx/5xx — inspect
  `getResponseCode()` instead.

---

### Sub-Task 4 — HTML parsing: Recent page + Club page

**Status:** `[ ] pending`

**Intent**  
Implement the two new parsing functions for the club-first discovery path:
`parseRecentPage(html)` and `parseClubPage(html)`. These have no equivalent in the
Python tool (which used a fixed event range instead).

**Expected Outcomes**
- `Parser.gs` contains `parseRecentPage(html)` and `parseClubPage(html)` in addition
  to the ported participant-level parsers (see Sub-Task 5).
- `parseRecentPage` returns an array of `{event_id, event_name, date}` objects for
  all events listed on the Recent page.
- `parseClubPage` returns an array of `{participant_id, name}` for the given event's
  club page (club 6614). Returns empty array if the club has no participants.
- Both functions handle gracefully: HTML from an event where the club did not
  participate (club page not found → 200 with empty results section).

**Recent page HTML structure (verified):**
```html
<a href="/de-AT/Meets/Recent/2341/Overview">53. Internationales Swimcity Wels Meeting</a>
...
<div class="hidden-xs col-sm-2">23.-24.05.2026</div>
```

**Club page HTML structure (verified):**
```html
<a href="/de-AT/Meets/Recent/2341/Participant/306991">BLOBNER Vincent</a>
<a href="/de-AT/Meets/Recent/2341/Participant/275975">ZAVODSKY Leo</a>
```

**Todo List**
1. In `Parser.gs`, implement `parseRecentPage(html)`:
   - Pattern: `/\/Recent\/(\d+)\/Overview"[^>]*>([^<]+)<.*?hidden-xs col-sm-2">([^<]+)<`
     (with DOTALL / `s` flag).
   - Parse date with `parseLastDate()` to normalise `DD.MM.YYYY` or range.
   - Return array of `{event_id: int, event_name: str, date: str}`.
2. Implement `parseClubPage(html)`:
   - Pattern: `/\/Recent\/(\d+)\/Participant\/(\d+)"[^>]*>([^<]+)<`
   - Extract `participant_id` and `name` from each match.
   - Return `[]` if no participant links found (club not in this event).
3. Write `testParseRecentPage()`: fetch the live Recent page, assert ≥ 90 events returned.
4. Write `testParseClubPage()`: fetch club page for event 2341 / club 6614, assert
   4 participants: BLOBNER Vincent (306991), ZAVODSKY Leo (275975),
   RAISIC Ana (302966), KYRKOU Christina (329116).

**Relevant Context**
- The Recent page lists exactly 100 events (mix of past and upcoming).
- Only events already processed by the GAS script are in the Events tab — new ones
  discovered on the Recent page drive fresh fetches.
- The `/de-AT/Meets/Recent/2341/Participants` page is AJAX-rendered and cannot be used;
  the Club page (`/Club/6614`) is server-side rendered and works with plain GET.
- Club ID 6614 is stable — it is the permanent identifier for SU MöDLING on myresults.eu.
- Events where SU MöDLING did not participate return an empty participants list (the page
  still returns HTTP 200). These events are still logged in the Events tab with
  `modling_participant_count = 0` to avoid re-checking them.

---

### Sub-Task 5 — HTML parsing: participant page + discipline normalisation

**Status:** `[ ] pending`

**Intent**  
Port all three participant-level HTML parsing functions and `normalizeDiscipline()` from
Python to JavaScript. These are pure regex operations — the patterns are identical.

**Expected Outcomes**
- `Parser.gs` (continued from Sub-Task 4) with: `parseMetadata(html, eventId)`,
  `parseParticipant(html)`, `parseResults(html, cfg)`, `normalizeDiscipline(rawName, cfg)`.
- `parseResults` returns `{disciplineName: {str, sec}}` — fastest time per discipline,
  relays excluded.
- All regex patterns reproduced verbatim from Python (converted to JS literal syntax).
- `testParser()` fetches the known test URL and asserts:
  - event = `"53. Internationales Swimcity Wels Meeting"`
  - name = `"BLOBNER Vincent"`
  - exactly 6 disciplines returned
  - all discipline keys match `NNm Stroke` (no trailing suffixes)

**Todo List**
1. In `Parser.gs`, declare all regex constants. Key patterns to port:
   - `RELAY_PATTERN = /4x/i`
   - `DISCIPLINE_CORE_PATTERN = /^(\d+\s*[mM]?\s+\S+)/i`
   - `TIME_FORMAT_PATTERN = /^(\d{1,2}:)?\d{1,2}\.\d{2}$/`
   - `MEETNAME2_PATTERN`, `NAV3A_PATTERN`, `PERSON_PATTERN` (use `/pattern/s`)
   - `ERGEBNISSE_HEADER_PATTERN`, `DISC_ANCHOR_PATTERN`, `TIME_COL_PATTERN`
   - All strip patterns: PREFIX, GENDER, HEAT, FINAL, AGE, YOUNGER, WHITESPACE
2. Implement `normalizeDiscipline(rawName, cfg)` — port exactly from Python lines 313–341.
3. Implement `parseMetadata(html, eventId)` — port from Python lines 404–441.
4. Implement `parseParticipant(html)` — port from Python lines 444–457.
5. Implement `parseResults(html, cfg)` — port from Python lines 460–530.
6. Implement `testParser()`. Run it and verify PASS.

**Relevant Context**
- Python source: lines 162–210 (regex constants), lines 313–530 (functions).
- Python `re.DOTALL` → JS `/pattern/s` (V8/GAS supports the `s` flag).
- Python `re.IGNORECASE` → JS `/pattern/i`.
- `time_to_seconds()` must also be ported (Python lines 301–310).

---

### Sub-Task 6 — Sheets data access layer

**Status:** `[ ] pending`

**Intent**  
Implement all read/write operations against the Sheets workbook. Replaces `save_to_csv()`,
the CSV file, and the in-memory `event_metadata_cache`. All other GAS functions call these
helpers — they never call `SpreadsheetApp` directly.

**Expected Outcomes**
- `Sheets.gs` with all helpers listed below.
- All multi-row writes use bulk `setValues()`, not per-cell `setValue()`.

**Functions to implement:**

| Function | Description |
|---|---|
| `getSheet(name)` | Returns a Sheet object by tab name (execution-scoped cache) |
| `loadSkipSet()` | Returns a JS `Set` of `"eventId\|swimmerId"` already in Results |
| `loadEventsCache()` | Returns `{eventId: {event_name, date, location}}` from Events tab |
| `loadSwimmers()` | Returns array of `{swimmer_id, name, birth_year, club}` from Swimmers tab |
| `upsertSwimmer(id, name, birthYear, club, firstSeenEventId)` | Insert or update Swimmers row |
| `upsertEvent(id, name, date, location, modlingCount)` | Insert or update Events row |
| `appendResults(eventId, swimmerId, resultsObj)` | Bulk-append rows to Results (`source = "scraper"`) |
| `deleteResults(swimmerId, startEventId, endEventId)` | Remove Results rows for a rescan range |
| `markRescanDone(queueRowIndex)` | Set status to `done` in Rescan_Queue |
| `appendLog(runAt, eventsChecked, eventsNew, swimmersDiscovered, resultsAdded, resultsSkipped, errors, rescans, durationSec, notes)` | Append to Log |

**Todo List**
1. Create `Sheets.gs`.
2. Implement `getSheet(name)` with an execution-scoped cache object.
3. Implement `loadSkipSet()`: read Results cols A+B → build Set of `"eId|sId"` strings.
4. Implement `loadEventsCache()`: read all Events rows → build `{eventId: meta}` object.
5. Implement `loadSwimmers()`: read all Swimmers rows → return array of objects.
6. Implement `upsertSwimmer(id, name, year, club, firstSeenEventId)`:
   - Find the row where col A = `id`. Update all fields + `last_updated`.
   - If not found, append new row.
7. Implement `upsertEvent(id, name, date, location, modlingCount)`: same upsert pattern.
8. Implement `appendResults(eventId, swimmerId, resultsObj)`:
   - Build 2D array: one row per discipline `[eventId, swimmerId, disc, timeStr, timeSec, now, "scraper"]`.
   - Append in one bulk write.
9. Implement `deleteResults(swimmerId, startId, endId)`:
   - Read all Results rows; filter out rows where swimmer_id matches and event_id in range.
   - Rewrite the tab with the filtered set.
10. Implement `markRescanDone(rowIndex)`: set column D of that row to `"done"`.
11. Implement `appendLog(...)`: append a single row to the Log tab.
12. Write `testSheets()`: write one dummy Results row, read it back, then delete it.

**Relevant Context**
- Python source: `save_to_csv()` lines 565–645.
- The discipline sort order (Freistil → Brust → Schmetterling → Rücken → Lagen) is used
  by the Streamlit dashboard, not here — Results is normalised (one row per discipline).
- `getLastRow()` + `getRange(lastRow+1, 1, n, cols).setValues(array)` is the correct
  bulk-append pattern in GAS.

---

### Sub-Task 7 — Main orchestrator (club-first discovery)

**Status:** `[ ] pending`

**Intent**  
Implement `main()` in `Code.gs` — the primary entry point that orchestrates the full
nightly pipeline: fetch Recent page → discover new events → for each event fetch the
Club/6614 page → collect participant IDs → build URL batch → parse → write to Sheets.

**Expected Outcomes**
- `main()` runs cleanly end-to-end.
- Only events not already in the Events tab drive new Club page fetches.
- Only `(event_id, swimmer_id)` pairs not already in Results drive Participant page fetches.
- New swimmers appear automatically in Swimmers tab without manual registration.
- Force-rescan queue is processed before normal tasks.
- Log tab updated at the end of every run.
- `testMain()` runs against event 2341 only and asserts 4 SU MöDLING swimmers,
  with 6 disciplines for swimmer 306991 (BLOBNER Vincent).

**Todo List**
1. Create `Code.gs` with `main()`.
2. At start: `const cfg = readConfig()`.
3. Load skip set: `const skipSet = loadSkipSet()`.
4. Load events cache: `const eventsCache = loadEventsCache()`.
5. **Process Rescan_Queue first:** read `pending` rows, delete Results for the range,
   add pairs to `rescanTasks`, mark rows `processing`.
6. **Fetch Recent page:**
   - `fetchHtml(RECENT_PAGE_URL, cfg)`.
   - `parseRecentPage(html)` → array of `{event_id, event_name, date}`.
7. **Discover new events:** for each event not in `eventsCache`:
   - Fetch `CLUB_PAGE_URL_TEMPLATE.format(event_id, cfg.club_id)`.
   - `parseClubPage(html)` → array of `{participant_id, name}`.
   - `upsertEvent(event_id, event_name, date, location=null, modlingCount)`.
   - For each participant: `upsertSwimmer(participant_id, name, ...)`.
8. **Build participant task list:**
   - For each known event in Events tab (including newly discovered):
     - For each known swimmer in Swimmers tab:
       - If `"eventId|swimmerId"` not in `skipSet` → add to task list.
   - Add `rescanTasks` (bypass skip set).
9. **Build URL list** using `PARTICIPANT_URL_TEMPLATE`.
10. **Fetch all participant pages:** `fetchAllHtml(urls, cfg)` in batches of `cfg.max_parallel`.
11. **Parse and write** for each returned HTML (non-null):
    a. `parseParticipant(html)` — if name and club both "Unknown", skip.
    b. Check `eventsCache` for metadata; if missing, call `parseMetadata(html, eventId)`.
    c. `upsertEvent(...)`.
    d. `upsertSwimmer(...)` — fills in name/year/club if still blank.
    e. `parseResults(html, cfg)` — if any results: `appendResults(...)`.
12. Null responses → increment `errors` counter.
13. Mark processed Rescan_Queue rows as `done`.
14. `appendLog(...)` with all counters.
15. Implement `testMain()` — temporarily override to test event 2341 only.

**URL constants:**
```javascript
const RECENT_PAGE_URL   = 'https://myresults.eu/de-AT/Meets/Recent';
const CLUB_PAGE_URL_TEMPLATE = 'https://myresults.eu/de-AT/Meets/Recent/{event}/Club/{club}';
const PARTICIPANT_URL_TEMPLATE = 'https://myresults.eu/de-AT/Meets/Recent/{event}/Participant/{participant}';
```

**Relevant Context**
- Python source: `process_single_event()` lines 651–712, `ScraperApp.run_scraper()`.
- The skip set prevents re-fetching events already in Results.
- New swimmers on the Club page who are not yet in Swimmers tab are automatically added
  — no form or manual step required.
- Events where SU MöDLING has `modling_participant_count = 0` are still stored in the
  Events tab so they are not re-checked on the next nightly run.

---

### Sub-Task 8 — Nightly time-based trigger

**Status:** `[ ] pending`

**Intent**  
Register a time-based trigger that runs `main()` automatically every night at 02:00.

**Expected Outcomes**
- One active trigger: `main()` runs daily between 02:00–03:00 Vienna time.
- A `setupTrigger()` utility in `Code.gs`.
- The first automatic run completes without error and a new Log row is written.

**Todo List**
1. In `Code.gs`, implement `setupTrigger()`:
   - Delete any existing trigger named `main` first (avoid duplicates).
   - `ScriptApp.newTrigger("main").timeBased().everyDays(1).atHour(2).inTimezone("Europe/Vienna").create()`.
2. Run `setupTrigger()` once manually.
3. Open the Triggers dashboard (⏰) and confirm one trigger is listed.
4. Verify the trigger fires by checking the Executions log the following morning.

**Relevant Context**
- GAS trigger timezone: `"Europe/Vienna"` (Austria).
- If a triggered run fails, GAS automatically sends a failure email to Martin.

---

### Sub-Task 9 — Historic CSV import (Path B)

**Status:** `[ ] pending — implement when CSV files are available`

**Intent**  
Implement a bulk-import function that ingests the CSV files produced by `timescraper_010.py`
into the Sheets workbook. This function is designed and coded now but only executed when
Martin provides the historic CSV files.

**Expected Outcomes**
- `Import.gs` with `importCsvData(csvString)`:
  - Parses the semicolon-delimited CSV with headers:
    `Date;Event Name;Location;ID;Name;Year;Club;[discipline columns...]`
  - For each row: `upsertEvent(...)`, `upsertSwimmer(...)`, `appendResults(...)` with
    `source = "csv_import"`.
  - Duplicate `(event_id, swimmer_id, discipline)` rows are skipped (already in Results).
  - Returns a summary: `{rows_processed, rows_inserted, rows_skipped, errors}`.
- `testImportCsv()` runs a 3-row fixture and verifies the Sheets output.

**CSV format (from Python tool):**
```
Date;Event Name;Location;ID;Name;Year;Club;50m Freistil;100m Freistil;…
05/10/2025;Int. SVS-Schwimmen Trophy 2025;Hallenbad Schwechat;306991;BLOBNER Vincent;2014;SU MöDLING;…
```

**Important notes:**
- The CSV uses `event_name + date + swimmer_id` as the natural key, not a numeric
  event_id. The import function must resolve event_id by looking up the event name + date
  in the Events tab or by generating a synthetic key.
- Synthetic event key strategy: hash `MD5(event_name + date)` → truncate to 6 hex chars
  → use as a string event_id prefixed with `"csv_"` (e.g. `"csv_a3f1b2"`). This avoids
  collisions with real numeric event IDs from myresults.eu.
- `source = "csv_import"` on all imported rows allows them to be identified and
  optionally re-verified once the corresponding myresults.eu event IDs are known.

**Todo List**
1. Create `Import.gs`.
2. Implement a `csvToRows(csvString)` helper that parses the CSV string into an array
   of header-keyed objects.
3. Implement `importCsvData(csvString)`:
   - Parse with `csvToRows()`.
   - Load existing skip set from Results to avoid duplicates.
   - For each parsed row: resolve or create event_id, call `upsertEvent()`,
     `upsertSwimmer()`, `appendResults()` with `source = "csv_import"`.
4. Implement `testImportCsv()` with a 3-row inline fixture.
5. Document the activation step: "Paste CSV content as a string argument to
   `importCsvData()` in the Script Editor and run once."

---

### Sub-Task 10 — Streamlit dashboard

**Status:** `[ ] pending`

**Intent**  
Build and deploy the public-facing dashboard as a Streamlit app on Streamlit Community
Cloud. Reads from Sheets via `gspread`. No login required.

**Expected Outcomes**
- A GitHub repository containing the Streamlit app code.
- A read-only Google Service Account with its JSON key stored as a Streamlit Cloud secret.
- The deployed app is accessible at a public `*.streamlit.app` URL.
- All four views functional with full filter support.
- Data refreshes within 5 minutes of a scraper run.

**App structure:**
```
swimming-results-dashboard/
├── app.py                   # Main entry point, sidebar navigation
├── data.py                  # gspread loaders + @st.cache_data
├── views/
│   ├── swimmer.py           # View 1: individual swimmer timeline
│   ├── team_overview.py     # View 2: Mannschaftsübersicht
│   ├── leaderboard.py       # View 3: Bestzeiten leaderboard
│   └── recent.py            # View 4: Letzte Ergebnisse
├── i18n.py                  # DE/EN translation strings dict
├── requirements.txt         # streamlit, gspread, pandas, plotly, google-auth
└── .streamlit/
    └── config.toml          # Theme / layout config
```

**Todo List**
1. **Service Account setup:**
   - Create a Google Cloud project linked to Martin's Workspace account.
   - Enable Google Sheets API.
   - Create a Service Account with role "Viewer".
   - Download JSON key file.
   - Share `SwimmingResults_DB` with the service account email as Viewer.
2. **Create GitHub repository:** `swimming-results-dashboard`.
3. **Implement `data.py`:**
   - Load credentials from `st.secrets["gcp_service_account"]`.
   - Connect with `gspread.service_account_from_dict(credentials)`.
   - `@st.cache_data(ttl=300)` functions: `load_results()`, `load_swimmers()`,
     `load_events()`, `load_log()`.
4. **Implement `i18n.py`:** flat dict of all UI strings in DE and EN.
5. **Implement views:**
   - `swimmer.py`: name search → filter Results + Events → Plotly line chart
     (x=date, y=time_sec inverted) with PB annotation. Filters: discipline, event,
     date range.
   - `team_overview.py`: card/table toggle, discipline pivot. Filters: discipline,
     birth year, event, date range, name text search.
   - `leaderboard.py`: sort by time_sec asc per discipline. Filters: discipline,
     birth year, event, date range. Medal badges.
   - `recent.py`: grouped by event descending. Filters: event, discipline, birth year.
6. **Deploy to Streamlit Community Cloud** and add `gcp_service_account` secret.
7. **Test:** open public URL, verify all four views load with real data.

**Relevant Context**
- `time_sec` enables correct numeric sorting; display `time_str` for readability.
- Personal best = `min(time_sec)` per `(swimmer_id, discipline)`.
- `source` column in Results allows filtering out CSV-import rows if needed.

---

### Sub-Task 11 — End-to-end validation

**Status:** `[ ] pending`

**Intent**  
Run the full system and confirm outputs are correct.

**Expected Outcomes**
- Running `main()` against the live Recent page (100 events) completes without error.
- Log tab shows correct counters.
- SU MöDLING swimmers are correctly auto-discovered (no manual registration needed).
- All results visible in the Streamlit dashboard with filters working.
- A second `main()` run produces `results_added = 0` (skip set covers everything).
- Force-rescan via Rescan_Queue works correctly.
- Total GAS execution time < 3 minutes for a full run.

**Todo List**
1. Clear all tabs except Config (keep `club_id = 6614` and other Config values).
2. Run `main()` manually from the Script Editor.
3. Inspect the Events tab: should contain all events from the Recent page where
   SU MöDLING participated.
4. Inspect the Swimmers tab: auto-populated from Club page discovery.
5. Inspect the Results tab: results for all discovered `(event_id, swimmer_id)` pairs.
6. Check the Log tab: `errors = 0`.
7. Open the Streamlit dashboard and verify all four views load correctly.
8. Run `main()` again — confirm `results_added = 0`.
9. Manually add a Rescan_Queue row for a known swimmer + event range. Run `main()`.
   Confirm the rescan is processed and results unchanged (same data re-fetched).
10. Check Executions dashboard: runtime < 3 minutes.

---

## Technology Reference

| Technology | Purpose | Where it runs | Cost |
|---|---|---|---|
| Google Apps Script | Scraper runtime (serverless JS) | Google's servers | Free (Workspace included) |
| UrlFetchApp | HTTP client — replaces Python `requests` | Inside GAS | Free (100K req/day) |
| Google Sheets | Persistent data store — replaces CSV | Google Drive (Martin's account) | Free (Workspace for Nonprofits) |
| SpreadsheetApp | Sheets read/write API | Inside GAS | Free |
| Time-based Trigger | Nightly scheduler | GAS scheduler | Free |
| Apps Script Executions | Execution logs | script.google.com | Free |
| Streamlit Community Cloud | Dashboard hosting | Streamlit's servers | Free |
| `gspread` (Python lib) | Sheets API client for Streamlit | Streamlit app runtime | Free |
| `pandas` | Data manipulation in dashboard | Streamlit app runtime | Free |
| `plotly` | Charts in dashboard | Streamlit app runtime | Free |
| Google Cloud (Service Account) | Read-only auth for Streamlit → Sheets | Google Cloud (free tier) | Free |
| GitHub | Source control for Streamlit app | GitHub.com | Free |

### GAS Quotas (Workspace for Nonprofits)

| Quota | Limit | Projected usage |
|---|---|---|
| Max execution time | 6 min / run | ~1–3 min for current scale |
| UrlFetchApp requests | 100 000 / day | ~400 per nightly run — far under limit |
| UrlFetchApp batch size | 100 parallel | Batch loop handles this |
| Script runtime / day | 6 h / day | ~3 min/night — negligible |
| Triggers | 20 / script | 1 nightly trigger |

**Typical nightly request volume estimate:**
- 1 × Recent page fetch
- ~100 × Club/6614 page fetches (one per event on Recent page)
- N × Participant page fetches (only new `(event_id, swimmer_id)` pairs not in skip set)
- On the first run against 100 events with ~4 SU MöDLING swimmers per event: ~401 requests
- On subsequent nightly runs (only 1–2 new events): ~5–10 requests total

---

## Files to be Created

### Apps Script project (script.google.com, bound to SwimmingResults_DB)

| File | Description |
|---|---|
| `Code.gs` | `main()`, `setupTrigger()`, `testMain()` |
| `Config.gs` | `readConfig()`, `testReadConfig()` |
| `Fetch.gs` | `fetchHtml()`, `fetchAllHtml()`, `testFetchHtml()` |
| `Parser.gs` | Recent + Club page parsers, all participant-level parsers, `normalizeDiscipline()`, tests |
| `Sheets.gs` | All Sheets read/write helpers, `appendLog()`, `testSheets()` |
| `Import.gs` | `importCsvData()`, `csvToRows()`, `testImportCsv()` |
| `appsscript.json` | Manifest: V8 runtime, OAuth scopes |

### GitHub repository (swimming-results-dashboard)

| File | Description |
|---|---|
| `app.py` | Main Streamlit entry point, sidebar navigation |
| `data.py` | gspread connection, `@st.cache_data` loaders |
| `i18n.py` | DE/EN translation strings |
| `views/swimmer.py` | Per-swimmer timeline view (View 1) |
| `views/team_overview.py` | Team overview card/table view (View 2) |
| `views/leaderboard.py` | Personal bests leaderboard (View 3) |
| `views/recent.py` | Recent results grouped by event (View 4) |
| `requirements.txt` | `streamlit`, `gspread`, `pandas`, `plotly`, `google-auth` |
| `.streamlit/config.toml` | Theme and layout |

### Python desktop tool

`timescraper_010.py` is **not modified** during this migration.

---

## Execution Sequence

```
Sub-Task 1   Google account + Sheets workbook + Script project
     │
Sub-Task 2   Config tab + readConfig()
     │
Sub-Task 3 ──┐  HTTP fetch layer (UrlFetchApp)
Sub-Task 4 ──┤  Recent + Club page parsers                [3, 4, 5 parallel — no inter-dependency]
Sub-Task 5 ──┘  Participant page parsers + normalisation
     │
Sub-Task 6   Sheets data access layer
     │
Sub-Task 7   Main orchestrator (club-first discovery)
     │
Sub-Task 8   Nightly trigger
     │
Sub-Task 9   Historic CSV import (design + implement; defer execution until CSVs available)
     │
Sub-Task 10  Streamlit dashboard
     │
Sub-Task 11  End-to-end validation
```

Sub-Tasks 3, 4 and 5 have no dependency on each other and can be done concurrently.
All other sub-tasks must be completed in order.

---

## Open Questions / Future Decisions

| Topic | Status | Notes |
|---|---|---|
| Historic CSV files | Deferred | Martin to provide files when ready; Sub-Task 9 handles the import |
| Club ID permanence | Confirmed | `6614` is stable — verified across events 2341 and 2380 |
| AJAX Participants page | Confirmed not usable | The Club page (`/Club/6614`) replaces it |
| Form A / swimmer registration | Removed | Auto-discovery from Club page makes this unnecessary |
| Form B / force-rescan | Simplified | Rescan_Queue tab is admin-editable directly; no Google Form needed |
| Dashboard public access | Confirmed | No login required; Streamlit Community Cloud public URL |
| Manual result entry by parents | **Future feature** — see section below | |

---

## Future Features

### Manual Result Entry (parents / coaches)

**Summary**
Competitions that are not published on myresults.eu — club-internal time trials, meets
on other timing systems, open-water events — cannot be auto-scraped. A parent or coach
should be able to submit results for a swimmer manually. These results must flow into the
same Sheets data model and appear in the dashboard alongside scraped data.

**Design decisions (for future implementation)**

**Entry method: Google Form (public link)**
A Google Form is the simplest no-code input path that works on any device — phone, tablet,
or PC — without any login or app. The form submits to a dedicated Apps Script trigger that
validates and writes to Sheets.

**Form fields:**

| Field | Type | Validation |
|---|---|---|
| Swimmer name | Dropdown (populated from Swimmers tab) | Required |
| Competition name | Short text | Required |
| Competition date | Date picker | Required |
| Location / pool | Short text | Optional |
| Discipline | Dropdown (standard list: 50m Freistil, 100m Freistil, …) | Required |
| Time (MM:SS.ss or SS.ss) | Short text | Validated by trigger against `TIME_FORMAT_PATTERN` |
| Notes | Short text | Optional (e.g. "50m pool", "outdoor") |

Multiple disciplines from the same competition require one form submission per discipline.
This is intentional — it keeps validation simple and avoids complex multi-row form UX.

**Data flow:**

```
Parent submits Google Form
         │
         ▼
onManualResultSubmit() trigger  (Forms.gs)
  ├─ Validate time format
  ├─ Look up swimmer_id from name  (Swimmers tab)
  ├─ Generate synthetic event_id:  "manual_" + MD5(name + date)[:6]
  ├─ upsertEvent(synthetic_id, name, date, location, modlingCount=0)
  ├─ appendResults(synthetic_id, swimmer_id, {discipline: {str, sec}},
  │               source = "manual")
  └─ appendLog(...)
```

**Sheets impact:**
- Results tab: `source = "manual"` distinguishes these rows from scraped and CSV-import rows.
- Events tab: synthetic event_id prefixed `"manual_"` — e.g. `"manual_a3f1b2"`.
  This namespace does not collide with numeric myresults.eu IDs or `"csv_"` IDs.
- Swimmers tab: no change — swimmer must already exist (discovered from Club page or
  imported via CSV before manual entry is attempted).

**Dashboard impact:**
- All four views show manual-entry results alongside scraped results — no special treatment.
- A small label or tooltip (e.g. "✏️ manuell eingetragen") can optionally be shown on
  time badges for `source = "manual"` rows, so parents can distinguish them from
  official scraped results.

**Moderation / correction:**
- A simple admin delete: Martin or a developer removes the offending Results row directly
  in the sheet. No special UI is needed for v1 of this feature.
- Future v2 could add an "edit" form for corrections.

**What must be built (when this feature is activated):**

| Component | Where | Description |
|---|---|---|
| Google Form C | Google Forms (public link) | Manual result entry form with fields above |
| `onManualResultSubmit(e)` | `Forms.gs` (new file or extend existing) | Validates + writes to Sheets |
| `onFormSubmit` trigger | Apps Script Triggers | Fires on Form C submission |
| Dashboard `source` label | `views/*.py` (Streamlit) | Optional ✏️ badge on manual rows |

**Pre-conditions before activating:**
1. The Swimmers tab must already contain the swimmer (auto-discovered or CSV-imported).
2. The Results tab must have a `source` column (already in the current data model).
3. The Events tab must tolerate string event IDs (already in the current data model via
   `"csv_"` synthetic IDs from Sub-Task 9 — `"manual_"` follows the same pattern).

**No changes to the current data model are needed.** The `source` column and the
synthetic-ID strategy are already planned in Sub-Tasks 9. This feature can be activated
at any point after the core system (Sub-Tasks 1–11) is live.
