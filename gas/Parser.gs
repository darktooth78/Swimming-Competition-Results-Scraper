/**
 * Parser.gs
 * =========
 * All HTML parsing for:
 *   • Recent page     (parseRecentPage)
 *   • Club page       (parseClubPage)
 *   • Participant page (parseMetadata, parseParticipant, parseResults)
 *   • Discipline normalisation (normalizeDiscipline)
 *   • Time utilities  (timeToSeconds, validateTimeFormat, parseLastDate)
 *
 * Regex patterns are direct ports from timescraper_010.py lines 162–210.
 * Python re.DOTALL → JS /s flag (V8/GAS supports it).
 * Python re.IGNORECASE → JS /i flag.
 */

// ---------------------------------------------------------------------------
// Regex constants — ported from Python source
// ---------------------------------------------------------------------------

// Relay detection
const RELAY_PATTERN            = /4x/i;

// Discipline normalisation strip patterns
const PREFIX_PATTERN           = /^\d+\s*-\s*/;
const GENDER_PATTERN           = /\b(Men|Women|Mixed|Herren|Damen)\b/gi;
const HEAT_PATTERN             = /\b(Preliminary|Vorlauf|Heats|Entscheidung)\b/gi;
const FINAL_PATTERN            = /\b([AB]-)?(Final|Finale)\b/gi;
const AGE_PATTERN              = /\bAK\s*\d+.*/i;
const YOUNGER_PATTERN          = /\bund\s+jünger\b/gi;
const WHITESPACE_PATTERN       = /\s+/g;

// Keep only "NNm Stroke" — first two tokens
const DISCIPLINE_CORE_PATTERN  = /^(\d+\s*[mM]?\s+\S+)/i;

// Time validation: SS.ss or M:SS.ss
const TIME_FORMAT_PATTERN      = /^(\d{1,2}:)?\d{1,2}\.\d{2}$/;

// Date parsing: DD.MM.YYYY
const DATE_EXTRACT_PATTERN     = /(\d{2})\.(\d{2})\.(\d{4})/g;

// Club cleanup: strips " AUT (Austria)..." suffix
const AUSTRIA_PATTERN          = /\bAUT\s*\(Austria\).*/i;

// HTML tag stripping
const TAG_STRIP_PATTERN        = /<[^>]+>/g;

// Primary time column: hidden-xs, right-aligned, no "points" in class name
const TIME_COL_PATTERN         = /<div[^>]*class="hidden-xs[^"]*myresults_content_divtable_right"[^>]*>\s*([^<\s][^<]*?)\s*<\/div>/g;

// Discipline link anchor (may contain inner tags like <i>)
const DISC_ANCHOR_PATTERN      = /<a[^>]*href="[^"]*"[^>]*>(.*?)<\/a>/s;

// "Ergebnisse" section header
const ERGEBNISSE_HEADER_PATTERN = /<div[^>]*class="row myresults_content_divtablerow\s+myresults_content_divtablerow_header[^"]*"[^>]*>[^<]*<div[^>]*>[^<]*[Ee]rgebnisse[^<]*<\/div>/s;

// Participant details table
const PERSON_PATTERN           = /myresults_personendetails_header[^>]*>\s*([^<]+?)\s*<\/td>.*?Jahrg\.[^<]*<\/td>\s*<td[^>]*>\s*(\d{4})\s*<\/td>.*?Verein[^<]*<\/td>\s*<td[^>]*>(.*?)<\/td>/s;

// Event name / date / location from header paragraph
const MEETNAME2_PATTERN        = /class="[^"]*myresults_meetname2[^"]*"[^>]*>\s*([^<]+)/;

// Fallback: nav3a paragraph
const NAV3A_PATTERN            = /class="[^"]*myresults_nav3a[^"]*"[^>]*>.*?<p[^>]*>([^<]+)<\/p>/s;

// Pool size: "25m (SCM) ..." or "50m (LCM) ..." before the "Bad" span on the Overview page
const POOL_SIZE_PATTERN        = /(\d+m)\s*\([^)]+\)[^<]*<span[^>]*myresults_content_divtable_details[^>]*>Bad</i;

// Overview URL template
const OVERVIEW_URL_TEMPLATE    = 'https://myresults.eu/de-AT/Meets/Recent/{event}/Overview';

// Recent page: event link + date
// Matches: /Recent/{id}/Overview + event name + date cell
const RECENT_EVENT_PATTERN     = /\/Recent\/(\d+)\/Overview"[^>]*>([^<]+)<[^]*?hidden-xs col-sm-2">([^<]+)</g;

