"""
Swimming Competition Results Scraper
====================================

A multi-threaded web scraper for extracting swimming competition results from myresults.eu.

Features:
- Multi-threaded scraping with configurable workers (20 parallel)
- Pure requests-based fetching (no Selenium/Chrome overhead)
- Automatic retry with exponential backoff
- Thread-safe CSV writing with dynamic column creation
- Input validation and error handling
- Progress tracking and GUI interface
- Configurable via config.json
- Event date and location extraction with caching
- Discipline name normalisation: keeps only "NNm Stroke", strips age-group/heat suffixes
- Fastest time kept when the same discipline appears under multiple suffix variants
- CSV rows sorted by date descending (newest event first)
- Discipline columns sorted by stroke order (Freistil → Brust → Schmetterling → Rücken → Lagen)
  and by distance ascending within each stroke (25m, 50m, 100m, …)

Architecture note:
  myresults.eu pages are fully server-side rendered — all data is present in the
  initial HTML response. No JavaScript execution or browser automation is needed.
  A simple requests.get() + regex parse is 20-30x faster than Selenium.

Author: Swimming Results Team
Version: 2.2.0
"""

import re
import time
import threading
import csv
import os
import logging
import json
from datetime import datetime
from typing import Optional, Tuple, Dict, Any
import customtkinter as ctk
from tkinter import filedialog
from concurrent.futures import ThreadPoolExecutor
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ==============================
# 🔧 LOGGING SETUP
# ==============================
log_filename = f"scraper_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==============================
# 🔧 CONFIGURATION LOADING
# ==============================

def load_config() -> Dict[str, Any]:
    """
    Load configuration from config.json or use defaults.

    Returns:
        Dictionary containing all configuration settings
    """
    default_config = {
        "translations": {
            "Backstroke": "Rücken",
            "Breaststroke": "Brust",
            "Butterfly": "Schmetterling",
            "Freestyle": "Freistil",
            "Ind. Medley": "Lagen",
            "Medley": "Lagen",
            "Free": "Freistil"
        },
        "timeouts": {
            "element_wait": 10,
            "cookie_button": 3,
            "page_load": 15
        },
        "performance": {
            "max_workers": 20,
            "page_load_delay": 0,
            "disable_images": True
        },
        "retry": {
            "max_attempts": 3,
            "delays": [1, 2, 4]
        },
        "csv": {
            "delimiter": ";",
            "encoding": "utf-8-sig"
        },
        "gui": {
            "window_width": 600,
            "window_height": 700,
            "log_height": 200
        }
    }

    config_file = "config.json"
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                user_config = json.load(f)
                # Merge with defaults
                for key in default_config:
                    if key in user_config:
                        if isinstance(default_config[key], dict):
                            default_config[key].update(user_config[key])
                        else:
                            default_config[key] = user_config[key]
                logger.info("Configuration loaded from config.json")
        except Exception as e:
            logger.warning(f"Could not load config.json: {e}. Using defaults.")
    else:
        try:
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=4, ensure_ascii=False)
            logger.info("Created default config.json")
        except Exception as e:
            logger.warning(f"Could not create config.json: {e}")

    return default_config

# Load configuration
CONFIG = load_config()

# ==============================
# 🔧 CONSTANTS (from config)
# ==============================
TRANSLATIONS = CONFIG["translations"]
PAGE_LOAD_TIMEOUT = CONFIG["timeouts"]["page_load"]
MAX_WORKERS = CONFIG["performance"]["max_workers"]
MAX_RETRIES = CONFIG["retry"]["max_attempts"]
RETRY_DELAYS = CONFIG["retry"]["delays"]

# URL template
MYRESULTS_URL_TEMPLATE = "https://myresults.eu/de-AT/Meets/Recent/{event}/Participant/{participant}"

# HTTP headers that mimic a real browser (required to avoid 403/redirect)
HTTP_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'de-AT,de;q=0.9,en;q=0.7',
}

# ==============================
# 🔧 PRE-COMPILED REGEX PATTERNS
# ==============================
# Discipline normalisation
RELAY_PATTERN    = re.compile(r"4x", re.IGNORECASE)
PREFIX_PATTERN   = re.compile(r"^\d+\s*-\s*")
GENDER_PATTERN   = re.compile(r"\b(Men|Women|Mixed|Herren|Damen)\b", re.IGNORECASE)
HEAT_PATTERN     = re.compile(r"\b(Preliminary|Vorlauf|Heats|Entscheidung)\b", re.IGNORECASE)
FINAL_PATTERN    = re.compile(r"\b([AB]-)?(Final|Finale)\b", re.IGNORECASE)
AGE_PATTERN      = re.compile(r"\bAK\s*\d+.*", re.IGNORECASE)
YOUNGER_PATTERN  = re.compile(r"\bund\s+jünger\b", re.IGNORECASE)
WHITESPACE_PATTERN = re.compile(r"\s+")
# Strip optional suffixes after "NNm Discipline" — keeps only distance + stroke
# Matches: leading digits + optional unit (m/M) + whitespace + one word (stroke)
DISCIPLINE_CORE_PATTERN = re.compile(
    r"^(\d+\s*[mM]?\s+\S+)",
    re.IGNORECASE
)
# Time validation
TIME_FORMAT_PATTERN = re.compile(r'^(\d{1,2}:)?\d{1,2}\.\d{2}$')
# Date parsing
DATE_PATTERN     = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
# Club cleanup
AUSTRIA_PATTERN  = re.compile(r"\bAUT\s*\(Austria\).*")

