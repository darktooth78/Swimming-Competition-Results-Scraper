"""
setup_google.py
===============
One-time automated setup for the SwimmingResults Google Workspace infrastructure.

What it does:
  1. OAuth browser auth (one click)
  2. Creates SwimmingResults_DB Google Sheets workbook
  3. Creates all 6 tabs with correct column headers
  4. Populates the Config tab with all values
  5. Creates the SwimmingResultsScraper Apps Script project (bound to the sheet)
  6. Uploads all 6 .gs files + appsscript.json

Usage:
  1. Save your OAuth Desktop client JSON as oauth_client.json next to this script
  2. venv/bin/python3 setup_google.py
"""

import json
import os
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import google.auth.transport.requests

# ---------------------------------------------------------------------------
# OAuth scopes
# ---------------------------------------------------------------------------
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/script.projects",
]

CLIENT_SECRETS_FILE = "oauth_client.json"
TOKEN_FILE          = "oauth_token.json"

# ---------------------------------------------------------------------------
# GAS file contents
# ---------------------------------------------------------------------------
GAS_DIR = Path(__file__).parent / "gas"


def load_gs(filename: str) -> str:
    return (GAS_DIR / filename).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Config tab data
# ---------------------------------------------------------------------------
CONFIG_ROWS = [
    ["club_id",                    "6614"],
    ["club_name_match",            "SU MöDLING"],
    ["max_parallel",               "100"],
    ["page_timeout",               "15"],
    ["max_retries",                "3"],
    ["retry_delays",               "1,2,4"],
    ["translation_Backstroke",     "Rücken"],
    ["translation_Breaststroke",   "Brust"],
    ["translation_Butterfly",      "Schmetterling"],
    ["translation_Freestyle",      "Freistil"],
    ["translation_Ind. Medley",    "Lagen"],
    ["translation_Medley",         "Lagen"],
    ["translation_Free",           "Freistil"],
]

TAB_HEADERS = {
    "Swimmers":     ["swimmer_id", "name", "birth_year", "club", "first_seen_event_id", "last_updated"],
    "Events":       ["event_id", "event_name", "date", "location", "last_updated", "modling_participant_count"],
    "Results":      ["event_id", "swimmer_id", "discipline", "time_str", "time_sec", "fetched_at", "source"],
    "Rescan_Queue": ["swimmer_id", "rescan_start", "rescan_end", "status", "submitted_at"],
    "Config":       ["key", "value"],
    "Log":          ["run_at", "events_checked", "events_new", "swimmers_discovered",
                     "results_added", "results_skipped", "errors", "rescans", "duration_sec", "notes"],
}

TAB_ORDER = ["Swimmers", "Events", "Results", "Rescan_Queue", "Config", "Log"]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def authenticate():
    from google.oauth2.credentials import Credentials

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        if creds and creds.valid:
            print("✓ Using cached OAuth token")
            return creds
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing OAuth token...")
            creds.refresh(google.auth.transport.requests.Request())
            _save_token(creds)
            return creds

    if not os.path.exists(CLIENT_SECRETS_FILE):
        print(f"\n✗ Missing {CLIENT_SECRETS_FILE}")
        print("  Save your OAuth Desktop client JSON as oauth_client.json next to this script.")
        sys.exit(1)

    print("\nOpening browser for Google OAuth consent...")
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)
    _save_token(creds)
    print("✓ OAuth consent granted and token saved")
    return creds


def _save_token(creds):
    with open(TOKEN_FILE, "w") as f:
        f.write(creds.to_json())


# ---------------------------------------------------------------------------
# Step 1 — Create Sheets workbook
# ---------------------------------------------------------------------------
def create_spreadsheet(sheets_svc) -> str:
    print("\n[1/4] Creating SwimmingResults_DB spreadsheet...")

    ss    = sheets_svc.spreadsheets().create(body={"properties": {"title": "SwimmingResults_DB"}}).execute()
    ss_id = ss["spreadsheetId"]
    print(f"  ✓ Created: https://docs.google.com/spreadsheets/d/{ss_id}")

    ss_meta     = sheets_svc.spreadsheets().get(spreadsheetId=ss_id).execute()
    default_sid = ss_meta["sheets"][0]["properties"]["sheetId"]

    add_sheet_requests = [
        {"updateSheetProperties": {"properties": {"sheetId": default_sid, "title": TAB_ORDER[0]}, "fields": "title"}}
    ]
    for tab_name in TAB_ORDER[1:]:
        add_sheet_requests.append({"addSheet": {"properties": {"title": tab_name}}})

    sheets_svc.spreadsheets().batchUpdate(
        spreadsheetId=ss_id, body={"requests": add_sheet_requests}
    ).execute()
    print(f"  ✓ Created {len(TAB_ORDER)} tabs: {', '.join(TAB_ORDER)}")
    return ss_id