// Club page: participant links
const CLUB_PARTICIPANT_PATTERN = /\/Recent\/(\d+)\/Participant\/(\d+)"[^>]*>([^<]+)</g;


// ---------------------------------------------------------------------------
// Time utilities
// ---------------------------------------------------------------------------

/**
 * Returns true if the string matches SS.ss or M:SS.ss format.
 * @param {string} s
 * @returns {boolean}
 */
function validateTimeFormat(s) {
  return TIME_FORMAT_PATTERN.test(s);
}


/**
 * Convert a time string ("SS.ss" or "M:SS.ss") to floating-point seconds.
 * Returns 999999.0 on parse failure.
 * Ported from Python lines 301–310.
 *
 * @param {string} timeStr
 * @returns {number}
 */
function timeToSeconds(timeStr) {
  try {
    const s = timeStr.replace(',', '.');
    if (s.includes(':')) {
      const parts = s.split(':');
      return parseFloat(parts[0]) * 60 + parseFloat(parts[1]);
    }
    return parseFloat(s);
  } catch (_) {
    return 999999.0;
  }
}


/**
 * Parse a raw date string (single "DD.MM.YYYY" or range "DD.-DD.MM.YYYY")
 * and return the LAST date formatted as "DD/MM/YYYY".
 * Ported from Python parse_last_date().
 *
 * @param {string} rawDateStr
 * @returns {string}
 */
function parseLastDate(rawDateStr) {
  const matches = [...rawDateStr.matchAll(/(\d{2})\.(\d{2})\.(\d{4})/g)];
  if (matches.length === 0) return rawDateStr;
  const last = matches[matches.length - 1];
  return `${last[1]}/${last[2]}/${last[3]}`;
}


// ---------------------------------------------------------------------------
// Discipline normalisation
// ---------------------------------------------------------------------------

/**
 * Normalise a raw swimming discipline name to "NNm Stroke" form.
 * Returns null for relay events ("4x…").
 * Ported from Python normalize_discipline() lines 313–341.
 *
 * @param {string} rawName
 * @param {{translations: {[eng: string]: string}}} cfg
 * @returns {string|null}
 */
function normalizeDiscipline(rawName, cfg) {
  if (RELAY_PATTERN.test(rawName)) return null;

  let name = rawName.replace(PREFIX_PATTERN, '').trim();
  name = name.replace(GENDER_PATTERN,   '');
  name = name.replace(HEAT_PATTERN,     '');
  name = name.replace(FINAL_PATTERN,    '');
  name = name.replace(AGE_PATTERN,      '');
  name = name.replace(YOUNGER_PATTERN,  '');

  // Apply EN→DE translations
  for (const [eng, ger] of Object.entries(cfg.translations)) {
    if (name.includes(eng)) {
      name = name.replace(new RegExp(eng, 'g'), ger);
    }
  }

  name = name.replace(WHITESPACE_PATTERN, ' ').trim().replace(/^[-\s]+|[-\s]+$/g, '');

  // Keep only "NNm Stroke"
  const coreMatch = DISCIPLINE_CORE_PATTERN.exec(name);
  if (coreMatch) name = coreMatch[1].trim();

  return name || null;
}


// ---------------------------------------------------------------------------
// Recent page parsing
// ---------------------------------------------------------------------------

/**
 * Parse the myresults.eu /de-AT/Meets/Recent HTML and return all listed events.
 *
 * @param {string} html
 * @returns {{event_id: number, event_name: string, date: string}[]}
 */
function parseRecentPage(html) {
  const events = [];
  // Reset lastIndex (global regex)
  RECENT_EVENT_PATTERN.lastIndex = 0;
  let m;
  while ((m = RECENT_EVENT_PATTERN.exec(html)) !== null) {
    events.push({
      event_id:   parseInt(m[1], 10),
      event_name: m[2].trim(),
      date:       parseLastDate(m[3].trim())
    });
  }
  return events;
}


// ---------------------------------------------------------------------------
// Club page parsing
// ---------------------------------------------------------------------------

/**
 * Parse a /Club/6614 page and return all SU MöDLING participant links.
 * Returns an empty array if the club has no participants in this event.
 *
 * @param {string} html
 * @returns {{event_id: number, participant_id: number, name: string}[]}
 */
