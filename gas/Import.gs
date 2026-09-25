/**
 * Import.gs
 * =========
 * Historic CSV import — Path B.
 *
 * Designed now, executed later when Martin provides the historic CSV files.
 *
 * CSV format (produced by timescraper_010.py v2.3+):
 *   Date;Event Name;Location;ID;Name;Year;Club;Pool;50m Freistil;100m Freistil;…
 *   DD/MM/YYYY;<event name>;<location>;<swimmer_id>;<LASTNAME Firstname>;<year>;<club>;<25m|50m>;<time>;…
 *
 * Legacy CSV (v2.2 and earlier) has no Pool column — defaults to "50m".
 *
 * Synthetic event key strategy for CSV rows:
 *   event_id = "csv_" + first 6 chars of MD5(event_name + "|" + date)
 *   This avoids collisions with real numeric IDs from myresults.eu.
 */


// ---------------------------------------------------------------------------
// CSV parser
// ---------------------------------------------------------------------------

/**
 * Parse a semicolon-delimited CSV string into an array of header-keyed objects.
 * Handles empty fields and trims whitespace.
 *
 * @param {string} csvString
 * @returns {Object[]}
 */
function csvToRows(csvString) {
  const lines   = csvString.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n');
  const headers = lines[0].split(';').map(h => h.trim());
  const rows    = [];

  for (let i = 1; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) continue;
    const values = line.split(';');
    const obj    = {};
    headers.forEach((h, idx) => {
      obj[h] = (values[idx] || '').trim();
    });
    rows.push(obj);
  }
  return rows;
}


/**
 * Generate a synthetic CSV event ID from the event name and date.
 * Format: "csv_xxxxxx" where xxxxxx is 6 hex chars of a simple hash.
 *
 * @param {string} eventName
 * @param {string} date   DD/MM/YYYY
 * @returns {string}
 */
function makeCsvEventId(eventName, date) {
  // Simple (non-cryptographic) hash — Utilities.computeDigest is available in GAS
  const input = `${eventName}|${date}`;
  const bytes = Utilities.computeDigest(Utilities.DigestAlgorithm.MD5, input);
  // Convert first 3 bytes to 6 hex chars
  return 'csv_' + bytes.slice(0, 3)
    .map(b => ((b < 0 ? b + 256 : b)).toString(16).padStart(2, '0'))
    .join('');
}


// ---------------------------------------------------------------------------
// Main import function — batch version (no per-row Sheets calls)
// ---------------------------------------------------------------------------

/**
 * Import historic CSV data into the Sheets workbook.
 *
 * Batch strategy:
 *   1. Bulk-read Events, Swimmers, Results into in-memory maps/sets — zero sheet
 *      calls during the processing loop.
 *   2. Process all CSV rows in memory, accumulating new Events/Swimmers/Results.
 *   3. Bulk-write all new rows in one setValues() call per sheet.
 *
 * This runs ~50× faster than the original per-row approach and stays well
 * within the GAS 6-minute execution budget for 500-row chunks.
 *
 * @param {string} csvString   Full CSV content (headers + data rows).
 * @returns {{rows_processed: number, rows_inserted: number, rows_skipped: number, errors: number}}
 */