# HTML parsing
TAG_STRIP_PATTERN = re.compile(r'<[^>]+>')
# Primary time column: hidden on xs, visible on sm+, no "points" class suffix
TIME_COL_PATTERN = re.compile(
    r'<div[^>]*class="hidden-xs[^"]*myresults_content_divtable_right"[^>]*>\s*([^<\s][^<]*?)\s*</div>'
)
# Discipline link (anchor may contain inner tags like <i>)
DISC_ANCHOR_PATTERN = re.compile(r'<a[^>]*href="[^"]*"[^>]*>(.*?)</a>', re.DOTALL)
# "Ergebnisse" section header row
ERGEBNISSE_HEADER_PATTERN = re.compile(
    r'<div[^>]*class="row myresults_content_divtablerow\s+myresults_content_divtablerow_header[^"]*"[^>]*>'
    r'[^<]*<div[^>]*>[^<]*[Ee]rgebnisse[^<]*</div>',
    re.DOTALL
)
# Participant details table
PERSON_PATTERN = re.compile(
    r'myresults_personendetails_header[^>]*>\s*([^<]+?)\s*</td>.*?'
    r'Jahrg\.[^<]*</td>\s*<td[^>]*>\s*(\d{4})\s*</td>.*?'
    r'Verein[^<]*</td>\s*<td[^>]*>(.*?)</td>',
    re.DOTALL
)
# Event name + date + location from page header paragraph
MEETNAME2_PATTERN = re.compile(r'class="[^"]*myresults_meetname2[^"]*"[^>]*>\s*([^<]+)')
# Fallback: nav3a paragraph
NAV3A_PATTERN = re.compile(
    r'class="[^"]*myresults_nav3a[^"]*"[^>]*>.*?<p[^>]*>([^<]+)</p>',
    re.DOTALL
)

# ==============================
# 🔧 GLOBAL STATE
# ==============================
stop_scraping = False
csv_lock = threading.Lock()

# Shared requests Session (connection-pool reuse across all threads)
_http_session: Optional[requests.Session] = None
_session_lock = threading.Lock()


def get_http_session() -> requests.Session:
    """Return (or lazily create) a shared requests.Session with connection pooling."""
    global _http_session
    with _session_lock:
        if _http_session is None:
            session = requests.Session()
            session.headers.update(HTTP_HEADERS)
            # urllib3 retry on connection errors only (not HTTP 4xx/5xx)
            retry = Retry(
                total=MAX_RETRIES,
                backoff_factor=1,
                status_forcelist=[500, 502, 503, 504],
                allowed_methods=["GET"],
            )
            adapter = HTTPAdapter(
                pool_connections=MAX_WORKERS + 2,
                pool_maxsize=MAX_WORKERS + 2,
                max_retries=retry,
            )
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            _http_session = session
        return _http_session


def reset_http_session() -> None:
    """Close and reset the shared session (called on STOP)."""
    global _http_session
    with _session_lock:
        if _http_session is not None:
            try:
                _http_session.close()
            except Exception:
                pass
            _http_session = None


# ==============================
# 📅 EVENT METADATA CACHE
# ==============================
event_metadata_cache: Dict[int, Dict[str, str]] = {}
metadata_cache_lock = threading.Lock()

# ==============================
# 🧠 HELPER FUNCTIONS
# ==============================

def strip_tags(s: str) -> str:
    return TAG_STRIP_PATTERN.sub(' ', s)


def clean_text(s: str) -> str:
    return WHITESPACE_PATTERN.sub(' ', strip_tags(s)).strip()


def parse_last_date(raw_date_str: str) -> str:
    """
    Extract and format the last date from a date range string.
    Handles "DD.MM.YYYY - DD.MM.YYYY" → "DD/MM/YYYY".
    """
    try:
        if "-" in raw_date_str:
            last_part = raw_date_str.split("-")[-1].strip()
        else:
            last_part = raw_date_str.strip()
        match = DATE_PATTERN.search(last_part)
        if match:
            return f"{match.group(1)}/{match.group(2)}/{match.group(3)}"
        return raw_date_str
    except Exception as e:
        logger.warning(f"Date parsing failed for '{raw_date_str}': {e}")
        return raw_date_str


def validate_time_format(time_str: str) -> bool:
    return bool(TIME_FORMAT_PATTERN.match(time_str))


def time_to_seconds(time_str: str) -> float:
    try:
        time_str = time_str.replace(",", ".")
        if ":" in time_str:
            parts = time_str.split(":")
            return (float(parts[0]) * 60) + float(parts[1])
        return float(time_str)
    except Exception as e:
        logger.warning(f"Time conversion failed for '{time_str}': {e}")
        return 999999.0


