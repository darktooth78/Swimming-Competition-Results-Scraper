#!/usr/bin/env python3
"""
generate_sum_report.py
======================
Scrapes SUM (Schwimm Union Mödling, Club 6614) results from myresults.eu.

Modes
-----
  (default) recent  : Event IDs 2000–2459, date-filtered 01/2025–08/2026
                      → SUM_Ergebnisse_2025_2026_Alle.csv + SUM_Medaillen_2025_2026.csv
  --mode history    : Event IDs 504–2460, NO date filter
                      → SUM_Ergebnisse_2010_2026_Alle.csv
                      Full historical scrape for Club 6614 (mid-2010 to present).

Both modes apply the same strict validation:
  • Drop blank / "Unknown" swimmer names
  • Drop relay teams (name contains "MANNSCHAFT", "STAFFEL", or discipline "4x")
  • Drop blank / "Unknown" event names
  • Drop invalid time strings (must match SS.ss or M:SS.ss)
"""

import sys
import os
import re
import csv
import datetime
import urllib.request
import concurrent.futures
from typing import List, Dict, Any, Optional, Tuple

# ---------------------------------------------------------------------------
# Discipline normalisation (mirrors timescraper_010.py normalize_discipline)
# ---------------------------------------------------------------------------
_RELAY_RE      = re.compile(r"4x", re.IGNORECASE)
_PREFIX_RE     = re.compile(r"^\d+\s*-\s*")
_GENDER_RE     = re.compile(r"\b(Men|Women|Mixed|Herren|Damen|männlich|weiblich|Frauen|Männer)\b", re.IGNORECASE)
_HEAT_RE       = re.compile(r"\b(Preliminary|Vorlauf|Heats|Entscheidung|Lauf\s*\d*)\b", re.IGNORECASE)
_FINAL_RE      = re.compile(r"\b([AB]-)?(Final|Finale)\b", re.IGNORECASE)
_AGE_RE        = re.compile(r"\bAK\s*\d+.*", re.IGNORECASE)
_YOUNGER_RE    = re.compile(r"\bund\s+jünger\b", re.IGNORECASE)
_WS_RE         = re.compile(r"\s+")
_CORE_RE       = re.compile(r"^(\d+\s*[mM]?\s+\S+)", re.IGNORECASE)
_TRANSLATIONS  = {
    "Backstroke": "Rücken", "Breaststroke": "Brust", "Butterfly": "Schmetterling",
    "Freestyle": "Freistil", "Ind. Medley": "Lagen", "Medley": "Lagen", "Free": "Freistil",
}

def _normalize_discipline(raw: str) -> Optional[str]:
    """Strip heat/gender/age suffixes and translate EN→DE stroke names.
    Returns None for relay (4x) events."""
    if _RELAY_RE.search(raw):
        return None
    name = _PREFIX_RE.sub("", raw).strip()
    name = _GENDER_RE.sub("", name)
    name = _HEAT_RE.sub("", name)
    name = _FINAL_RE.sub("", name)
    name = _AGE_RE.sub("", name)
    name = _YOUNGER_RE.sub("", name)
    for eng, ger in _TRANSLATIONS.items():
        name = name.replace(eng, ger)
    name = _WS_RE.sub(" ", name).strip().strip("- ")
    m = _CORE_RE.match(name)
    if m:
        name = m.group(1).strip()
    return name if name else None


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
RECENT_START_DATE = datetime.date(2025, 1, 1)
RECENT_END_DATE   = datetime.date(2026, 8, 31)
RECENT_EVENT_RANGE = range(2000, 2460)

HISTORY_EVENT_RANGE = range(504, 2461)

CLUB_ID    = 6614
MAX_WORKERS = 30
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Valid swimming time: SS.ss  or  [M]M:SS.ss  (seconds 00–59, minutes 0–59)
TIME_RE = re.compile(r'^(?:[0-5]?\d):(?:[0-5]\d)\.\d{2}$|^[0-5]\d\.\d{2}$')

