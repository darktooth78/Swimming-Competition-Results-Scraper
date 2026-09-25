#!/usr/bin/env python3
"""
backfill_convert.py
===================
Converts SUM_Ergebnisse_2025_2026_Alle.csv (produced by generate_sum_report.py
after the swimmer_id patch) into the Import.gs-compatible format and splits the
result into ≤ CHUNK_SIZE-row CSV chunks ready for pasting into the GAS editor.

Input format (semicolon, utf-8-sig):
    event_id;swimmer_id;Veranstaltungsdatum;Veranstaltung;Veranstaltungsort;
    Name Athlet:in;Bewerb;Zeit;Platzierung;Altersklasse

Output format (Import.gs, semicolon, utf-8-sig):
    Date;Event Name;Location;ID;Name;Year;Club;Pool;<disciplines…>
    DD/MM/YYYY;<event name>;<location>;<swimmer_id>;<LASTNAME Firstname>;<year>;<club>;<25m|50m>;<time>;…

Usage:
    python3 backfill_convert.py [SUM_Ergebnisse_2025_2026_Alle.csv]
"""

import sys
import os
import re
import csv
import hashlib
import datetime
from typing import Optional

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
INPUT_CSV  = "SUM_Ergebnisse_2025_2026_Alle.csv"
OUT_PREFIX = "backfill_chunk"
CHUNK_SIZE = 500          # rows per output file (GAS 6-min budget fits ~500 rows comfortably)

# Try to reuse pool-size cache from the existing scraper module
try:
    import timescraper_010 as scraper
    _POOL_CACHE_AVAILABLE = True
except ImportError:
    _POOL_CACHE_AVAILABLE = False

# ---------------------------------------------------------------------------
# Discipline normalisation — mirrors timescraper_010.normalize_discipline()
# ---------------------------------------------------------------------------
_RELAY_RE          = re.compile(r'4x', re.IGNORECASE)
_PREFIX_RE         = re.compile(r'^\d+\s*-\s*')
_GENDER_RE         = re.compile(r'\b(Men|Women|Mixed|Herren|Damen)\b', re.IGNORECASE)
_HEAT_RE           = re.compile(r'\b(Preliminary|Vorlauf|Heats|Entscheidung)\b', re.IGNORECASE)
_FINAL_RE          = re.compile(r'\b([AB]-)?(Final|Finale)\b', re.IGNORECASE)
_AGE_RE            = re.compile(r'\bAK\s*\d+.*', re.IGNORECASE)
_YOUNGER_RE        = re.compile(r'\bund\s+jünger\b', re.IGNORECASE)
_WS_RE             = re.compile(r'\s+')
_CORE_RE           = re.compile(r'^(\d+\s*[mM]?\s+\S+)', re.IGNORECASE)
_TIME_RE           = re.compile(r'^(\d{1,2}:)?\d{1,2}\.\d{2}$')

def normalize_discipline(raw: str) -> Optional[str]:
    """Return 'NNm Stroke' key or None (relay / unrecognisable)."""
    if _RELAY_RE.search(raw):
        return None
    name = _PREFIX_RE.sub('', raw).strip()
    name = _GENDER_RE.sub('', name)
    name = _HEAT_RE.sub('',  name)
    name = _FINAL_RE.sub('', name)
    name = _AGE_RE.sub('',   name)
    name = _YOUNGER_RE.sub('', name)
    name = _WS_RE.sub(' ', name).strip().strip('-').strip()
    m = _CORE_RE.match(name)
    if m:
        name = m.group(1).strip()
    return name or None


def validate_time(s: str) -> bool:
    return bool(_TIME_RE.match(s.strip()))


def time_to_sec(s: str) -> float:
    s = s.replace(',', '.')
    if ':' in s:
        parts = s.split(':')
        return float(parts[0]) * 60 + float(parts[1])
    return float(s)


# ---------------------------------------------------------------------------
# Pool size lookup
# ---------------------------------------------------------------------------
_pool_cache: dict = {}

