/**
 * Sheets.gs
 * =========
 * All read/write operations against the SwimmingResults_DB workbook.
 * No other GAS file calls SpreadsheetApp directly — only this module does.
 *
 * Replaces save_to_csv() and event_metadata_cache from the Python desktop tool.
 *
 * Tab column layout (1-based):
 *   Swimmers:     A=swimmer_id, B=name, C=birth_year, D=club,
 *                 E=first_seen_event_id, F=last_updated
 *   Events:       A=event_id, B=event_name, C=date, D=location,
 *                 E=last_updated, F=modling_participant_count, G=pool
 *   Results:      A=event_id, B=swimmer_id, C=discipline, D=time_str,
 *                 E=time_sec, F=fetched_at, G=source
 *   Rescan_Queue: A=swimmer_id, B=rescan_start, C=rescan_end,
 *                 D=status, E=submitted_at
 *   Config:       A=key, B=value
 *   Log:          A=run_at, B=events_checked, C=events_new, D=swimmers_discovered,
 *                 E=results_added, F=results_skipped, G=errors, H=rescans,
 *                 I=duration_sec, J=notes
 */

// Execution-scoped sheet cache — avoids repeated getSheetByName() calls
const _sheetCache = {};


/**
 * Return a Sheet object by name, using an execution-scoped cache.
 * @param {string} name
 * @returns {GoogleAppsScript.Spreadsheet.Sheet}
 */
function getSheet(name) {
  if (!_sheetCache[name]) {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    _sheetCache[name] = ss.getSheetByName(name);
    if (!_sheetCache[name]) {
      throw new Error(`Sheet "${name}" not found in the workbook.`);
    }
  }
  return _sheetCache[name];
}


// ---------------------------------------------------------------------------
// Skip set — avoid re-fetching already stored results
// ---------------------------------------------------------------------------

/**
 * Return a Set of "eventId|swimmerId" strings already present in the Results tab.
 * Used by main() to skip tasks that have been processed.
 *
 * @returns {Set<string>}
 */
function loadSkipSet() {
  const sheet = getSheet('Results');
  const lastRow = sheet.getLastRow();
  const skipSet = new Set();
  if (lastRow < 2) return skipSet;   // header only

  // Only need columns A (event_id) and B (swimmer_id)
  const values = sheet.getRange(2, 1, lastRow - 1, 2).getValues();
  for (const [eventId, swimmerId] of values) {
    if (eventId && swimmerId) {
      skipSet.add(`${eventId}|${swimmerId}`);
    }
  }
  return skipSet;
}


// ---------------------------------------------------------------------------
// Events cache — metadata keyed by event_id
// ---------------------------------------------------------------------------

/**
 * Load all events from the Events tab into a lookup object.
 * @returns {{[eventId: string]: {event_name: string, date: string, location: string}}}
 */
function loadEventsCache() {
  const sheet   = getSheet('Events');
  const lastRow = sheet.getLastRow();
  const cache   = {};
  if (lastRow < 2) return cache;

  const values = sheet.getRange(2, 1, lastRow - 1, 7).getValues();
  for (const [eventId, eventName, date, location, , , pool] of values) {
    if (eventId) {
      cache[String(eventId)] = {
        event_name: String(eventName),
        date:       String(date),
        location:   String(location),
        pool:       String(pool || '50m') || '50m'
      };
    }
  }
  return cache;
}


// ---------------------------------------------------------------------------
// Swimmers list
// ---------------------------------------------------------------------------

/**
 * Load all swimmers from the Swimmers tab.
 * @returns {{swimmer_id: string, name: string, birth_year: string, club: string, first_seen_event_id: string}[]}
 */
function loadSwimmers() {
  const sheet   = getSheet('Swimmers');
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return [];

  const values = sheet.getRange(2, 1, lastRow - 1, 5).getValues();
  return values
    .filter(r => r[0])
    .map(([swimmer_id, name, birth_year, club, first_seen_event_id]) => ({
      swimmer_id:          String(swimmer_id),
      name:                String(name),
      birth_year:          String(birth_year),
      club:                String(club),
      first_seen_event_id: String(first_seen_event_id)
    }));
}


// ---------------------------------------------------------------------------
// Upsert helpers
// ---------------------------------------------------------------------------

/**
 * Insert or update a row in the Swimmers tab.
 * Matches on column A (swimmer_id).
 *
 * @param {number|string} id
 * @param {string} name
 * @param {string} birthYear
 * @param {string} club
 * @param {number} firstSeenEventId
 */
