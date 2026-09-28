#!/usr/bin/env python3
"""
upload_history_to_sheets.py
===========================
Read SUM_Ergebnisse_2010_2026_Alle.csv (produced by generate_sum_report.py
--mode history) and batch-upload new rows into SwimmingResults_DB.

Target sheets and column layout
---------------------------------
Events  (A–G): event_id | event_name | date | location | last_updated |
               modling_participant_count | pool
Swimmers(A–D): swimmer_id | name | birth_year | club
Results (A–J): event_id | swimmer_id | discipline | time_str | time_sec |
               fetched_at | source | place | medal | age_group

Fail-safe rules
---------------
• Skip rows where name or event_name is empty / "Unknown".
• Skip rows where event_id or swimmer_id is blank.
• Deduplicate against existing Results rows using composite key
  event_id + swimmer_id + discipline (keeps fastest time per trio if clash).
• Write in chunks of CHUNK_SIZE rows to avoid API payload limits.

Auth
----
Reads credentials from oauth_token.json (produced by generate_streamlit_token.py
or setup_google.py). Refreshes if the access token is expired.

Usage
-----
    python3 upload_history_to_sheets.py
    python3 upload_history_to_sheets.py --csv SUM_Ergebnisse_2010_2026_Alle.csv
    python3 upload_history_to_sheets.py --dry-run   # validate only, no writes
"""

import sys
import csv
import json
import datetime
import argparse
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional

import gspread
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SPREADSHEET_NAME = "SwimmingResults_DB"
TOKEN_FILE       = "oauth_token.json"
CHUNK_SIZE       = 2_000
SOURCE_LABEL     = "history_backfill"
SCOPES           = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Columns we write to each sheet (order matches the sheet's column layout)
EVENTS_COLS   = ["event_id", "event_name", "date", "location",
                 "last_updated", "modling_participant_count", "pool"]
SWIMMERS_COLS = ["swimmer_id", "name", "birth_year", "club"]
RESULTS_COLS  = ["event_id", "swimmer_id", "discipline", "time_str",
                 "time_sec", "fetched_at", "source",
                 "place", "medal", "age_group"]


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _load_credentials() -> Credentials:
    token_path = Path(TOKEN_FILE)
    if not token_path.exists():
        sys.exit(
            f"[ERROR] {TOKEN_FILE} not found.  "
            "Run generate_streamlit_token.py first to create it."
        )
    data = json.loads(token_path.read_text())
    creds = Credentials(
        token         = data.get("token"),
        refresh_token = data.get("refresh_token"),
        token_uri     = data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id     = data.get("client_id"),
        client_secret = data.get("client_secret"),
        scopes        = data.get("scopes", SCOPES),
    )
    if not creds.valid:
        print("  Refreshing OAuth token...")
        creds.refresh(Request())
        # Persist refreshed token
        token_path.write_text(json.dumps({
            "token":         creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri":     creds.token_uri,
            "client_id":     creds.client_id,
            "client_secret": creds.client_secret,
            "scopes":        list(creds.scopes or SCOPES),
        }, indent=2))
    return creds


def _get_client() -> gspread.Client:
    return gspread.authorize(_load_credentials())


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_UNKNOWN = {"", "unknown", "unbekannt"}


def _is_valid_swimmer(name: str) -> bool:
    return bool(name and name.strip().lower() not in _UNKNOWN)


def _is_valid_event(name: str) -> bool:
    return bool(name and name.strip().lower() not in _UNKNOWN)


# ---------------------------------------------------------------------------
# Sheet readers
# ---------------------------------------------------------------------------

def _existing_keys(ws: gspread.Worksheet, col_names: List[str]) -> Set[Tuple]:
    """
    Return a set of tuples for all existing rows using the specified column names.
    Assumes the first row is the header.
    """
    records = ws.get_all_records(numericise_ignore=["all"])
    result: Set[Tuple] = set()
    for rec in records:
        key = tuple(str(rec.get(c, "")).strip() for c in col_names)
        result.add(key)
    return result


# ---------------------------------------------------------------------------
# CSV reader
# ---------------------------------------------------------------------------

def _read_csv(path: str) -> List[Dict[str, str]]:
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            rows.append({k.strip(): v.strip() for k, v in row.items()})
    return rows


# ---------------------------------------------------------------------------
# Main upload logic
# ---------------------------------------------------------------------------

def upload(csv_path: str, dry_run: bool) -> None:
    now_str = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── Load CSV ─────────────────────────────────────────────────────────────
    print(f"\n[1/5] Reading {csv_path} ...")
    all_rows = _read_csv(csv_path)
    print(f"      {len(all_rows)} rows read from CSV.")

    # ── Pre-upload validation ────────────────────────────────────────────────
    print("[2/5] Validating rows ...")
    valid_rows = []
    skipped_invalid = 0
    for row in all_rows:
        name      = row.get("name", "").strip()
        event_name = row.get("event_name", "").strip()
        event_id  = row.get("event_id", "").strip()
        swimmer_id = row.get("swimmer_id", "").strip()
        if not event_id or not swimmer_id:
            skipped_invalid += 1
            continue
        if not _is_valid_swimmer(name):
            skipped_invalid += 1
            continue
        if not _is_valid_event(event_name):
            skipped_invalid += 1
            continue
        valid_rows.append(row)
    print(f"      {len(valid_rows)} valid rows  |  {skipped_invalid} skipped (invalid name/event)")

    if not valid_rows:
        print("[!] No valid rows to upload. Exiting.")
        return

    # ── Connect to Sheets ─────────────────────────────────────────────────────
    print("[3/5] Connecting to Google Sheets ...")
    client = _get_client()
    spreadsheet = client.open(SPREADSHEET_NAME)
    ws_events   = spreadsheet.worksheet("Events")
    ws_swimmers = spreadsheet.worksheet("Swimmers")
    ws_results  = spreadsheet.worksheet("Results")
    print(f"      Opened: {SPREADSHEET_NAME}")

    # ── Fetch existing keys ───────────────────────────────────────────────────
    print("[4/5] Fetching existing row keys ...")
    existing_event_ids:   Set[Tuple] = _existing_keys(ws_events,   ["event_id"])
    existing_swimmer_ids: Set[Tuple] = _existing_keys(ws_swimmers, ["swimmer_id"])
    existing_results:     Set[Tuple] = _existing_keys(ws_results,  ["event_id", "swimmer_id", "discipline"])
    print(f"      Existing — Events: {len(existing_event_ids)} | "
          f"Swimmers: {len(existing_swimmer_ids)} | Results: {len(existing_results)}")

    # ── Build new rows ────────────────────────────────────────────────────────
    print("[5/5] Preparing new rows ...")

    new_events:   List[List] = []
    new_swimmers: List[List] = []
    new_results:  List[List] = []

    seen_event_ids:   Set[str] = set()
    seen_swimmer_ids: Set[str] = set()
    # Track best time per (event_id, swimmer_id, discipline) to deduplicate within CSV
    best_time: Dict[Tuple, float] = {}
    result_rows: Dict[Tuple, Dict[str, str]] = {}

    for row in valid_rows:
        eid  = row.get("event_id",   "").strip()
        sid  = row.get("swimmer_id", "").strip()
        disc = row.get("discipline", "").strip()

        # Events
        ek = (eid,)
        if ek not in existing_event_ids and eid not in seen_event_ids:
            seen_event_ids.add(eid)
            new_events.append([
                eid,
                row.get("event_name", ""),
                row.get("date", ""),
                row.get("location", ""),
                now_str,
                "",  # modling_participant_count — filled separately
                row.get("pool", "50m"),
            ])

        # Swimmers
        sk = (sid,)
        if sk not in existing_swimmer_ids and sid not in seen_swimmer_ids:
            seen_swimmer_ids.add(sid)
            new_swimmers.append([
                sid,
                row.get("name", ""),
                row.get("birth_year", ""),
                row.get("club", ""),
            ])

        # Results — dedup by (eid, sid, disc); keep fastest time
        rk = (eid, sid, disc)
        if rk in existing_results:
            continue
        time_sec_str = row.get("time_sec", "")
        try:
            time_sec_val = float(time_sec_str)
        except ValueError:
            time_sec_val = float("inf")
        if rk not in best_time or time_sec_val < best_time[rk]:
            best_time[rk]   = time_sec_val
            result_rows[rk] = row

    for rk, row in result_rows.items():
        eid, sid, disc = rk
        new_results.append([
            eid,
            sid,
            disc,
            row.get("time_str",  ""),
            row.get("time_sec",  ""),
            now_str,
            SOURCE_LABEL,
            row.get("place",     ""),
            row.get("medal",     ""),
            row.get("age_group", ""),
        ])

    print(f"\n  New Events to insert:   {len(new_events)}")
    print(f"  New Swimmers to insert: {len(new_swimmers)}")
    print(f"  New Results to insert:  {len(new_results)}")

    if dry_run:
        print("\n[DRY-RUN] No writes performed. Remove --dry-run to upload.")
        return

    # ── Write in chunks ───────────────────────────────────────────────────────
    def _batch_append(ws: gspread.Worksheet, rows: List[List], label: str) -> None:
        if not rows:
            print(f"  {label}: nothing to insert.")
            return
        for i in range(0, len(rows), CHUNK_SIZE):
            chunk = rows[i:i + CHUNK_SIZE]
            ws.append_rows(chunk, value_input_option="USER_ENTERED")
            print(f"  {label}: inserted rows {i + 1}–{i + len(chunk)}")

    _batch_append(ws_events,   new_events,   "Events  ")
    _batch_append(ws_swimmers, new_swimmers, "Swimmers")
    _batch_append(ws_results,  new_results,  "Results ")

    print("\n✅ Upload complete.")
    print(f"   Events inserted:   {len(new_events)}")
    print(f"   Swimmers inserted: {len(new_swimmers)}")
    print(f"   Results inserted:  {len(new_results)}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Batch-upload historical SUM data to SwimmingResults_DB.")
    parser.add_argument(
        "--csv", default="SUM_Ergebnisse_2010_2026_Alle.csv",
        help="Path to the CSV file produced by generate_sum_report.py --mode history",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Validate and count rows without writing to Sheets",
    )
    args = parser.parse_args()

    upload(csv_path=args.csv, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