def get_pool_size(event_id: int) -> str:
    key = str(event_id)
    if key in _pool_cache:
        return _pool_cache[key]
    pool = "50m"
    if _POOL_CACHE_AVAILABLE:
        try:
            pool = scraper.parse_pool_size_from_overview(event_id)
        except Exception:
            pool = "50m"
    _pool_cache[key] = pool
    return pool


# ---------------------------------------------------------------------------
# Date normalisation: "DD.MM.YYYY" or "DD.-DD.MM.YYYY" → "DD/MM/YYYY"
# ---------------------------------------------------------------------------
_DATE_EXTRACT = re.compile(r'(\d{1,2})\.(\d{1,2})\.(\d{4})$')

def normalise_date(raw: str) -> str:
    """Extract the last date from a range string and return DD/MM/YYYY."""
    # Try last DD.MM.YYYY in string
    matches = re.findall(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', raw)
    if matches:
        d, mo, y = matches[-1]
        return f"{int(d):02d}/{int(mo):02d}/{y}"
    return raw


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    input_path = sys.argv[1] if len(sys.argv) > 1 else INPUT_CSV
    if not os.path.exists(input_path):
        print(f"ERROR: input file not found: {input_path}")
        print("Run generate_sum_report.py first, then re-run this script.")
        sys.exit(1)

    print(f"Reading: {input_path}")
    with open(input_path, encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f, delimiter=';')
        raw_rows = list(reader)

    print(f"  → {len(raw_rows)} raw result rows")

    # ── Step 1: Pivot rows into {(event_id, swimmer_id): {..., disciplines: {disc: best_sec}}}
    # Key: (event_id, swimmer_id)
    # Value: athlete meta + dict of best times per normalised discipline

    athlete_events: dict = {}   # (eid_str, sid_str) → {meta, times, times_str}

    skipped_relay  = 0
    skipped_time   = 0
    skipped_noname = 0

    for row in raw_rows:
        event_id   = row.get('event_id', '').strip()
        swimmer_id = row.get('swimmer_id', '').strip()
        name       = row.get('Name Athlet:in', '').strip()
        date_raw   = row.get('Veranstaltungsdatum', '').strip()
        event_name = row.get('Veranstaltung', '').strip()
        location   = row.get('Veranstaltungsort', '').strip()
        discipline = row.get('Bewerb', '').strip()
        time_raw   = row.get('Zeit', '').strip()

        if not swimmer_id or not event_id:
            skipped_noname += 1
            continue

        disc_key = normalize_discipline(discipline)
        if disc_key is None:
            skipped_relay += 1
            continue

        # time must be valid
        time_str = time_raw.replace(',', '.')
        if not validate_time(time_str):
            skipped_time += 1
            continue

        key = (event_id, swimmer_id)
        if key not in athlete_events:
            athlete_events[key] = {
                'event_id':   event_id,
                'swimmer_id': swimmer_id,
                'name':       name,
                'date_raw':   date_raw,
                'date':       normalise_date(date_raw),
                'event_name': event_name,
                'location':   location,
                'year':       '',    # not in CSV — will be left blank
                'club':       'SU MöDLING',
                'times':      {},    # disc_key → time_sec (fastest)
                'times_str':  {},    # disc_key → time_str
                'place':      {},    # disc_key → place string (e.g. '1.')
                'medal':      {},    # disc_key → medal string (e.g. 'Gold')
                'age_group':  {},    # disc_key → age group string
            }

        ae = athlete_events[key]
        place     = row.get('Platzierung', '').strip()
        medal     = row.get('Medaille', '').strip()
        age_group = row.get('Altersklasse', '').strip()

        sec = time_to_sec(time_str)
        if disc_key not in ae['times'] or sec < ae['times'][disc_key]:
            ae['times'][disc_key]     = sec
            ae['times_str'][disc_key] = time_str
            ae['place'][disc_key]     = place
            ae['medal'][disc_key]     = medal
            ae['age_group'][disc_key] = age_group

    print(f"  → skipped: {skipped_relay} relays, {skipped_time} invalid times, {skipped_noname} missing IDs")
    print(f"  → {len(athlete_events)} athlete×event combinations")

    # ── Step 2: Collect all discipline columns (sorted consistently)
    all_discs: set = set()
    for ae in athlete_events.values():
        all_discs.update(ae['times_str'].keys())

    def _disc_sort_key(d: str):
        stroke_order = ['Freistil', 'Brust', 'Schmetterling', 'Rücken', 'Lagen',
                        'Freestyle', 'Breaststroke', 'Butterfly', 'Backstroke', 'Medley']
        try:
            dist = int(re.match(r'(\d+)', d).group(1))
        except Exception:
            dist = 9999
        stroke = d.split()[-1] if len(d.split()) > 1 else ''
        try:
            s_idx = stroke_order.index(stroke)
        except ValueError:
            s_idx = len(stroke_order)
        return (s_idx, dist)

    sorted_discs = sorted(all_discs, key=_disc_sort_key)
    print(f"  → {len(sorted_discs)} unique disciplines: {sorted_discs[:8]}{'…' if len(sorted_discs) > 8 else ''}")

    # ── Step 3: Fetch pool sizes (one HTTP call per unique event_id, cached)
    unique_event_ids = sorted(set(ae['event_id'] for ae in athlete_events.values()))
    print(f"\nFetching pool sizes for {len(unique_event_ids)} events…")
    for i, eid in enumerate(unique_event_ids, 1):
        try:
            pool = get_pool_size(int(eid))
        except ValueError:
            pool = "50m"
        _pool_cache[eid] = pool
        print(f"  [{i}/{len(unique_event_ids)}] event {eid} → {pool}")

    # ── Step 4: Build output rows
    FIXED_HEADERS = ['Date', 'Event Name', 'Location', 'ID', 'Name', 'Year', 'Club', 'Pool']
    output_headers = FIXED_HEADERS + sorted_discs

    output_rows = []
    for ae in sorted(athlete_events.values(), key=lambda r: (r['date'], r['event_name'], r['name'])):
        pool = _pool_cache.get(ae['event_id'], '50m')
        row_out = [
            ae['date'],
            ae['event_name'],
            ae['location'],
            ae['swimmer_id'],
            ae['name'],
            ae['year'],
            ae['club'],
            pool,
        ] + [ae['times_str'].get(d, '') for d in sorted_discs]
        output_rows.append(row_out)

    print(f"\n{len(output_rows)} output rows ready for import")

    # ── Step 5: Write chunks
    n_chunks = max(1, (len(output_rows) + CHUNK_SIZE - 1) // CHUNK_SIZE)
    print(f"Writing {n_chunks} chunk file(s) (up to {CHUNK_SIZE} rows each)…")

    for ci in range(n_chunks):
        chunk = output_rows[ci * CHUNK_SIZE : (ci + 1) * CHUNK_SIZE]
        filename = f"{OUT_PREFIX}_{ci + 1:02d}.csv"
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f, delimiter=';')
            writer.writerow(output_headers)
            writer.writerows(chunk)
        print(f"  ✓ {filename}  ({len(chunk)} rows)")

    # ── Step 6: Print GAS instructions
    print()
    print("=" * 60)
    print("NEXT STEPS — paste into Google Apps Script editor")
    print("=" * 60)
    print()
    print("For EACH chunk file:")
    print("  1. Open the chunk .csv in a text editor and copy ALL content.")
    print("  2. In the Apps Script editor, open the file with importCsvData().")
    print("  3. Create a temporary wrapper function, e.g.:")
    print()
    print("     function runImportChunk01() {")
    print("       const csv = `<PASTE CHUNK CONTENT HERE>`;")
    print("       const result = importCsvData(csv);")
    print("       Logger.log(JSON.stringify(result));")
    print("     }")
    print()
    print("  4. Select runImportChunk01 in the function dropdown and click Run.")
    print("  5. Check the Execution Log for { rows_inserted, rows_skipped, errors }.")
    print("  6. Repeat for each subsequent chunk file.")
    print()
    print("TIP: The skip-set in importCsvData() prevents duplicates —")
    print("     safe to re-run a chunk if something went wrong.")
    print()
    print(f"Chunk files written: {[f'{OUT_PREFIX}_{i+1:02d}.csv' for i in range(n_chunks)]}")


if __name__ == "__main__":
    main()
