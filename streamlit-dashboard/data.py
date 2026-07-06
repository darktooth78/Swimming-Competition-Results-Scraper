"""
data.py
=======
Google Sheets data loaders for the Streamlit dashboard.
All functions are cached with a 5-minute TTL.

Auth: OAuth refresh token stored in st.secrets["gcp_oauth_token"].
      Run generate_streamlit_token.py once locally to produce the token,
      then paste the output TOML block into Streamlit Cloud secrets.
      (Migrating to a Service Account later only requires swapping this
       _get_client() function — nothing else changes.)

Sheets structure:
  Swimmers:  swimmer_id | name | birth_year | club | first_seen_event_id | last_updated
  Events:    event_id | event_name | date | location | last_updated | modling_participant_count | pool
  Results:   event_id | swimmer_id | discipline | time_str | time_sec | fetched_at | source
  Log:       run_at | events_checked | events_new | swimmers_discovered | results_added |
             results_skipped | errors | rescans | duration_sec | notes
"""

import re
import streamlit as st
import gspread
import pandas as pd
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

SPREADSHEET_NAME = "SwimmingResults_DB"


@st.cache_resource(show_spinner=False)
def _get_client() -> gspread.Client:
    """
    Build a gspread client from the OAuth refresh token stored in Streamlit secrets.

    Secrets block (in Streamlit Cloud → App settings → Secrets):
        [gcp_oauth_token]
        token         = "..."
        refresh_token = "..."
        token_uri     = "https://oauth2.googleapis.com/token"
        client_id     = "..."
        client_secret = "..."
        scopes        = ["https://www.googleapis.com/auth/spreadsheets.readonly", ...]
    """
    t = st.secrets["gcp_oauth_token"]

    creds = Credentials(
        token         = t["token"],
        refresh_token = t["refresh_token"],
        token_uri     = t["token_uri"],
        client_id     = t["client_id"],
        client_secret = t["client_secret"],
        scopes        = list(t["scopes"]),
    )

    # Refresh if expired (happens after ~1 hour; refresh_token keeps it alive)
    if not creds.valid:
        creds.refresh(Request())

    return gspread.authorize(creds)


@st.cache_resource(show_spinner=False)
def _get_spreadsheet():
    """Open and cache the workbook handle."""
    return _get_client().open(SPREADSHEET_NAME)


def _sheet_to_df(tab_name: str) -> pd.DataFrame:
    """Read a sheet tab and return a DataFrame with the first row as header."""
    ws = _get_spreadsheet().worksheet(tab_name)
    records = ws.get_all_records(numericise_ignore=["all"])
    return pd.DataFrame(records)


# Relay placeholder pattern — "1. MANNSCHAFT", "2. TEAM", etc.
_RELAY_NAME_RE = re.compile(r"^\d+\.\s+(MANNSCHAFT|TEAM)\b", re.IGNORECASE)


@st.cache_data(ttl=300, show_spinner=False)
def load_swimmers() -> pd.DataFrame:
    """
    Return real swimmers from the Swimmers tab (relay placeholders excluded).
    Columns: swimmer_id, name, birth_year, club, first_seen_event_id, last_updated
    """
    df = _sheet_to_df("Swimmers")
    if df.empty:
        return df
    df["swimmer_id"] = df["swimmer_id"].astype(str)
    df["birth_year"] = pd.to_numeric(df["birth_year"], errors="coerce")
    # Drop relay team placeholders — they have no individual participant page
    df = df[~df["name"].str.match(_RELAY_NAME_RE, na=False)].reset_index(drop=True)
    return df


@st.cache_data(ttl=300, show_spinner=False)
def load_events() -> pd.DataFrame:
    """
    Return the Events tab as a DataFrame.
    Columns: event_id, event_name, date, location, last_updated, modling_participant_count, pool
    """
    df = _sheet_to_df("Events")
    if df.empty:
        return df
    df["event_id"] = df["event_id"].astype(str)
    df["date_parsed"] = pd.to_datetime(df["date"], format="%d/%m/%Y", errors="coerce")
    # Ensure pool column exists (backwards-compatible with sheets that predate v2.3)
    if "pool" not in df.columns:
        df["pool"] = "50m"
    else:
        df["pool"] = df["pool"].fillna("50m").replace("", "50m")
    return df


@st.cache_data(ttl=300, show_spinner=False)
def load_results() -> pd.DataFrame:
    """
    Return the Results tab as a DataFrame, enriched with event and swimmer metadata.
    Columns: event_id, swimmer_id, discipline, time_str, time_sec, fetched_at, source,
             + event_name, date, location, date_parsed, name, birth_year, club
    """
    df = _sheet_to_df("Results")
    if df.empty:
        return df

    df["event_id"]   = df["event_id"].astype(str)
    df["swimmer_id"] = df["swimmer_id"].astype(str)
    df["time_sec"]   = pd.to_numeric(df["time_sec"], errors="coerce")

    # Join event metadata (including pool size)
    events = load_events()[["event_id", "event_name", "date", "location", "date_parsed", "pool"]]
    df = df.merge(events, on="event_id", how="left")

    # Join swimmer metadata
    swimmers = load_swimmers()[["swimmer_id", "name", "birth_year", "club"]]
    df = df.merge(swimmers, on="swimmer_id", how="left")

    return df


@st.cache_data(ttl=300, show_spinner=False)
def load_log() -> pd.DataFrame:
    """
    Return the Log tab as a DataFrame.
    Columns: run_at, events_checked, events_new, swimmers_discovered, results_added,
             results_skipped, errors, rescans, duration_sec, notes
    """
    df = _sheet_to_df("Log")
    if df.empty:
        return df
    df["run_at"] = pd.to_datetime(df["run_at"], errors="coerce")
    return df


def get_last_run_label() -> str:
    """Return a human-readable 'last run' label from the Log tab."""
    try:
        log = load_log()
        if log.empty or "run_at" not in log.columns:
            return "—"
        last = log["run_at"].max()
        if pd.isna(last):
            return "—"
        return last.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return "—"


def compute_personal_bests(results_df: pd.DataFrame) -> pd.DataFrame:
    """
    Add an 'is_pb' boolean column — True where time_sec equals the minimum
    for that (swimmer_id, discipline) combination.
    """
    if results_df.empty:
        return results_df

    pb_df = (
        results_df
        .dropna(subset=["time_sec"])
        .groupby(["swimmer_id", "discipline"], as_index=False)["time_sec"]
        .min()
        .rename(columns={"time_sec": "pb_sec"})
    )
    merged = results_df.merge(pb_df, on=["swimmer_id", "discipline"], how="left")
    merged["is_pb"] = merged["time_sec"] == merged["pb_sec"]
    return merged