def normalize_discipline(raw_name: str) -> Optional[str]:
    """
    Normalize swimming discipline name by removing metadata.
    Returns None for relay events (contains "4x").

    Discipline names follow the scheme "NNm Stroke [optional extras]"
    (e.g. "50m Freistil Kinder" or "100m Backstroke AK 12").
    Only the first two tokens (distance + stroke) are kept so that the
    same event under different age groups or heats maps to one column.
    The "keep fastest time" logic in parse_results_from_html then
    ensures only the best time per discipline is retained.
    """
    if RELAY_PATTERN.search(raw_name):
        return None
    name = PREFIX_PATTERN.sub("", raw_name).strip()
    name = GENDER_PATTERN.sub("", name)
    name = HEAT_PATTERN.sub("", name)
    name = FINAL_PATTERN.sub("", name)
    name = AGE_PATTERN.sub("", name)
    name = YOUNGER_PATTERN.sub("", name)
    for eng, ger in TRANSLATIONS.items():
        if eng in name:
            name = name.replace(eng, ger)
    name = WHITESPACE_PATTERN.sub(" ", name).strip().strip("- ")
    # Keep only "NNm Stroke" — drop anything after the second token
    core_m = DISCIPLINE_CORE_PATTERN.match(name)
    if core_m:
        name = core_m.group(1).strip()
    return name if name else None


def validate_participant_id(pid: str) -> Tuple[bool, str]:
    if not pid or not pid.strip():
        return False, "Participant ID cannot be empty"
    if not pid.isdigit():
        return False, "Participant ID must be numeric"
    if len(pid) < 3 or len(pid) > 10:
        return False, "Participant ID must be 3-10 digits"
    return True, ""


def validate_event_range(start: str, end: str) -> Tuple[bool, str]:
    try:
        start_num = int(start)
        end_num = int(end)
    except ValueError:
        return False, "Event numbers must be integers"
    if start_num < 1:
        return False, "Start event must be positive"
    if end_num < start_num:
        return False, "End event must be >= start event"
    if end_num - start_num > 1000:
        return False, "Range too large (max 1000 events). Consider splitting."
    return True, ""


def validate_file_path(path: str) -> Tuple[bool, str]:
    if not path or not path.strip():
        return False, "Please select output file"
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        return False, f"Directory does not exist: {directory}"
    if os.path.exists(path):
        if not os.access(path, os.W_OK):
            return False, "File is not writable (may be open in Excel)"
    else:
        parent_dir = directory if directory else "."
        if not os.access(parent_dir, os.W_OK):
            return False, f"Cannot write to directory: {parent_dir}"
    return True, ""


# ==============================
# 🌐 HTML PARSING
# ==============================

def fetch_html(url: str) -> Optional[str]:
    """
    Fetch a URL and return the response HTML, or None on failure.
    Uses the shared connection-pooled requests.Session.
    """
    try:
        session = get_http_session()
        resp = session.get(url, timeout=PAGE_LOAD_TIMEOUT)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        logger.warning(f"HTTP fetch failed for {url}: {e}")
        return None


def parse_metadata_from_html(html: str, event_id: int) -> Dict[str, str]:
    """
    Extract event name, date, and location from page HTML.

    The page header contains a paragraph like:
      "53. Internationales Swimcity Wels Meeting (23.-24.05.2026) - Welldorado Wels"
    This is parsed directly without JavaScript.
    """
    metadata = {"event": "Unknown", "date": "Unknown", "location": "Unknown"}

    # Try meetname2 paragraph (most reliable)
    m = MEETNAME2_PATTERN.search(html)
    raw = ""
    if m:
        raw = m.group(1).strip()
    else:
        # Fallback: nav3a paragraph
        m2 = NAV3A_PATTERN.search(html)
        if m2:
            raw = m2.group(1).strip()

    if raw:
        # Pattern: "Event Name (Date) - Location"
        match = re.match(r'^(.+?)\s*\((.+?)\)\s*-\s*(.+)$', raw)
        if match:
            metadata["event"] = match.group(1).strip()
            metadata["date"] = parse_last_date(match.group(2).strip())
            metadata["location"] = match.group(3).strip()
            logger.debug(
                f"Event {event_id} metadata: {metadata['event']} | "
                f"{metadata['date']} | {metadata['location']}"
            )

    # Cache
    with metadata_cache_lock:
        event_metadata_cache[event_id] = metadata

    return metadata


def parse_participant_from_html(html: str) -> Tuple[str, str, str]:
    """
    Extract participant name, birth year, and club from page HTML.

    Returns ("Unknown", "Unknown", "Unknown") if extraction fails.
    """
    p_name, p_year, p_club = "Unknown", "Unknown", "Unknown"
    m = PERSON_PATTERN.search(html)
    if m:
        p_name = clean_text(m.group(1))
        p_year = m.group(2)
        raw_club = clean_text(m.group(3)).split('>>')[0].strip()
        p_club = AUSTRIA_PATTERN.sub("", raw_club).strip()
    return p_name, p_year, p_club