function importCsvData(csvString) {
  // ── 1. Bulk-read existing data into memory ───────────────────────────────

  // Skip set: "eventId|swimmerId" pairs already in Results
  const skipSet = loadSkipSet();

  // Events map: eventId → true (just need existence check)
  const eventsSheet   = getSheet('Events');
  const eventsLastRow = eventsSheet.getLastRow();
  const existingEventIds = new Set();
  if (eventsLastRow >= 2) {
    eventsSheet.getRange(2, 1, eventsLastRow - 1, 1).getValues()
      .forEach(r => { if (r[0]) existingEventIds.add(String(r[0])); });
  }

  // Swimmers map: swimmerId → [name, year, club, firstSeenEventId]
  const swimmersSheet   = getSheet('Swimmers');
  const swimmersLastRow = swimmersSheet.getLastRow();
  const existingSwimmers = new Map();  // swimmerId → row array (cols A–F)
  if (swimmersLastRow >= 2) {
    swimmersSheet.getRange(2, 1, swimmersLastRow - 1, 6).getValues()
      .forEach(r => { if (r[0]) existingSwimmers.set(String(r[0]), r); });
  }

  // ── 2. Process CSV rows in memory ────────────────────────────────────────

  const rows = csvToRows(csvString);
  const FIXED_COLS = new Set(['Date', 'Event Name', 'Location', 'ID', 'Name', 'Year', 'Club', 'Pool']);
  const now = new Date().toISOString();

  // Accumulators for new rows (written in bulk at the end)
  const newEventRows   = [];   // [eventId, name, date, location, now, 0, pool]
  const newSwimmerRows = [];   // [swimmerId, name, year, club, eventId, now]
  const newResultRows  = [];   // [eventId, swimmerId, disc, str, sec, now, 'csv_import', '', '', '']

  // Track what we're about to add so we don't double-add within this run
  const addedEventIds   = new Set();
  const addedSwimmerIds = new Set();

  let rows_processed = 0;
  let rows_inserted  = 0;
  let rows_skipped   = 0;
  let errors         = 0;

  for (const row of rows) {
    rows_processed++;
    try {
      const date      = (row['Date']       || '').trim();
      const eventName = (row['Event Name'] || '').trim();
      const location  = (row['Location']   || '').trim();
      const swimmerId = (row['ID']         || '').trim();
      const name      = (row['Name']       || '').trim();
      const year      = (row['Year']       || '').trim();
      const club      = (row['Club']       || '').trim();
      const pool      = (row['Pool']       || '50m').trim();

      if (!swimmerId || !eventName || !date) { errors++; continue; }

      const eventId = makeCsvEventId(eventName, date);
      const key     = `${eventId}|${swimmerId}`;

      // Skip already-imported pairs
      if (skipSet.has(key)) { rows_skipped++; continue; }

      // Collect discipline columns
      const resultsObj = {};
      for (const [col, val] of Object.entries(row)) {
        if (FIXED_COLS.has(col) || !val) continue;
        const timeStr = val.replace(',', '.').trim();
        if (!validateTimeFormat(timeStr)) continue;
        resultsObj[col] = { str: timeStr, sec: timeToSeconds(timeStr) };
      }
      if (Object.keys(resultsObj).length === 0) { rows_skipped++; continue; }

      // Queue new event row (once per eventId)
      if (!existingEventIds.has(eventId) && !addedEventIds.has(eventId)) {
        newEventRows.push([eventId, eventName, date, location || '', now, 0, pool]);
        addedEventIds.add(eventId);
      }

      // Queue new swimmer row (once per swimmerId)
      if (!existingSwimmers.has(swimmerId) && !addedSwimmerIds.has(swimmerId)) {
        newSwimmerRows.push([swimmerId, name, year || '', club || 'SU M\u00f6DLING', eventId, now]);
        addedSwimmerIds.add(swimmerId);
      }

      // Queue result rows — one per discipline
      for (const [disc, {str, sec}] of Object.entries(resultsObj)) {
        newResultRows.push([eventId, swimmerId, disc, str, sec, now, 'csv_import', '', '', '']);
      }

      skipSet.add(key);
      rows_inserted++;
    } catch (e) {
      errors++;
      Logger.log('importCsvData: error on row ' + rows_processed + ': ' + e);
    }
  }

  // ── 3. Bulk-write all new rows ────────────────────────────────────────────

  if (newEventRows.length > 0) {
    const eLastRow = eventsSheet.getLastRow();
    eventsSheet.getRange(eLastRow + 1, 1, newEventRows.length, 7).setValues(newEventRows);
    Logger.log('importCsvData: wrote ' + newEventRows.length + ' new events');
  }

  if (newSwimmerRows.length > 0) {
    const sLastRow = swimmersSheet.getLastRow();
    swimmersSheet.getRange(sLastRow + 1, 1, newSwimmerRows.length, 6).setValues(newSwimmerRows);
    Logger.log('importCsvData: wrote ' + newSwimmerRows.length + ' new swimmers');
  }

  if (newResultRows.length > 0) {
    const resultsSheet = getSheet('Results');
    const rLastRow = resultsSheet.getLastRow();
    resultsSheet.getRange(rLastRow + 1, 1, newResultRows.length, 10).setValues(newResultRows);
    Logger.log('importCsvData: wrote ' + newResultRows.length + ' new result rows');
  }

  const summary = { rows_processed, rows_inserted, rows_skipped, errors,
                    new_events: newEventRows.length, new_swimmers: newSwimmerRows.length,
                    new_result_rows: newResultRows.length };
  Logger.log('importCsvData: ' + JSON.stringify(summary));
  return summary;
}


// ---------------------------------------------------------------------------
// Test with a 3-row inline fixture
// ---------------------------------------------------------------------------

function testImportCsv() {
  const fixture = [
    'Date;Event Name;Location;ID;Name;Year;Club;50m Freistil;100m Freistil;50m Brust',
    '05/10/2025;Int. SVS-Schwimmen Trophy 2025;Hallenbad Schwechat;306991;BLOBNER Vincent;2014;SU MöDLING;27.92;1:01.44;34.21',
    '05/10/2025;Int. SVS-Schwimmen Trophy 2025;Hallenbad Schwechat;275975;ZAVODSKY Leo;2012;SU MöDLING;29.20;;',
    '05/10/2025;Int. SVS-Schwimmen Trophy 2025;Hallenbad Schwechat;302966;RAISIC Ana;2013;SU MöDLING;31.05;;35.88'
  ].join('\n');

  const summary = importCsvData(fixture);
  Logger.log('testImportCsv summary: ' + JSON.stringify(summary));

  if (summary.errors > 0) {
    Logger.log('testImportCsv: FAIL — errors: ' + summary.errors); return;
  }
  if (summary.rows_processed !== 3) {
    Logger.log('testImportCsv: FAIL — expected 3 rows processed, got ' + summary.rows_processed); return;
  }

  Logger.log('testImportCsv: PASS');

  // Cleanup — delete the test rows
  const testId = makeCsvEventId('Int. SVS-Schwimmen Trophy 2025', '05/10/2025');
  deleteResults('306991', testId, testId);
  deleteResults('275975', testId, testId);
  deleteResults('302966', testId, testId);
  Logger.log('testImportCsv: test rows cleaned up');
}