# ---------------------------------------------------------------------------
# Step 2 — Write headers and Config data
# ---------------------------------------------------------------------------
def write_headers_and_config(sheets_svc, ss_id: str):
    print("\n[2/4] Writing headers and Config values...")

    ss_meta      = sheets_svc.spreadsheets().get(spreadsheetId=ss_id).execute()
    sheet_id_map = {s["properties"]["title"]: s["properties"]["sheetId"] for s in ss_meta["sheets"]}

    value_updates = [{"range": f"{tab}!A1", "values": [hdrs]} for tab, hdrs in TAB_HEADERS.items()]
    value_updates.append({"range": "Config!A2", "values": CONFIG_ROWS})

    sheets_svc.spreadsheets().values().batchUpdate(
        spreadsheetId=ss_id,
        body={"valueInputOption": "RAW", "data": value_updates}
    ).execute()

    bold_requests = []
    for tab_name in TAB_ORDER:
        sid = sheet_id_map.get(tab_name)
        if sid is None:
            continue
        bold_requests.append({
            "repeatCell": {
                "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
                           "startColumnIndex": 0, "endColumnIndex": len(TAB_HEADERS[tab_name])},
                "cell": {"userEnteredFormat": {
                    "textFormat": {"bold": True},
                    "backgroundColor": {"red": 0.85, "green": 0.90, "blue": 0.98}
                }},
                "fields": "userEnteredFormat(textFormat,backgroundColor)"
            }
        })
    if bold_requests:
        sheets_svc.spreadsheets().batchUpdate(spreadsheetId=ss_id, body={"requests": bold_requests}).execute()

    print(f"  ✓ Headers written to all {len(TAB_ORDER)} tabs")
    print(f"  ✓ Config tab populated with {len(CONFIG_ROWS)} key/value rows")


# ---------------------------------------------------------------------------
# Step 3 — Create Apps Script project
# ---------------------------------------------------------------------------
def create_apps_script(script_svc, ss_id: str) -> str:
    print("\n[3/4] Creating SwimmingResultsScraper Apps Script project...")
    project   = script_svc.projects().create(body={"title": "SwimmingResultsScraper", "parentId": ss_id}).execute()
    script_id = project["scriptId"]
    print(f"  ✓ Created script: https://script.google.com/d/{script_id}/edit")
    return script_id


# ---------------------------------------------------------------------------
# Step 4 — Upload all .gs files
# ---------------------------------------------------------------------------
def upload_gs_files(script_svc, script_id: str):
    print("\n[4/4] Uploading GAS source files...")

    files = [
        {"name": "appsscript", "type": "JSON",      "source": json.dumps(json.loads(load_gs("appsscript.json")), indent=2)},
        {"name": "Config",     "type": "SERVER_JS",  "source": load_gs("Config.gs")},
        {"name": "Fetch",      "type": "SERVER_JS",  "source": load_gs("Fetch.gs")},
        {"name": "Parser",     "type": "SERVER_JS",  "source": load_gs("Parser.gs")},
        {"name": "Sheets",     "type": "SERVER_JS",  "source": load_gs("Sheets.gs")},
        {"name": "Import",     "type": "SERVER_JS",  "source": load_gs("Import.gs")},
        {"name": "Code",       "type": "SERVER_JS",  "source": load_gs("Code.gs")},
    ]
    script_svc.projects().updateContent(
        scriptId=script_id, body={"scriptId": script_id, "files": files}
    ).execute()
    for f in files:
        label = "json" if f["type"] == "JSON" else "gs"
        print(f"  ✓ Uploaded {f['name']}.{label}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("  SwimmingResults Google Workspace Setup")
    print("=" * 60)
    print("  Place your OAuth Desktop client JSON as oauth_client.json")
    print("  next to this script before running.")
    print("=" * 60)

    creds      = authenticate()
    sheets_svc = build("sheets", "v4", credentials=creds)
    script_svc = build("script", "v1", credentials=creds)

    try:
        ss_id     = create_spreadsheet(sheets_svc)
        write_headers_and_config(sheets_svc, ss_id)
        script_id = create_apps_script(script_svc, ss_id)
        upload_gs_files(script_svc, script_id)
    except HttpError as e:
        print(f"\n✗ Google API error: {e}")
        print(f"  Details: {e.error_details}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("  ✅  Setup complete!")
    print("=" * 60)
    print(f"\n  Spreadsheet : https://docs.google.com/spreadsheets/d/{ss_id}")
    print(f"  Apps Script : https://script.google.com/d/{script_id}/edit")
    print("""
  Next steps (browser, once):
  1. Open the Apps Script link above
  2. Run testReadConfig → click Allow in the OAuth consent dialog
  3. Run testReadConfig, testFetchHtml, testParser, testSheets, testMain → all should log PASS
  4. Run setupTrigger() → registers the nightly 02:00 cron
  5. Open ⏰ Triggers and confirm one trigger is listed
""")


if __name__ == "__main__":
    main()