function parseClubPage(html) {
  const participants = [];
  CLUB_PARTICIPANT_PATTERN.lastIndex = 0;
  let m;
  while ((m = CLUB_PARTICIPANT_PATTERN.exec(html)) !== null) {
    participants.push({
      event_id:       parseInt(m[1], 10),
      participant_id: parseInt(m[2], 10),
      name:           m[3].trim()
    });
  }
  return participants;
}


// ---------------------------------------------------------------------------
// Participant page — metadata
// ---------------------------------------------------------------------------

/**
 * Extract event name, date, and location from a participant page HTML.
 * Returns {event: string, date: string, location: string}.
 * Ported from Python parse_metadata_from_html() lines 404–441.
 *
 * @param {string} html
 * @param {number} eventId   (used only for logging)
 * @returns {{event: string, date: string, location: string}}
 */
function parseMetadata(html, eventId) {
  const meta = { event: 'Unknown', date: 'Unknown', location: 'Unknown' };
  let raw = '';

  const m2 = MEETNAME2_PATTERN.exec(html);
  if (m2) {
    raw = m2[1].trim();
  } else {
    const mn = NAV3A_PATTERN.exec(html);
    if (mn) raw = mn[1].trim();
  }

  if (raw) {
    // Pattern: "Event Name (Date) - Location"
    const parts = raw.match(/^(.+?)\s*\((.+?)\)\s*-\s*(.+)$/);
    if (parts) {
      meta.event    = parts[1].trim();
      meta.date     = parseLastDate(parts[2].trim());
      meta.location = parts[3].trim();
    }
  }

  return meta;
}


// ---------------------------------------------------------------------------
// Participant page — swimmer details
// ---------------------------------------------------------------------------

/**
 * Extract swimmer name, birth year, and club from HTML.
 * Returns {name, birth_year, club} with "Unknown" fallbacks.
 * Ported from Python parse_participant_from_html() lines 444–457.
 *
 * @param {string} html
 * @returns {{name: string, birth_year: string, club: string}}
 */
function parseParticipant(html) {
  const result = { name: 'Unknown', birth_year: 'Unknown', club: 'Unknown' };
  const m = PERSON_PATTERN.exec(html);
  if (m) {
    result.name       = cleanText(m[1]);
    result.birth_year = m[2];
    const rawClub     = cleanText(m[3]).split('>>')[0].trim();
    result.club       = rawClub.replace(AUSTRIA_PATTERN, '').trim();
  }
  return result;
}


// ---------------------------------------------------------------------------
// Participant page — results
// ---------------------------------------------------------------------------

/**
 * Extract all swimming results from a participant page HTML.
 * Returns {disciplineName: {str: string, sec: number}} — fastest per discipline.
 * Relays (4x…) are excluded.
 * Ported from Python parse_results_from_html() lines 460–513.
 *
 * @param {string} html
 * @param {{translations: {[eng: string]: string}}} cfg
 * @returns {{[discipline: string]: {str: string, sec: number}}}
 */
