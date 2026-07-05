/**
 * Import.gs
 * =========
 * Historic CSV import — Path B.
 *
 * Designed now, executed later when Martin provides the historic CSV files.
 *
 * CSV format (produced by timescraper_010.py):
 *   Date;Event Name;Location;ID;Name;Year;Club;50m Freistil;100m Freistil;…
 *   DD/MM/YYYY;<event name>;<location>;<swimmer_id>;<LASTNAME Firstname>;<year>;<club>;<time>;…
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
// Main import function
// ---------------------------------------------------------------------------

/**
 * Import historic CSV data into the Sheets workbook.
 *
 * How to use:
 *   1. Open the Script Editor (Extensions → Apps Script).
 *   2. Paste the CSV content as the argument below and run:
 *        importCsvData(`Date;Event Name;Location;ID;Name;Year;Club;50m Freistil;…\n…rows…`);
 *
 * @param {string} csvString   Full CSV content (headers + data rows).
 * @returns {{rows_processed: number, rows_inserted: number, rows_skipped: number, errors: number}}
 */
function importCsvData(csvString) {
  const cfg     = readConfig();
  const skipSet = loadSkipSet();   // existing (event_id, swimmer_id) pairs

  const rows = csvToRows(csvString);

  let rows_processed = 0;
  let rows_inserted  = 0;
  let rows_skipped   = 0;
  let errors         = 0;

  // Fixed columns present in every CSV row
  const FIXED_COLS = new Set(['Date', 'Event Name', 'Location', 'ID', 'Name', 'Year', 'Club']);

  for (const row of rows) {
    rows_processed++;
    try {
      const date       = (row['Date']       || '').trim();
      const eventName  = (row['Event Name'] || '').trim();
      const location   = (row['Location']   || '').trim();
      const swimmerId  = (row['ID']         || '').trim();
      const name       = (row['Name']       || '').trim();
      const year       = (row['Year']       || '').trim();
      const club       = (row['Club']       || '').trim();

      if (!swimmerId || !eventName || !date) { errors++; continue; }

      // Resolve event ID
      const eventId = makeCsvEventId(eventName, date);

      // Upsert event and swimmer
      upsertEvent(eventId, eventName, date, location, null);
      upsertSwimmer(swimmerId, name, year, club, eventId);

      // Collect discipline columns
      const resultsObj = {};
      for (const [col, val] of Object.entries(row)) {
        if (FIXED_COLS.has(col) || !val) continue;
        const timeStr = val.replace(',', '.').trim();
        if (!validateTimeFormat(timeStr)) continue;
        resultsObj[col] = { str: timeStr, sec: timeToSeconds(timeStr) };
      }

      if (Object.keys(resultsObj).length === 0) { rows_skipped++; continue; }

      const key = `${eventId}|${swimmerId}`;
      if (skipSet.has(key)) { rows_skipped++; continue; }

      appendResults(eventId, swimmerId, resultsObj, 'csv_import');
      skipSet.add(key);
      rows_inserted++;
    } catch (e) {
      errors++;
      Logger.log(`importCsvData: error on row ${rows_processed}: ${e}`);
    }
  }

  const summary = { rows_processed, rows_inserted, rows_skipped, errors };
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