function upsertSwimmer(id, name, birthYear, club, firstSeenEventId) {
  const sheet   = getSheet('Swimmers');
  const now     = new Date().toISOString();
  const lastRow = sheet.getLastRow();
  const idStr   = String(id);

  if (lastRow >= 2) {
    const colA = sheet.getRange(2, 1, lastRow - 1, 1).getValues();
    for (let i = 0; i < colA.length; i++) {
      if (String(colA[i][0]) === idStr) {
        // Update existing row — only overwrite name/year/club if currently "Unknown" or blank
        const row       = sheet.getRange(i + 2, 1, 1, 6).getValues()[0];
        const newName   = (name      && name      !== 'Unknown') ? name      : (row[1] || name);
        const newYear   = (birthYear && birthYear !== 'Unknown') ? birthYear : (row[2] || birthYear);
        const newClub   = (club      && club      !== 'Unknown') ? club      : (row[3] || club);
        sheet.getRange(i + 2, 1, 1, 6).setValues([[idStr, newName, newYear, newClub, row[4] || firstSeenEventId, now]]);
        return;
      }
    }
  }

  // Not found — append new row
  sheet.appendRow([idStr, name, birthYear, club, firstSeenEventId, now]);
}


/**
 * Insert or update a row in the Events tab.
 * Matches on column A (event_id).
 *
 * @param {number|string} id
 * @param {string} name
 * @param {string} date
 * @param {string|null} location
 * @param {number} modlingCount
 * @param {string|null} [pool]  "25m" or "50m" (optional, not overwritten if already set)
 */
function upsertEvent(id, name, date, location, modlingCount, pool) {
  const sheet   = getSheet('Events');
  const now     = new Date().toISOString();
  const lastRow = sheet.getLastRow();
  const idStr   = String(id);

  if (lastRow >= 2) {
    const colA = sheet.getRange(2, 1, lastRow - 1, 1).getValues();
    for (let i = 0; i < colA.length; i++) {
      if (String(colA[i][0]) === idStr) {
        const row      = sheet.getRange(i + 2, 1, 1, 7).getValues()[0];
        const newName  = (name     && name     !== 'Unknown') ? name     : (row[1] || name);
        const newDate  = (date     && date     !== 'Unknown') ? date     : (row[2] || date);
        const newLoc   = (location && location !== 'Unknown') ? location : (row[3] || location || '');
        const newCount = modlingCount != null ? modlingCount : row[5];
        // Only write pool if provided; keep existing value otherwise
        const newPool  = pool || row[6] || '50m';
        sheet.getRange(i + 2, 1, 1, 7).setValues([[idStr, newName, newDate, newLoc, now, newCount, newPool]]);
        return;
      }
    }
  }

  sheet.appendRow([idStr, name, date, location || '', now, modlingCount != null ? modlingCount : 0, pool || '50m']);
}


// ---------------------------------------------------------------------------
// Results write
// ---------------------------------------------------------------------------

/**
 * Bulk-append result rows to the Results tab.
 * One row per discipline.
 *
 * @param {number|string} eventId
 * @param {number|string} swimmerId
 * @param {{[discipline: string]: {str: string, sec: number}}} resultsObj
 * @param {string} [source="scraper"]
 */
function appendResults(eventId, swimmerId, resultsObj, source) {
  const sheet = getSheet('Results');
  const now   = new Date().toISOString();
  const src   = source || 'scraper';
  const rows  = [];

  for (const [disc, {str, sec}] of Object.entries(resultsObj)) {
    rows.push([String(eventId), String(swimmerId), disc, str, sec, now, src]);
  }

  if (rows.length === 0) return;

  const lastRow = sheet.getLastRow();
  sheet.getRange(lastRow + 1, 1, rows.length, 7).setValues(rows);
}


// ---------------------------------------------------------------------------
// Rescan helpers
// ---------------------------------------------------------------------------

/**
 * Delete all Results rows matching swimmer_id and event_id within [startId, endId].
 * Used by the force-rescan flow.
 *
 * @param {string|number} swimmerId
 * @param {number} startEventId
 * @param {number} endEventId
 */
function deleteResults(swimmerId, startEventId, endEventId) {
  const sheet   = getSheet('Results');
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return;

  const values    = sheet.getRange(2, 1, lastRow - 1, 7).getValues();
  const sidStr    = String(swimmerId);
  const isNumericRange = !isNaN(Number(startEventId)) && !isNaN(Number(endEventId));

  const filtered  = values.filter(row => {
    const eidStr = String(row[0]);
    const sid    = String(row[1]);
    if (sid !== sidStr) return true;
    if (isNumericRange) {
      const eid = parseInt(eidStr, 10);
      return !(eid >= Number(startEventId) && eid <= Number(endEventId));
    }
    // String event ID (e.g. "csv_a3f1b2") — exact match only
    return eidStr !== String(startEventId);
  });

  // Clear and rewrite (header is row 1 — untouched)
  if (lastRow > 1) sheet.getRange(2, 1, lastRow - 1, 7).clearContent();
  if (filtered.length > 0) {
    sheet.getRange(2, 1, filtered.length, 7).setValues(filtered);
  }
}


/**
 * Mark a Rescan_Queue row as done.
 * @param {number} rowIndex  1-based row index in the sheet (including header)
 */
function markRescanDone(rowIndex) {
  getSheet('Rescan_Queue').getRange(rowIndex, 4).setValue('done');
}