function parseResults(html, cfg) {
  const results = {};

  // Find Ergebnisse section
  const headerMatch = ERGEBNISSE_HEADER_PATTERN.exec(html);
  if (!headerMatch) return results;

  const resultsHtml = html.slice(headerMatch.index + headerMatch[0].length);

  // Split into row chunks
  const rowSplits = resultsHtml.split(
    /(?=<div[^>]*class="row myresults_content_divtablerow\s+myresults_content_divtablerow_(?:odd|even))/
  );

  for (const chunk of rowSplits) {
    if (!chunk.trim()) continue;

    // Extract discipline name from the first anchor
    const anchorM = DISC_ANCHOR_PATTERN.exec(chunk);
    if (!anchorM) continue;
    const discRaw   = cleanText(anchorM[1]);
    const discClean = normalizeDiscipline(discRaw, cfg);
    if (!discClean) continue;

    // Extract time from first right-aligned column (reset global regex)
    TIME_COL_PATTERN.lastIndex = 0;
    const timeM = TIME_COL_PATTERN.exec(chunk);
    if (!timeM) continue;
    const timeStr = timeM[1].trim().replace(',', '.');

    if (!validateTimeFormat(timeStr)) continue;

    const sec = timeToSeconds(timeStr);
    if (!(discClean in results) || sec < results[discClean].sec) {
      results[discClean] = { str: timeStr, sec };
    }
  }

  return results;
}


// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------

/**
 * Strip HTML tags and collapse whitespace — equivalent to Python clean_text().
 * @param {string} text
 * @returns {string}
 */
function cleanText(text) {
  return (text || '')
    .replace(TAG_STRIP_PATTERN, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}


// ---------------------------------------------------------------------------
// Pool size
// ---------------------------------------------------------------------------

/**
 * Fetch the event Overview page and return "25m" or "50m".
 * The "Bad" field contains text like "25m (SCM) Hallenbad" or "50m (LCM) Freibad".
 * Defaults to "50m" when the page cannot be fetched or the field is absent.
 * Ported from Python parse_pool_size_from_overview().
 *
 * @param {number|string} eventId
 * @param {{max_retries: number, retry_delays: number[]}} cfg
 * @returns {string}  "25m" or "50m"
 */
function parsePoolSize(eventId, cfg) {
  const url  = OVERVIEW_URL_TEMPLATE.replace('{event}', eventId);
  const html = fetchHtml(url, cfg);
  if (!html) return '50m';
  const m = POOL_SIZE_PATTERN.exec(html);
  return m ? m[1].toLowerCase() : '50m';
}


// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

function testParseRecentPage() {
  const cfg  = readConfig();
  const html = fetchHtml('https://myresults.eu/de-AT/Meets/Recent', cfg);
  if (!html) { Logger.log('testParseRecentPage: FAIL — no HTML'); return; }
  const events = parseRecentPage(html);
  Logger.log('testParseRecentPage: found ' + events.length + ' events');
  if (events.length < 90) {
    Logger.log('testParseRecentPage: FAIL — expected ≥ 90, got ' + events.length);
    return;
  }
  Logger.log('testParseRecentPage: sample: ' + JSON.stringify(events.slice(0, 3)));
  Logger.log('testParseRecentPage: PASS');
}

function testParseClubPage() {
  const cfg  = readConfig();
  const html = fetchHtml('https://myresults.eu/de-AT/Meets/Recent/2341/Club/6614', cfg);
  if (!html) { Logger.log('testParseClubPage: FAIL — no HTML'); return; }
  const participants = parseClubPage(html);
  Logger.log('testParseClubPage: found ' + participants.length + ' participants');
  Logger.log('testParseClubPage: ' + JSON.stringify(participants));
  const ids = participants.map(p => p.participant_id);
  const expected = [306991, 275975, 302966, 329116];
  const allFound = expected.every(id => ids.includes(id));
  if (!allFound) {
    Logger.log('testParseClubPage: FAIL — missing expected participants');
    return;
  }
  Logger.log('testParseClubPage: PASS');
}

function testParser() {
  const cfg  = readConfig();
  const url  = 'https://myresults.eu/de-AT/Meets/Recent/2341/Participant/306991';
  const html = fetchHtml(url, cfg);
  if (!html) { Logger.log('testParser: FAIL — no HTML'); return; }

  const meta    = parseMetadata(html, 2341);
  const swimmer = parseParticipant(html);
  const results = parseResults(html, cfg);

  Logger.log('meta    : ' + JSON.stringify(meta));
  Logger.log('swimmer : ' + JSON.stringify(swimmer));
  Logger.log('results : ' + JSON.stringify(results));

  const discKeys = Object.keys(results);

  if (meta.event !== '53. Internationales Swimcity Wels Meeting') {
    Logger.log('testParser: FAIL — wrong event: ' + meta.event); return;
  }
  if (swimmer.name !== 'BLOBNER Vincent') {
    Logger.log('testParser: FAIL — wrong name: ' + swimmer.name); return;
  }
  if (discKeys.length !== 6) {
    Logger.log('testParser: FAIL — expected 6 disciplines, got ' + discKeys.length); return;
  }
  // All keys must be "NNm Stroke" (≤ 2 tokens)
  for (const k of discKeys) {
    if (k.trim().split(/\s+/).length > 2) {
      Logger.log('testParser: FAIL — unexpected suffix in key: ' + k); return;
    }
  }
  Logger.log('testParser: PASS');
}


function testParsePoolSize() {
  const cfg   = readConfig();
  const pool25 = parsePoolSize(2248, cfg);
  const pool50 = parsePoolSize(2341, cfg);
  Logger.log('testParsePoolSize: event 2248 → ' + pool25 + ' (expected 25m)');
  Logger.log('testParsePoolSize: event 2341 → ' + pool50 + ' (expected 50m)');
  if (pool25 !== '25m') { Logger.log('testParsePoolSize: FAIL — expected 25m'); return; }
  if (pool50 !== '50m') { Logger.log('testParsePoolSize: FAIL — expected 50m'); return; }
  Logger.log('testParsePoolSize: PASS');
}