# Relay / team placeholders to drop
RELAY_PATTERNS = re.compile(r'MANNSCHAFT|STAFFEL|4\s*[xX]\s*\d', re.IGNORECASE)

# Pool-size detection on Overview page
POOL_SIZE_RE = re.compile(r'(\d+)m\s*\((?:SCM|LCM)\)', re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_date_str(d_str: str) -> Optional[datetime.date]:
    """Parse date from strings like '23.-24.05.2026', '04.05.2025', or
    multi-day formats like '28.02.-01.03.2025'.
    Always returns the last (end) date of the event."""
    s = d_str.strip()
    # Find all dd.mm.yyyy occurrences; take the last one
    full = re.findall(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', s)
    if full:
        d, mo, y = full[-1]
        try:
            return datetime.date(int(y), int(mo), int(d))
        except ValueError:
            pass
    # Cross-month: "28.02.-01.03.2025" — day.month already matched above
    # Fallback: trailing year with earlier day tokens e.g. "01.-02.04.2017"
    m = re.search(r'(\d{1,2})\.-(\d{1,2})\.(\d{2})\.(\d{4})$', s)
    if m:
        try:
            return datetime.date(int(m.group(4)), int(m.group(3)), int(m.group(2)))
        except ValueError:
            pass
    # Last resort: any two-digit day + two-digit month + four-digit year at end
    m = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', s)
    if m:
        try:
            return datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass
    return None


def time_to_seconds(t_str: str) -> Optional[float]:
    """Convert 'SS.ss' or 'M:SS.ss' to float seconds, or None if invalid."""
    if not TIME_RE.match(t_str):
        return None
    try:
        if ':' in t_str:
            mins, secs = t_str.split(':')
            return int(mins) * 60 + float(secs)
        return float(t_str)
    except ValueError:
        return None


def fetch_url(url: str, timeout: int = 15) -> Optional[str]:
    """HTTP GET with 3 retries; returns decoded HTML or None."""
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode('utf-8', errors='ignore')
        except Exception:
            pass
    return None


def is_valid_swimmer(name: str) -> bool:
    """Return False for blank names, 'Unknown', or relay team placeholders."""
    if not name or name.strip().lower() in ('', 'unknown', 'unbekannt'):
        return False
    if RELAY_PATTERNS.search(name):
        return False
    return True


def is_valid_event(name: str) -> bool:
    """Return False for blank or 'Unknown' event names."""
    return bool(name and name.strip().lower() not in ('', 'unknown', 'unbekannt'))


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

_pool_cache: Dict[int, str] = {}


def fetch_pool_size(event_id: int) -> str:
    """Fetch pool size from the Overview page; cache result per event."""
    if event_id in _pool_cache:
        return _pool_cache[event_id]
    url = f"https://myresults.eu/de-AT/Meets/Recent/{event_id}/Overview"
    html = fetch_url(url)
    pool = "50m"  # default
    if html:
        m = POOL_SIZE_RE.search(html)
        if m:
            pool = f"{m.group(1)}m"
    _pool_cache[event_id] = pool
    return pool


def scan_club_page(event_id: int) -> Tuple[int, List[Tuple[int, str]], Dict[str, Any]]:
    """
    Returns (event_id, [(participant_id, name)], event_meta).
    event_meta keys: name, date, location, date_obj
    """
    url = f"https://myresults.eu/de-AT/Meets/Recent/{event_id}/Club/{CLUB_ID}"
    html = fetch_url(url)
    if not html:
        return event_id, [], {}

    # Metadata
    meet_m = re.search(r'<p class="myresults_meetname2">([^<]+)</p>', html)
    if not meet_m:
        meet_m = re.search(r'<ul class="myresults_nav3a[^"]*"><p[^>]*>([^<]+)</p>', html)
    raw_meet = meet_m.group(1).strip() if meet_m else ""

    m_meta = re.match(r'^(.*?)\s*\((\d{1,2}\.[-.\d]*\d{4})\)\s*-\s*(.*)$', raw_meet)
    if m_meta:
        e_name = m_meta.group(1).strip()
        e_date = m_meta.group(2).strip()
        e_loc  = m_meta.group(3).strip()
    else:
        e_name = raw_meet
        e_date = ""
        e_loc  = ""

    d_obj = parse_date_str(e_date)
    meta  = {'name': e_name, 'date': e_date, 'location': e_loc, 'date_obj': d_obj}

    # Participants
    p_pattern = re.compile(rf'/Recent/{event_id}/Participant/(\d+)"[^>]*>([^<]+)<')
    seen: set = set()
    unique_p: List[Tuple[int, str]] = []
    for pid_str, pname in p_pattern.findall(html):
        pid = int(pid_str)
        name = pname.strip()
        if pid not in seen and is_valid_swimmer(name):
            seen.add(pid)
            unique_p.append((pid, name))

    return event_id, unique_p, meta


def parse_participant_page(
    event_id: int,
    pid: int,
    default_meta: Dict[str, Any],
    pool: str,
) -> List[Dict[str, Any]]:
    """
    Fetch one participant page and return enriched result rows.
    Returns [] on error or if swimmer fails validation.
    """
    url = f"https://myresults.eu/de-AT/Meets/Recent/{event_id}/Participant/{pid}"
    html = fetch_url(url)
    if not html:
        return []

    # Swimmer name
    name_m = re.search(r'<td class="myresults_personendetails_header"[^>]*>([^<]+)</td>', html)
    swimmer_name = name_m.group(1).strip() if name_m else ""
    if not is_valid_swimmer(swimmer_name):
        return []

    # Birth year (from personendetails table, format "YYYY" or "Jg. YYYY")
    year_m = re.search(r'<td[^>]*class="myresults_personendetails_info"[^>]*>(?:Jg\.\s*)?(\d{4})</td>', html)
    birth_year = year_m.group(1) if year_m else ""

    # Club (3rd personendetails_info cell)
    info_cells = re.findall(r'<td[^>]*class="myresults_personendetails_info"[^>]*>([^<]+)</td>', html)
    club = info_cells[1].strip() if len(info_cells) >= 2 else "SU Mödling"

    # Event metadata
    meet_m = re.search(r'<p class="myresults_meetname2">([^<]+)</p>', html)
    raw_meet = meet_m.group(1).strip() if meet_m else ""
    m_meta = re.match(r'^(.*?)\s*\((\d{1,2}\.[-.\d]*\d{4})\)\s*-\s*(.*)$', raw_meet)
    if m_meta:
        e_name = m_meta.group(1).strip()
        e_date = m_meta.group(2).strip()
        e_loc  = m_meta.group(3).strip()
    else:
        e_name = default_meta.get('name', '')
        e_date = default_meta.get('date', '')
        e_loc  = default_meta.get('location', '')

    if not is_valid_event(e_name):
        return []

    # Results section
    ergebnisse_idx = html.find('Ergebnisse</div>')
    if ergebnisse_idx == -1:
        m_erg = re.search(r'Ergebnisse\s*</div>', html, re.IGNORECASE)
        if m_erg:
            ergebnisse_idx = m_erg.start()
        else:
            return []

    results_part = html[ergebnisse_idx:]
    row_splits = re.split(
        r'(?=<div[^>]*class="row myresults_content_divtablerow\s+myresults_content_divtablerow_(?:odd|even))',
        results_part,
    )

    records: List[Dict[str, Any]] = []
    for chunk in row_splits[1:]:
        # Discipline from anchor
        anchor_m = re.search(r'<a[^>]*href="[^"]*Results/[^"]*"[^>]*>(.*?)<', chunk)
        if not anchor_m:
            continue
        disc_raw = re.sub(r'<[^>]+>', '', anchor_m.group(1)).strip()
        if not disc_raw or disc_raw == "Das Unternehmen":
            continue
        disc = _normalize_discipline(disc_raw)
        if disc is None:
            continue   # relay or unparseable — skip

        # Place
        place_m = re.search(r'<span class="msecm-place[^"]*">([^<]+)</span>', chunk)
        place = place_m.group(1).strip() if place_m else ""

        # Age group / Altersklasse
        ak_m = re.search(r'<span class="myresults_content_divtable_details_black">([^<]+)</span>', chunk)
        ak = ak_m.group(1).strip() if ak_m else ""

        # Time — prefer first right-aligned column without "points" in class
        time_m = re.search(
            r'<div class="hidden-xs\s+col-sm-2\s+col-md-1\s+text-right\s+myresults_content_divtable_right">([^<]+)</div>',
            chunk,
        )
        if not time_m:
            time_m = re.search(
                r'<div class="[^"]*myresults_content_divtable_right[^"]*">([^<]+)</div>', chunk
            )
        time_str = time_m.group(1).strip() if time_m else ""

        # Validate time format
        time_sec = time_to_seconds(time_str)
        if time_sec is None:
            continue  # drop rows with invalid or missing times

        # Medal
        if 'msecm-place-gold' in chunk or place == '1.':
            medal = "Gold"
        elif 'msecm-place-silver' in chunk or place == '2.':
            medal = "Silber"
        elif 'msecm-place-bronze' in chunk or place == '3.':
            medal = "Bronze"
        else:
            medal = ""

        records.append({
            'event_id':       event_id,
            'swimmer_id':     pid,
            'date':           e_date,
            'event_name':     e_name,
            'location':       e_loc,
            'name':           swimmer_name,
            'birth_year':     birth_year,
            'club':           club,
            'pool':           pool,
            'discipline':     disc,
            'time_str':       time_str,
            'time_sec':       f"{time_sec:.3f}",
            'place':          place,
            'medal':          medal,
            'age_group':      ak,
        })

    return records


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

FIELDNAMES = [
    "event_id", "swimmer_id", "date", "event_name", "location",
    "name", "birth_year", "club", "pool",
    "discipline", "time_str", "time_sec", "place", "medal", "age_group",
]


def run_scrape(
    event_range,
    date_filter: Optional[Tuple[datetime.date, datetime.date]],
    output_csv: str,
    label: str,
):
    print("=" * 65)
    print(f"SUM Club {CLUB_ID} Results Scraper — {label}")
    if date_filter:
        s, e = date_filter
        print(f"Date filter: {s.strftime('%d.%m.%Y')} – {e.strftime('%d.%m.%Y')}")
    else:
        print("Date filter: none (full history)")
    print(f"Event ID range: {event_range.start} – {event_range.stop - 1}")
    print(f"Threads: {MAX_WORKERS}")
    print("=" * 65)

    # ── Phase 1: Scan club pages ──────────────────────────────────────────
    event_list = list(event_range)
    print(f"\nPhase 1: Scanning {len(event_list)} event IDs for Club {CLUB_ID} participants...")

    valid_events = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(scan_club_page, eid): eid for eid in event_list}
        for fut in concurrent.futures.as_completed(futures):
            eid, participants, meta = fut.result()
            if not participants:
                continue
            if date_filter:
                d_obj = meta.get('date_obj')
                if not d_obj or not (date_filter[0] <= d_obj <= date_filter[1]):
                    continue
            valid_events.append((eid, participants, meta))

    valid_events.sort(
        key=lambda x: x[2].get('date_obj') or datetime.date(1970, 1, 1),
        reverse=True,
    )
    total_tasks = sum(len(p) for _, p, _ in valid_events)
    print(f"Found {len(valid_events)} events with SUM participants.")
    print(f"Total participant pages to fetch: {total_tasks}")

    # ── Phase 2: Pool size (one fetch per event) ──────────────────────────
    print("\nPhase 2: Fetching pool sizes...")
    unique_eids = [eid for eid, _, _ in valid_events]
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        pool_futures = {ex.submit(fetch_pool_size, eid): eid for eid in unique_eids}
        for fut in concurrent.futures.as_completed(pool_futures):
            fut.result()  # populate _pool_cache
    print(f"Pool sizes cached for {len(_pool_cache)} events.")

    # ── Phase 3: Participant pages ────────────────────────────────────────
    tasks = [
        (eid, pid, meta, _pool_cache.get(eid, "50m"))
        for eid, participants, meta in valid_events
        for pid, _ in participants
    ]

    print("\nPhase 3: Fetching participant result pages...")
    all_results: List[Dict[str, Any]] = []
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        fut_map = {
            ex.submit(parse_participant_page, eid, pid, meta, pool): (eid, pid)
            for eid, pid, meta, pool in tasks
        }
        for fut in concurrent.futures.as_completed(fut_map):
            rows = fut.result()
            all_results.extend(rows)
            done += 1
            if done % 200 == 0 or done == len(tasks):
                print(f"  {done}/{len(tasks)} pages done — {len(all_results)} rows so far")

    # ── Validation summary ────────────────────────────────────────────────
    unknowns = [r for r in all_results if not is_valid_swimmer(r['name']) or not is_valid_event(r['event_name'])]
    print(f"\n✅ Rows passing validation: {len(all_results)}")
    if unknowns:
        print(f"⚠️  Rows with invalid name/event (should be 0): {len(unknowns)}")


    # Dedup: keep fastest time per (swimmer_id, event_id, discipline).
    # Required because normalization collapses heats/finals to the same key.
    best: Dict[Tuple, Dict] = {}
    for r in all_results:
        key = (r['swimmer_id'], r['event_id'], r['discipline'])
        try:
            t_sec = float(r['time_sec'])
        except ValueError:
            t_sec = float('inf')
        if key not in best or t_sec < float(best[key]['time_sec']):
            best[key] = r
    all_results = list(best.values())
    print(f"After dedup (fastest per swimmer/event/discipline): {len(all_results)} rows")


    # ── Sort & save ───────────────────────────────────────────────────────
    all_results.sort(key=lambda r: (r['date'], r['event_name'], r['name'], r['discipline']))

    with open(output_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, delimiter=";", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_results)

    print(f"\nSaved {len(all_results)} rows to: {output_csv}")

    # ── Medal summary (recent mode only) ─────────────────────────────────
    if not date_filter:
        return all_results  # history mode — no medal CSV

    medal_results = [r for r in all_results if r['medal']]
    medal_csv = output_csv.replace("_Alle.csv", "_Medaillen.csv").replace("_2025_2026_Alle.csv", "")
    # Keep legacy medal CSV path
    medal_csv_path = "SUM_Medaillen_2025_2026.csv"
    with open(medal_csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, delimiter=";", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(medal_results)
    print(f"Saved {len(medal_results)} medal rows to: {medal_csv_path}")

    return all_results


def main():
    mode = "recent"
    if "--mode" in sys.argv:
        idx = sys.argv.index("--mode")
        if idx + 1 < len(sys.argv):
            mode = sys.argv[idx + 1]

    if mode == "history":
        run_scrape(
            event_range=HISTORY_EVENT_RANGE,
            date_filter=None,
            output_csv="SUM_Ergebnisse_2010_2026_Alle.csv",
            label="Full History 2010–2026",
        )
    else:
        run_scrape(
            event_range=RECENT_EVENT_RANGE,
            date_filter=(RECENT_START_DATE, RECENT_END_DATE),
            output_csv="SUM_Ergebnisse_2025_2026_Alle.csv",
            label="Recent 2025–2026",
        )


if __name__ == "__main__":
    main()
