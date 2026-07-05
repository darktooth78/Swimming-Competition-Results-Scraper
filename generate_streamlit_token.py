"""
generate_streamlit_token.py
===========================
One-time script to generate a Google OAuth refresh token for the Streamlit dashboard.

Run once:
    1. Save your OAuth Desktop client JSON as oauth_client.json next to this script
    2. venv/bin/python3 generate_streamlit_token.py
    3. Paste the printed TOML block into Streamlit Cloud secrets
    4. Delete streamlit_secret_token.json afterwards
"""

import json
import os
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

# Read-only scopes — the dashboard only reads the spreadsheet
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

CLIENT_SECRETS_FILE = "oauth_client.json"
OUTPUT_FILE         = "streamlit_secret_token.json"


def main():
    print("=" * 60)
    print("  Streamlit Dashboard — Google OAuth Token Generator")
    print("=" * 60)

    if not os.path.exists(CLIENT_SECRETS_FILE):
        print(f"\n✗ Missing {CLIENT_SECRETS_FILE}")
        print("  Save your OAuth Desktop client JSON as oauth_client.json next to this script.")
        sys.exit(1)

    print("\nOpening browser for Google OAuth consent...")
    print("Sign in as Martin (the account that owns SwimmingResults_DB)\n")

    flow  = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)

    # Read client_id and client_secret from the secrets file for the output token
    with open(CLIENT_SECRETS_FILE) as f:
        cs = json.load(f)["installed"]

    token_data = {
        "token":         creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri":     creds.token_uri,
        "client_id":     cs["client_id"],
        "client_secret": cs["client_secret"],
        "scopes":        list(creds.scopes) if creds.scopes else SCOPES,
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(token_data, f, indent=2)

    print(f"\n✓ Token saved to {OUTPUT_FILE}")
    print("\n" + "=" * 60)
    print("  Paste this into Streamlit Cloud → App settings → Secrets:")
    print("=" * 60)

    print('\n[gcp_oauth_token]')
    for k, v in token_data.items():
        if isinstance(v, list):
            items = ", ".join(f'"{s}"' for s in v)
            print(f'{k} = [{items}]')
        else:
            safe = str(v).replace('\\', '\\\\').replace('"', '\\"')
            print(f'{k} = "{safe}"')

    print("\n" + "=" * 60)
    print(f"  Token also saved in: {OUTPUT_FILE}")
    print("  ⚠️  Delete that file after pasting into Streamlit secrets!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