def parse_results_from_html(html: str) -> Dict[str, Dict[str, Any]]:
    """
    Extract swimming results from page HTML.

    Finds the "Ergebnisse" section and parses each result row.
    Returns dict: {discipline_name: {"str": time_string, "sec": float}}
    Keeps fastest time per discipline across multiple heats.
    """
    temp_results: Dict[str, Dict[str, Any]] = {}

    # Find position of Ergebnisse header
    ergebnisse_match = ERGEBNISSE_HEADER_PATTERN.search(html)
    if not ergebnisse_match:
        logger.debug("No 'Ergebnisse' section found in HTML")
        return temp_results

    # Only parse HTML after the Ergebnisse header
    results_html = html[ergebnisse_match.end():]

    # Split into row chunks — each result row is odd or even
    row_splits = re.split(
        r'(?=<div[^>]*class="row myresults_content_divtablerow\s+myresults_content_divtablerow_(?:odd|even))',
        results_html
    )

    for chunk in row_splits:
        if not chunk.strip():
            continue

        # Extract discipline name from anchor (strip inner tags like <i>)
        anchor_m = DISC_ANCHOR_PATTERN.search(chunk)
        if not anchor_m:
            continue
        disc_raw = clean_text(anchor_m.group(1))
        disc_clean = normalize_discipline(disc_raw)
        if not disc_clean:
            continue

        # Extract time from the primary right-aligned column
        # (hidden-xs, visible on sm — this is the "time" col, not points)
        time_m = TIME_COL_PATTERN.search(chunk)
        if not time_m:
            continue
        time_str = time_m.group(1).strip().replace(",", ".")

        if not validate_time_format(time_str):
            logger.debug(f"Skipping invalid time format: {time_str!r} for {disc_clean!r}")
            continue

        sec = time_to_seconds(time_str)
        if disc_clean not in temp_results or sec < temp_results[disc_clean]["sec"]:
            temp_results[disc_clean] = {"str": time_str, "sec": sec}

    return temp_results


# ==============================
# 💾 CSV FILE HANDLING (THREAD-SAFE)
# ==============================

# Stroke order for discipline column sorting (index = priority; lower = earlier)
_STROKE_ORDER = ["freistil", "brust", "schmetterling", "rücken", "lagen"]


def _discipline_sort_key(col_name: str) -> tuple:
    """
    Sort key for discipline column headers.
    Primary:   stroke rank (Freistil=0, Brust=1, Schmetterling=2, Rücken=3, Lagen=4, other=5)
    Secondary: distance in metres (numeric, ascending)
    Discipline names follow "NNm Stroke" after normalisation.
    """
    parts = col_name.strip().split()
    # Extract numeric distance (strip trailing non-digit chars like 'm')
    try:
        distance = int(re.sub(r"[^\d]", "", parts[0]))
    except (IndexError, ValueError):
        distance = 9999

    stroke = parts[1].lower() if len(parts) > 1 else ""
    try:
        stroke_rank = _STROKE_ORDER.index(stroke)
    except ValueError:
        stroke_rank = len(_STROKE_ORDER)  # unknown strokes sort last

    return (stroke_rank, distance)


def _sort_discipline_columns(discipline_cols: list) -> list:
    """Return discipline column names sorted by stroke order then distance."""
    return sorted(discipline_cols, key=_discipline_sort_key)


def _sort_key_date_desc(row: list) -> tuple:
    """
    Sort key for CSV rows: parse "DD/MM/YYYY" from column 0 (Date).
    Returns a tuple that sorts descending (negate year/month/day).
    Rows with unparseable dates sort last.
    """
    try:
        d, m, y = row[0].split("/")
        return (-int(y), -int(m), -int(d))
    except Exception:
        return (0, 0, 0)


def save_to_csv(meta_data: dict, results: dict, log_func, full_path: str) -> None:
    """Speichert Daten Thread-Sicher in die CSV Datei."""
    with csv_lock:
        static_headers = ["Date", "Event Name", "Location", "ID", "Name", "Year", "Club"]
        file_exists = os.path.isfile(full_path)
        current_headers = []
        existing_rows = []

        try:
            if file_exists:
                with open(full_path, 'r', newline='', encoding='utf-8-sig') as f:
                    reader = csv.reader(f, delimiter=';')
                    try:
                        current_headers = next(reader)
                        existing_rows = list(reader)
                    except StopIteration:
                        current_headers = static_headers
            else:
                current_headers = static_headers
        except (PermissionError, IOError, OSError) as e:
            log_func(f"❌ FEHLER: Datei-Zugriff verweigert! {e}")
            log_func("   Bitte Excel schließen oder Datei entsperren.")
            logger.error(f"CSV read failed: {e}", exc_info=True)
            return
        except Exception as e:
            log_func(f"⚠️ Fehler beim Lesen: {e}")
            logger.error(f"Unexpected CSV read error: {e}", exc_info=True)
            current_headers = static_headers

        new_disciplines = [d for d in results.keys() if d not in current_headers]

        try:
            static_count = 7  # Date, Event Name, Location, ID, Name, Year, Club
            if new_disciplines:
                log_func(f"   ✨ Neue Spalten: {new_disciplines}")
                current_headers.extend(new_disciplines)

            # Always re-sort discipline columns (stroke order + distance)
            discipline_cols = _sort_discipline_columns(current_headers[static_count:])
            ordered_headers = current_headers[:static_count] + discipline_cols

            # Rebuild every existing row to match the new column order
            def _reorder_row(row: list) -> list:
                # Map old header → cell value (pad if row is short)
                old_map = {current_headers[i]: row[i] if i < len(row) else ""
                           for i in range(len(current_headers))}
                return [old_map.get(h, "") for h in ordered_headers]

            existing_rows = [_reorder_row(r) for r in existing_rows]

            # Build new row using the final ordered headers
            new_row = [
                meta_data["date"], meta_data["event"], meta_data["location"],
                meta_data["id"], meta_data["name"], meta_data["year"], meta_data["club"]
            ]
            for header in ordered_headers[static_count:]:
                new_row.append(results.get(header, ""))

            # Pad new row to full width
            while len(new_row) < len(ordered_headers):
                new_row.append("")

            all_rows = existing_rows + [new_row]
            # Sort descending by date (column 0: "DD/MM/YYYY")
            all_rows.sort(key=_sort_key_date_desc)

            with open(full_path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f, delimiter=';')
                writer.writerow(ordered_headers)
                writer.writerows(all_rows)

            log_func(f"💾 Gespeichert (Event {meta_data['event']})")

        except (PermissionError, IOError, OSError) as e:
            log_func(f"❌ FEHLER: Zugriff verweigert! {e}")
            log_func("   Bitte Excel schließen oder Schreibrechte prüfen.")
            logger.error(f"CSV write failed: {e}", exc_info=True)
        except Exception as e:
            log_func(f"❌ Unerwarteter Fehler beim Speichern: {e}")
            logger.error(f"Unexpected CSV write error: {e}", exc_info=True)


