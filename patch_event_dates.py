#!/usr/bin/env python3
"""
patch_event_dates.py
====================
One-shot script that fixes malformed date strings in the Events sheet.

Problem
-------
The historical backfill (upload_history_to_sheets.py) wrote raw event date
strings from the CSV directly into column C of the Events sheet, e.g.:
  "01.-02.04.2017"   "28.02.-01.03.2025"   "23.-24.05.2026"

The Streamlit dashboard expects "DD/MM/YYYY" (the format produced by GAS).
Any row with a non-standard date is parsed as NaT, so date pickers can never
show dates before ~2025 even though historical data exists.

What this script does
---------------------
1. Read all rows from the Events sheet.
2. For each row where column C (date) is NOT already "DD/MM/YYYY":
   • Extract all dd.mm.yyyy occurrences from the raw string.
   • Take the last one (= event end date).
   • Write "DD/MM/YYYY" back to that cell.
3. Batch-update only the changed cells (minimises API quota usage).

Usage
-----
    # Dry-run — show what would change, no writes:
    python3 patch_event_dates.py --dry-run

    # Live patch:
    python3 patch_event_dates.py
"""

import re
import sys
import json
import argparse
from pathlib import Path

import gspread
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SPREADSHEET_NAME = "SwimmingResults_DB"
TOKEN_FILE       = "oauth_token.json"
SCOPES           = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Column C (1-based index 3) holds the event date
DATE_COL_INDEX = 3  # 1-based

# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------
_DATE_ALREADY_OK = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_DATE_EXTRACT    = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")


def _normalise_date(raw: str) -> str | None:
    """
    Return "DD/MM/YYYY" extracted from a raw event date string.
    Returns None if the date is already in the correct format or cannot be parsed.
    """
    raw = raw.strip()
    if _DATE_ALREADY_OK.match(raw):
        return None  # already correct — no update needed
    matches = _DATE_EXTRACT.findall(raw)
    if not matches:
        return None  # unparseable — leave as-is
    d, m, y = matches[-1]
    return f"{int(d):02d}/{int(m):02d}/{y}"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _load_credentials() -> Credentials:
    token_path = Path(TOKEN_FILE)
    if not token_path.exists():
        sys.exit(
            f"[ERROR] {TOKEN_FILE} not found. "
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
        token_path.write_text(json.dumps({
            "token":         creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri":     creds.token_uri,
            "client_id":     creds.client_id,
            "client_secret": creds.client_secret,
            "scopes":        list(creds.scopes or SCOPES),
        }, indent=2))
    return creds


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def patch(dry_run: bool) -> None:
    print(f"\n{'[DRY-RUN] ' if dry_run else ''}Connecting to Google Sheets...")
    client      = gspread.authorize(_load_credentials())
    spreadsheet = client.open(SPREADSHEET_NAME)
    ws          = spreadsheet.worksheet("Events")

    # Read all values (including header row)
    all_values = ws.get_all_values()
    if not all_values:
        print("[ERROR] Events sheet is empty.")
        return

    header    = all_values[0]
    data_rows = all_values[1:]  # row index 0 = header = sheet row 1

    print(f"  Events sheet: {len(data_rows)} data rows (+ 1 header).")

    # Build list of (sheet_row_number, old_date, new_date) for rows that need fixing
    patches = []
    for i, row in enumerate(data_rows):
        sheet_row = i + 2  # +1 for 1-based, +1 for header row
        raw_date  = row[DATE_COL_INDEX - 1] if len(row) >= DATE_COL_INDEX else ""
        fixed     = _normalise_date(raw_date)
        if fixed is not None:
            patches.append((sheet_row, raw_date, fixed))

    if not patches:
        print("  Nothing to fix — all dates are already in DD/MM/YYYY format.")
        return

    print(f"\n  {len(patches)} row(s) need fixing:")
    for sheet_row, old, new in patches[:20]:  # preview first 20
        print(f"    Row {sheet_row:>4}:  \"{old}\"  →  \"{new}\"")
    if len(patches) > 20:
        print(f"    ... and {len(patches) - 20} more.")

    if dry_run:
        print("\n[DRY-RUN] No changes written.")
        return

    # Batch-update: build a list of Cell objects for a single API call
    cells = [
        gspread.Cell(row=sheet_row, col=DATE_COL_INDEX, value=new_date)
        for sheet_row, _, new_date in patches
    ]
    print(f"\n  Writing {len(cells)} cell(s)...")
    ws.update_cells(cells, value_input_option="RAW")
    print(f"  Done. {len(cells)} date(s) patched in the Events sheet.")
    print(
        "\n  IMPORTANT: The Streamlit dashboard caches data for 5 minutes.\n"
        "  Refresh the app (or wait 5 min) to see the updated date range."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fix raw event date strings in the Events sheet.")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    args = parser.parse_args()
    patch(dry_run=args.dry_run)