// ---------------------------------------------------------------------------
// Log
// ---------------------------------------------------------------------------

/**
 * Append one run summary row to the Log tab.
 *
 * @param {Date}   runAt
 * @param {number} eventsChecked
 * @param {number} eventsNew
 * @param {number} swimmersDiscovered
 * @param {number} resultsAdded
 * @param {number} resultsSkipped
 * @param {number} errors
 * @param {number} rescans
 * @param {number} durationSec
 * @param {string} notes
 */
function appendLog(runAt, eventsChecked, eventsNew, swimmersDiscovered,
                   resultsAdded, resultsSkipped, errors, rescans,
                   durationSec, notes) {
  getSheet('Log').appendRow([
    runAt instanceof Date ? runAt.toISOString() : runAt,
    eventsChecked,
    eventsNew,
    swimmersDiscovered,
    resultsAdded,
    resultsSkipped,
    errors,
    rescans,
    durationSec,
    notes || ''
  ]);
}


// ---------------------------------------------------------------------------
// Backfill
// ---------------------------------------------------------------------------

/**
 * backfillPoolSize()
 * ==================
 * One-shot function: reads every row in the Events sheet, fetches the pool
 * size from the /Overview page for any row where column G (pool) is blank or
 * missing, and writes it back.
 *
 * Run ONCE manually from the Apps Script editor:
 *   Extensions → Apps Script → select backfillPoolSize → Run
 *
 * It respects the GAS 6-minute execution limit: it stops early if within
 * 5 minutes and logs how many rows remain so you can re-run.
 *
 * Safe to re-run: already-populated rows are skipped without a network call.
 */
function backfillPoolSize() {
  const MAX_MS   = 300000;   // 5-minute budget (same guard as main())
  const runStart = new Date();
  const cfg      = readConfig();
  const sheet    = getSheet('Events');
  const lastRow  = sheet.getLastRow();

  if (lastRow < 2) {
    Logger.log('backfillPoolSize: Events sheet is empty — nothing to do');
    return;
  }

  // Read all 7 columns (A–G) in one batch
  const values = sheet.getRange(2, 1, lastRow - 1, 7).getValues();

  let filled   = 0;
  let skipped  = 0;
  let errors   = 0;
  let deferred = 0;

  for (let i = 0; i < values.length; i++) {
    // Time-budget guard
    if ((new Date() - runStart) > MAX_MS) {
      deferred = values.length - i;
      Logger.log('backfillPoolSize: time budget reached — ' + deferred + ' rows deferred. Re-run to continue.');
      break;
    }

    const row     = values[i];
    const eventId = row[0];
    const pool    = String(row[6] || '').trim();

    // Already filled — skip without any network call
    if (pool === '25m' || pool === '50m') {
      skipped++;
      continue;
    }

    // No event ID — skip
    if (!eventId) {
      skipped++;
      continue;
    }

    // Synthetic CSV event IDs (csv_xxxxxx) have no Overview page — default to 50m
    if (String(eventId).startsWith('csv_')) {
      sheet.getRange(i + 2, 7).setValue('50m');
      filled++;
      continue;
    }

    try {
      const poolSize = parsePoolSize(eventId, cfg);
      sheet.getRange(i + 2, 7).setValue(poolSize);
      filled++;
      Logger.log('backfillPoolSize: event ' + eventId + ' → ' + poolSize);
    } catch (e) {
      errors++;
      Logger.log('backfillPoolSize: ERROR for event ' + eventId + ': ' + e);
    }
  }

  Logger.log(
    'backfillPoolSize: done — filled=' + filled +
    ', skipped=' + skipped +
    ', errors=' + errors +
    ', deferred=' + deferred
  );
}




// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

/**
 * Write a dummy Results row, read it back, then delete it.
 * Verifies the Sheets read/write layer end-to-end.
 */
function testSheets() {
  const sheet = getSheet('Results');
  const beforeLastRow = sheet.getLastRow();

  // Write one dummy row
  appendResults('9999', '99999', { '50m Freistil': { str: '27.92', sec: 27.92 } }, 'test');

  const afterLastRow = sheet.getLastRow();
  if (afterLastRow !== beforeLastRow + 1) {
    Logger.log('testSheets: FAIL — row not appended (before=' + beforeLastRow + ', after=' + afterLastRow + ')');
    return;
  }

  // Read it back
  const row = sheet.getRange(afterLastRow, 1, 1, 7).getValues()[0];
  Logger.log('testSheets: written row: ' + JSON.stringify(row));
  if (String(row[0]) !== '9999' || String(row[1]) !== '99999') {
    Logger.log('testSheets: FAIL — read-back mismatch');
    return;
  }

  // Delete it
  deleteResults('99999', 9999, 9999);
  if (sheet.getLastRow() !== beforeLastRow) {
    Logger.log('testSheets: FAIL — row not deleted');
    return;
  }

  Logger.log('testSheets: PASS');
}