# ==============================
# 🧠 SCRAPER LOGIC
# ==============================

def process_single_event(event_number: int, current_id: str, log_func, full_path: str) -> None:
    """
    Fetch and process a single event/participant page.

    Uses pure HTTP (requests) instead of Selenium — no browser overhead.
    Typical latency: ~0.15-0.3s per request vs ~3-5s with Chrome.
    """
    global stop_scraping
    if stop_scraping:
        return

    url = MYRESULTS_URL_TEMPLATE.format(event=event_number, participant=current_id)

    for attempt in range(MAX_RETRIES):
        if stop_scraping:
            return
        html = fetch_html(url)
        if html is not None:
            break
        delay = RETRY_DELAYS[attempt] if attempt < len(RETRY_DELAYS) else RETRY_DELAYS[-1]
        logger.warning(f"Event {event_number} attempt {attempt + 1} failed. Retrying in {delay}s...")
        time.sleep(delay)
    else:
        log_func(f"❌ Event {event_number}: Fetch failed after {MAX_RETRIES} attempts")
        return

    try:
        # --- Participant info ---
        p_name, p_year, p_club = parse_participant_from_html(html)
        if p_name == "Unknown" and p_club == "Unknown":
            # Participant not found at this event — skip silently
            return

        # --- Event metadata (name, date, location) ---
        # Check cache first
        with metadata_cache_lock:
            cached = event_metadata_cache.get(event_number)

        if cached:
            meta = dict(cached)
        else:
            meta = parse_metadata_from_html(html, event_number)

        meta["id"] = current_id
        meta["name"] = p_name
        meta["year"] = p_year
        meta["club"] = p_club

        # --- Results ---
        temp_results = parse_results_from_html(html)
        final_res = {k: v["str"] for k, v in temp_results.items()}

        if final_res:
            save_to_csv(meta, final_res, log_func, full_path)
            log_func(f"✅ Event {event_number} ({p_name}): Daten gespeichert.")
        else:
            logger.debug(f"Event {event_number}: No times found for participant {current_id}")

    except Exception as e:
        logger.error(f"Critical error in event {event_number}: {e}", exc_info=True)
        log_func(f"❌ Fehler bei Event {event_number}: {e}")


# ==============================
# 🎨 GUI APPLICATION
# ==============================

class ScraperApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Schwimm-Zeit Scraper (Turbo)")
        # ⑥ Taller default window; resizable vertically
        self.geometry("600x740")
        self.minsize(520, 620)
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        # ⑥ Let the log row (row 10) expand when the window is resized
        self.grid_rowconfigure(10, weight=1)

        # ─── Title ────────────────────────────────────────────────────
        self.label_title = ctk.CTkLabel(
            self, text="Schwimm-Zeit Scraper 🚀", font=("Roboto", 24, "bold")
        )
        self.label_title.grid(row=0, column=0, columnspan=2, pady=(18, 6))

        # ─── ① Multi-ID input ─────────────────────────────────────────
        self.lbl_ids = ctk.CTkLabel(
            self, text="TEILNEHMER-IDs  (eine pro Zeile oder kommagetrennt)",
            font=("Roboto", 11), text_color="#8a9ab0", anchor="w"
        )
        self.lbl_ids.grid(row=1, column=0, columnspan=2, padx=22, pady=(6, 0), sticky="w")

        self.text_ids = ctk.CTkTextbox(self, height=80, font=("Courier New", 13))
        self.text_ids.grid(row=2, column=0, columnspan=2, padx=20, pady=(2, 0), sticky="ew")
        self.text_ids.bind("<KeyRelease>", self._on_ids_change)

        self.lbl_ids_hint = ctk.CTkLabel(
            self, text="0 IDs erkannt", font=("Roboto", 10), text_color="#556677", anchor="w"
        )
        self.lbl_ids_hint.grid(row=3, column=0, columnspan=2, padx=22, pady=(1, 4), sticky="w")

        # ─── Event range ──────────────────────────────────────────────
        self.entry_start = ctk.CTkEntry(self, placeholder_text="Start Event Nr.")
        self.entry_start.grid(row=4, column=0, padx=20, pady=6, sticky="ew")
        self.entry_start.bind("<FocusOut>", lambda e: self._validate_range_ui())

        self.entry_end = ctk.CTkEntry(self, placeholder_text="End Event Nr.")
        self.entry_end.grid(row=4, column=1, padx=20, pady=6, sticky="ew")
        self.entry_end.bind("<FocusOut>", lambda e: self._validate_range_ui())

        # ─── Output file ──────────────────────────────────────────────
        self.entry_file = ctk.CTkEntry(self, placeholder_text="Bitte Speicherort wählen...")
        self.entry_file.grid(row=5, column=0, padx=(20, 5), pady=6, sticky="ew")

        self.btn_save_as = ctk.CTkButton(
            self, text="💾 Wählen…", width=110, command=self.choose_file
        )
        self.btn_save_as.grid(row=5, column=1, padx=(5, 20), pady=6, sticky="ew")

        # ─── Start / Stop ─────────────────────────────────────────────
        self.btn_start = ctk.CTkButton(
            self, text="🚀 START", fg_color="green",
            height=40, command=self.start_thread
        )
        self.btn_start.grid(row=6, column=0, padx=20, pady=(14, 6), sticky="ew")

        self.btn_stop = ctk.CTkButton(
            self, text="🛑 STOP", fg_color="red",
            height=40, command=self.stop_process, state="disabled"
        )
        self.btn_stop.grid(row=6, column=1, padx=20, pady=(14, 6), sticky="ew")

        # ─── Progress bar ─────────────────────────────────────────────
        self.progress_bar = ctk.CTkProgressBar(self)
        self.progress_bar.grid(row=7, column=0, columnspan=2, padx=20, pady=(6, 2), sticky="ew")
        self.progress_bar.set(0)

        # ② Progress label with elapsed + ETA
        self.progress_label = ctk.CTkLabel(self, text="0 / 0 (0%)", font=("Roboto", 10))
        self.progress_label.grid(row=8, column=0, columnspan=2, pady=(0, 4))

        # ─── ③ Live result counters ───────────────────────────────────
        self.frm_counters = ctk.CTkFrame(self, fg_color="transparent")
        self.frm_counters.grid(row=9, column=0, columnspan=2, padx=20, pady=(0, 4), sticky="ew")
        self.frm_counters.grid_columnconfigure((0, 1, 2), weight=1)

        def _make_counter(parent, col, label, color):
            frm = ctk.CTkFrame(parent, corner_radius=6)
            frm.grid(row=0, column=col, padx=3, sticky="ew")
            num = ctk.CTkLabel(frm, text="0", font=("Roboto", 20, "bold"), text_color=color)
            num.pack(pady=(4, 0))
            lbl = ctk.CTkLabel(frm, text=label, font=("Roboto", 9), text_color="#556677")
            lbl.pack(pady=(0, 4))
            return num

        self.lbl_saved   = _make_counter(self.frm_counters, 0, "GESPEICHERT", "#50c050")
        self.lbl_skipped = _make_counter(self.frm_counters, 1, "ÜBERSPRUNGEN", "#8888cc")
        self.lbl_errors  = _make_counter(self.frm_counters, 2, "FEHLER",       "#cc5050")

        # Counters need their own atomic integers
        self._cnt_saved   = 0
        self._cnt_skipped = 0
        self._cnt_errors  = 0
        self._cnt_lock    = threading.Lock()

        # ─── Log textbox ──────────────────────────────────────────────
        self.textbox = ctk.CTkTextbox(self, font=("Courier New", 11))
        self.textbox.grid(row=10, column=0, columnspan=2, padx=20, pady=(6, 4), sticky="nsew")
        self.textbox.configure(state="disabled")

        # ─── ⑤ Settings strip (debug checkbox, version) ───────────────
        self.frm_settings = ctk.CTkFrame(self, fg_color="transparent")
        self.frm_settings.grid(row=11, column=0, columnspan=2, padx=20, pady=(2, 10), sticky="ew")

        self.verbose_mode = ctk.CTkCheckBox(
            self.frm_settings, text="Debug-Modus (verbose log)", command=self.toggle_verbose
        )
        self.verbose_mode.pack(side="left")

        ctk.CTkLabel(
            self.frm_settings, text="v2.2.0", font=("Roboto", 10), text_color="#445566"
        ).pack(side="right")

        self.print_log("Bereit.  Bitte IDs und Event-Bereich eingeben, dann START drücken.")

        # ② Timing state
        self._start_time: Optional[float] = None

        # Progress tracking
        self.total_tasks = 0
        self.completed_tasks = 0

    # ─── ① ID parsing helpers ─────────────────────────────────────────

    def _parse_ids(self) -> list[str]:
        """Return the list of non-empty, whitespace-stripped IDs from the text box."""
        raw = self.text_ids.get("1.0", "end")
        # Support both newline and comma as separators
        tokens = re.split(r"[\n,]+", raw)
        return [t.strip() for t in tokens if t.strip()]

    def _on_ids_change(self, _event=None):
        ids = self._parse_ids()
        count = len(ids)
        if count == 0:
            self.lbl_ids_hint.configure(text="0 IDs erkannt", text_color="#556677")
        elif count == 1:
            self.lbl_ids_hint.configure(text="1 ID erkannt", text_color="#8a9ab0")
        else:
            self.lbl_ids_hint.configure(text=f"{count} IDs erkannt", text_color="#8a9ab0")
        # Auto-suggest filename from first ID if file field is empty
        if ids and not self.entry_file.get().strip():
            self.entry_file.configure(placeholder_text=f"{ids[0]}_swimming_results.csv")

    # ─── ④ Inline validation helpers ─────────────────────────────────

    _ENTRY_DEFAULT_BORDER = "#565B5E"   # CTk default dark border
    _ENTRY_OK_BORDER      = "#3a8a5a"
    _ENTRY_ERR_BORDER     = "#e05555"

    def _mark_entry(self, widget: ctk.CTkEntry, ok: bool):
        color = self._ENTRY_OK_BORDER if ok else self._ENTRY_ERR_BORDER
        widget.configure(border_color=color)

    def _reset_entry(self, widget: ctk.CTkEntry):
        widget.configure(border_color=self._ENTRY_DEFAULT_BORDER)

    def _validate_range_ui(self):
        """Colour Start/End event entries live on focus-out."""
        start = self.entry_start.get().strip()
        end   = self.entry_end.get().strip()
        if start or end:
            ok, _ = validate_event_range(start, end)
            self._mark_entry(self.entry_start, ok)
            self._mark_entry(self.entry_end, ok)

    # ─── Misc helpers ─────────────────────────────────────────────────

    def toggle_verbose(self):
        if self.verbose_mode.get():
            logger.setLevel(logging.DEBUG)
            self.print_log("🔍 Debug-Modus aktiviert")
        else:
            logger.setLevel(logging.INFO)
            self.print_log("ℹ️ Normaler Modus")

    def choose_file(self):
        ids = self._parse_ids()
        suggestion = ids[0] if ids else "zeiten"
        filename = filedialog.asksaveasfilename(
            initialfile=f"{suggestion}.csv",
            defaultextension=".csv",
            filetypes=[("CSV Dateien", "*.csv"), ("Alle Dateien", "*.*")]
        )
        if filename:
            self.entry_file.delete(0, "end")
            self.entry_file.insert(0, filename)
            self._reset_entry(self.entry_file)

    def print_log(self, text: str):
        """Thread-safe logging to GUI textbox."""
        try:
            self.textbox.configure(state="normal")
            self.textbox.insert("end", text + "\n")
            self.textbox.see("end")
            self.textbox.configure(state="disabled")
        except Exception as e:
            logger.debug(f"GUI logging failed: {e}")

    # ─── ② Progress with ETA ─────────────────────────────────────────

    def update_progress(self, completed: int, total: int):
        try:
            if total > 0:
                progress = completed / total
                self.progress_bar.set(progress)
                percentage = int(progress * 100)

                # ② Build elapsed + ETA string
                elapsed_str = ""
                if self._start_time is not None:
                    elapsed = time.monotonic() - self._start_time
                    elapsed_str = f"  ⏱ {elapsed:.1f} s"
                    if completed > 0 and completed < total:
                        rate = completed / elapsed if elapsed > 0 else 0
                        if rate > 0:
                            eta = (total - completed) / rate
                            elapsed_str += f"  ·  ~{eta:.1f} s verbleibend"

                self.progress_label.configure(
                    text=f"{completed} / {total} ({percentage}%){elapsed_str}"
                )
            else:
                self.progress_bar.set(0)
                self.progress_label.configure(text="0 / 0 (0%)")
        except Exception as e:
            logger.debug(f"Progress update failed: {e}")

    def reset_progress(self):
        try:
            self.progress_bar.set(0)
            self.progress_label.configure(text="0 / 0 (0%)")
            self.completed_tasks = 0
            self.total_tasks = 0
            self._start_time = None
        except Exception as e:
            logger.debug(f"Progress reset failed: {e}")

    # ─── ③ Counter helpers ────────────────────────────────────────────

    def _reset_counters(self):
        with self._cnt_lock:
            self._cnt_saved = self._cnt_skipped = self._cnt_errors = 0
        self.lbl_saved.configure(text="0")
        self.lbl_skipped.configure(text="0")
        self.lbl_errors.configure(text="0")

    def _inc_saved(self):
        with self._cnt_lock:
            self._cnt_saved += 1
            val = self._cnt_saved
        self.lbl_saved.configure(text=str(val))

    def _inc_skipped(self):
        with self._cnt_lock:
            self._cnt_skipped += 1
            val = self._cnt_skipped
        self.lbl_skipped.configure(text=str(val))

    def _inc_errors(self):
        with self._cnt_lock:
            self._cnt_errors += 1
            val = self._cnt_errors
        self.lbl_errors.configure(text=str(val))

    # ─── Start / Stop ─────────────────────────────────────────────────

    def start_thread(self):
        # ① Validate IDs from multi-ID box
        ids = self._parse_ids()
        if not ids:
            self.print_log("❌ Bitte mindestens eine Teilnehmer-ID eingeben.")
            return
        invalid = []
        for pid in ids:
            ok, msg = validate_participant_id(pid)
            if not ok:
                invalid.append(f"{pid}: {msg}")
        if invalid:
            for err in invalid:
                self.print_log(f"❌ ID-Fehler: {err}")
            return

        # ④ Validate event range with border highlighting
        start = self.entry_start.get().strip()
        end   = self.entry_end.get().strip()
        valid, msg = validate_event_range(start, end)
        self._mark_entry(self.entry_start, valid)
        self._mark_entry(self.entry_end, valid)
        if not valid:
            self.print_log(f"❌ Event-Bereich: {msg}")
            return

        # ④ Validate file path with border highlighting
        full_path = self.entry_file.get().strip()
        fvalid, fmsg = validate_file_path(full_path)
        self._mark_entry(self.entry_file, fvalid)
        if not fvalid:
            self.print_log(f"❌ Datei: {fmsg}")
            if not full_path:
                self.choose_file()
            return

        # Warn for large ranges
        event_count = int(end) - int(start) + 1
        total_requests = event_count * len(ids)
        if total_requests > 500:
            self.print_log(
                f"⚠️ {total_requests} Requests · {len(ids)} IDs · "
                f"ca. {total_requests * 0.2 / MAX_WORKERS:.0f} s geschätzt"
            )

        global stop_scraping
        stop_scraping = False

        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.textbox.delete("0.0", "end")
        self.reset_progress()
        self._reset_counters()

        threading.Thread(target=self.run_scraper, args=(full_path,), daemon=True).start()

    def stop_process(self):
        global stop_scraping
        stop_scraping = True
        self.print_log("\n🛑 Stoppe laufende Threads…")
        self.btn_stop.configure(state="disabled")
        threading.Thread(target=reset_http_session, daemon=True).start()

    def run_scraper(self, full_path: str):
        try:
            ids   = self._parse_ids()
            start = int(self.entry_start.get())
            end   = int(self.entry_end.get())

            self.print_log(
                f"Starte {MAX_WORKERS}-fach Turbo · {len(ids)} ID(s) · "
                f"Events {start}–{end}"
            )
            self.print_log(f"Datei: {full_path}")
            self.print_log("-" * 40)

            # Build task list: (event_number, participant_id)
            tasks = [(ev, pid) for ev in range(start, end + 1) for pid in ids]

            self.total_tasks = len(tasks)
            self.completed_tasks = 0
            self._start_time = time.monotonic()
            self.update_progress(0, self.total_tasks)

            def _task_wrapper(event_number: int, current_id: str):
                """Wraps process_single_event, routes result into the right counter."""
                global stop_scraping
                if stop_scraping:
                    return

                # Intercept the log_func calls to detect saved vs skipped vs error
                result_bucket: list[str] = []

                def _counting_log(text: str):
                    result_bucket.append(text)
                    self.print_log(text)

                # Count errors: process_single_event logs "❌" on hard failure
                try:
                    process_single_event(event_number, current_id, _counting_log, full_path)
                except Exception as e:
                    self._inc_errors()
                    self.print_log(f"❌ Thread-Fehler Event {event_number}: {e}")
                    return

                # Classify outcome from accumulated log lines
                if any("❌" in line for line in result_bucket):
                    self._inc_errors()
                elif any("💾" in line or "✅" in line for line in result_bucket):
                    self._inc_saved()
                else:
                    self._inc_skipped()

            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = []
                for ev, pid in tasks:
                    if stop_scraping:
                        break
                    futures.append(executor.submit(_task_wrapper, ev, pid))

                for future in futures:
                    if stop_scraping:
                        executor.shutdown(wait=False, cancel_futures=True)
                        break
                    try:
                        future.result()
                    except Exception as e:
                        self.print_log(f"Fehler im Thread: {e}")
                    finally:
                        self.completed_tasks += 1
                        self.update_progress(self.completed_tasks, self.total_tasks)

            elapsed = time.monotonic() - self._start_time if self._start_time else 0
            with self._cnt_lock:
                saved   = self._cnt_saved
                skipped = self._cnt_skipped
                errors  = self._cnt_errors
            self.print_log(
                f"\n✅ Fertig!  {saved} gespeichert · {skipped} übersprungen · "
                f"{errors} Fehler  ({elapsed:.1f} s)"
            )
            self.update_progress(self.total_tasks, self.total_tasks)

        except ValueError:
            self.print_log("❌ Fehler: Events müssen Zahlen sein.")
        except Exception as e:
            self.print_log(f"❌ Kritischer Fehler: {e}")
        finally:
            self.btn_start.configure(state="normal")
            self.btn_stop.configure(state="disabled")


if __name__ == "__main__":
    app = ScraperApp()
    app.mainloop()
