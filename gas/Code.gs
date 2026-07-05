/**
 * Code.gs
 * =======
 * Main entry point and trigger setup for the SwimmingResultsScraper.
 *
 * main()         — nightly orchestrator: club-first discovery → fetch → parse → write
 * setupTrigger() — register the 02:00 Vienna-time daily trigger (run once manually)
 * testMain()     — validates against event 2341 only
 */

// ---------------------------------------------------------------------------
// URL constants
// ---------------------------------------------------------------------------

const RECENT_PAGE_URL          = 'https://myresults.eu/de-AT/Meets/Recent';
const CLUB_PAGE_URL_TEMPLATE   = 'https://myresults.eu/de-AT/Meets/Recent/{event}/Club/{club}';
const PARTICIPANT_URL_TEMPLATE = 'https://myresults.eu/de-AT/Meets/Recent/{event}/Participant/{participant}';


// ---------------------------------------------------------------------------
// main() — nightly pipeline
// ---------------------------------------------------------------------------

/**
 * Full nightly pipeline:
 *  1. Read config
 *  2. Load skip set (already-stored results)
 *  3. Process any pending Rescan_Queue rows
 *  4. Fetch Recent page → event list
 *  5. Discover new events via Club/6614 page → participant IDs
 *  6. Build participant task list (skip already done)
 *  7. Fetch + parse all participant pages
 *  8. Write to Sheets
 *  9. Append Log row
 */
function main() {
  const runStart   = new Date();
  const MAX_MS     = 300000;   // stop after 5 min to stay inside the 6-min GAS limit

  // Counters
  let eventsChecked       = 0;
  let eventsNew           = 0;
  let swimmersDiscovered  = 0;
  let resultsAdded        = 0;
  let resultsSkipped      = 0;
  let errors              = 0;
  let rescansProcessed    = 0;
  const notes             = [];

  try {
    // ── Step 1: Config ────────────────────────────────────────────────────
    const cfg = readConfig();

    // ── Step 2: Load skip set ─────────────────────────────────────────────
    const skipSet     = loadSkipSet();
    const eventsCache = loadEventsCache();

    // ── Step 3: Rescan_Queue ──────────────────────────────────────────────
    const rescanTasks   = [];    // {event_id, swimmer_id, rowIndex}
    const rescanSheet   = getSheet('Rescan_Queue');
    const rescanLastRow = rescanSheet.getLastRow();

    if (rescanLastRow >= 2) {
      const rescanRows = rescanSheet.getRange(2, 1, rescanLastRow - 1, 5).getValues();
      for (let ri = 0; ri < rescanRows.length; ri++) {
        const [swimmerId, startId, endId, status] = rescanRows[ri];
        if (String(status).toLowerCase().trim() !== 'pending') continue;

        // Mark processing
        rescanSheet.getRange(ri + 2, 4).setValue('processing');

        // Delete existing Results rows for this range so they get re-fetched
        deleteResults(String(swimmerId), parseInt(startId, 10), parseInt(endId, 10));

        for (let eid = parseInt(startId, 10); eid <= parseInt(endId, 10); eid++) {
          rescanTasks.push({ event_id: eid, swimmer_id: String(swimmerId), rescanRowIndex: ri + 2 });
        }
        rescansProcessed++;
      }
    }

    // ── Step 4: Fetch Recent page ─────────────────────────────────────────
    const recentHtml = fetchHtml(RECENT_PAGE_URL, cfg);
    if (!recentHtml) {
      notes.push('ERROR: Could not fetch Recent page');
      errors++;
    }
    const recentEvents = recentHtml ? parseRecentPage(recentHtml) : [];
    eventsChecked = recentEvents.length;

    // ── Step 5: Discover new events (Club page) ───────────────────────────
    const newEventIds = recentEvents
      .filter(e => !eventsCache[String(e.event_id)])
      .map(e => e.event_id);

    // knownSwimmerIds: set of swimmer IDs already in the Swimmers tab (load once)
    let knownSwimmerSet = new Set(loadSwimmers().map(s => s.swimmer_id));

    // eventParticipants: tracks which (event_id, swimmer_id) pairs were found on club pages
    // Used in Step 6 to avoid cross-joining ALL events × ALL swimmers
    const eventParticipants = {};  // { eventId: [swimmerId, ...] }

    if (newEventIds.length > 0) {
      const clubUrls = newEventIds.map(
        eid => CLUB_PAGE_URL_TEMPLATE
          .replace('{event}', eid)
          .replace('{club}',  cfg.club_id)
      );

      const clubHtmlMap = fetchAllHtml(clubUrls, cfg);

      for (const eid of newEventIds) {
        const url       = CLUB_PAGE_URL_TEMPLATE.replace('{event}', eid).replace('{club}', cfg.club_id);
        const clubHtml  = clubHtmlMap[url];
        const eventMeta = recentEvents.find(e => e.event_id === eid) || {};

        if (!clubHtml) {
          errors++;
          upsertEvent(eid, eventMeta.event_name || 'Unknown', eventMeta.date || 'Unknown', null, 0);
          eventsNew++;
          eventsCache[String(eid)] = { event_name: eventMeta.event_name || 'Unknown', date: eventMeta.date || 'Unknown', location: '' };
          eventParticipants[eid] = [];
          continue;
        }

        const participants = parseClubPage(clubHtml);
        upsertEvent(eid, eventMeta.event_name || 'Unknown', eventMeta.date || 'Unknown', null, participants.length);
        eventsNew++;
        eventsCache[String(eid)] = { event_name: eventMeta.event_name || 'Unknown', date: eventMeta.date || 'Unknown', location: '' };
        eventParticipants[eid] = participants.map(p => String(p.participant_id));

        // Add any newly discovered swimmers in one pass (no per-participant Sheets read)
        for (const p of participants) {
          const sidStr = String(p.participant_id);
          if (!knownSwimmerSet.has(sidStr)) {
            upsertSwimmer(sidStr, p.name, 'Unknown', 'Unknown', eid);
            knownSwimmerSet.add(sidStr);
            swimmersDiscovered++;
          }
        }
      }
    }

    // ── Step 6: Build participant task list ───────────────────────────────
    // Only queue (event, swimmer) pairs that were actually seen on a club page
    // OR that are in the rescan list. Never cross-join all events × all swimmers.
    const tasks = [];

    // From club page discoveries (new events only)
    for (const [eid, swimmerIds] of Object.entries(eventParticipants)) {
      for (const sidStr of swimmerIds) {
        const key = `${eid}|${sidStr}`;
        if (!skipSet.has(key)) {
          tasks.push({ event_id: Number(eid), swimmer_id: sidStr });
        } else {
          resultsSkipped++;
        }
      }
    }

    // Also check existing events in eventsCache that were already known —
    // any swimmers in Swimmers tab that don't yet have results for those events.
    // This handles: new swimmer added to Swimmers tab after event was already cached.
    const existingEventIds = Object.keys(eventsCache)
      .map(Number)
      .filter(eid => !(eid in eventParticipants));  // already-known events only

    for (const eid of existingEventIds) {
      for (const sidStr of knownSwimmerSet) {
        const key = `${eid}|${sidStr}`;
        if (!skipSet.has(key)) {
          tasks.push({ event_id: eid, swimmer_id: sidStr });
        } else {
          resultsSkipped++;
        }
      }
    }

    // Add rescan tasks (bypass skip set)
    for (const rt of rescanTasks) {
      tasks.push({ event_id: rt.event_id, swimmer_id: rt.swimmer_id });
    }

    // ── Step 7: Fetch + parse participant pages (in time-budgeted batches) ─
    const BATCH = cfg.max_parallel || 100;
    let tasksRemaining = 0;

    for (let batchStart = 0; batchStart < tasks.length; batchStart += BATCH) {
      // Stop gracefully if we are within 1 min of the limit
      if ((new Date() - runStart) > MAX_MS) {
        tasksRemaining = tasks.length - batchStart;
        notes.push(`Time budget reached — ${tasksRemaining} tasks deferred to next run`);
        Logger.log(`main(): time budget reached at batch ${batchStart}, ${tasksRemaining} tasks deferred`);
        break;
      }

      const batch = tasks.slice(batchStart, batchStart + BATCH);
      const participantUrls = batch.map(t =>
        PARTICIPANT_URL_TEMPLATE
          .replace('{event}',       t.event_id)
          .replace('{participant}', t.swimmer_id)
      );

      const htmlMap = fetchAllHtml(participantUrls, cfg);

      for (let ti = 0; ti < batch.length; ti++) {
      const task = batch[ti];
      const url  = PARTICIPANT_URL_TEMPLATE
        .replace('{event}',       task.event_id)
        .replace('{participant}', task.swimmer_id);
      const html = htmlMap[url];

      if (!html) { errors++; continue; }

      // Parse swimmer info
      const swimmer = parseParticipant(html);
      if (swimmer.name === 'Unknown' && swimmer.club === 'Unknown') continue;

      // Enrich metadata if not yet in cache
      if (!eventsCache[String(task.event_id)] || eventsCache[String(task.event_id)].location === '') {
        const meta = parseMetadata(html, task.event_id);
        upsertEvent(task.event_id, meta.event, meta.date, meta.location, null);
        if (eventsCache[String(task.event_id)]) {
          eventsCache[String(task.event_id)].location = meta.location;
        }
      }

      // Update swimmer record (fill in any "Unknown" fields)
      upsertSwimmer(task.swimmer_id, swimmer.name, swimmer.birth_year, swimmer.club, task.event_id);

      // Parse and write results
      const results = parseResults(html, cfg);
      if (Object.keys(results).length > 0) {
        appendResults(task.event_id, task.swimmer_id, results, 'scraper');
        resultsAdded += Object.keys(results).length;
      }
      } // end batch inner loop
    }   // end batch outer loop

    if (tasksRemaining > 0) {
      notes.push(`Re-run main() to process remaining ${tasksRemaining} tasks`);
    }

    // ── Step 8: Mark rescans done ─────────────────────────────────────────
    const rescanRowsDone = new Set();
    for (const rt of rescanTasks) {
      if (rt.rescanRowIndex && !rescanRowsDone.has(rt.rescanRowIndex)) {
        markRescanDone(rt.rescanRowIndex);
        rescanRowsDone.add(rt.rescanRowIndex);
      }
    }

  } catch (e) {
    errors++;
    notes.push('EXCEPTION: ' + e.message);
    Logger.log('main() exception: ' + e + '\n' + e.stack);
  } finally {
    // ── Step 9: Log ───────────────────────────────────────────────────────
    const durationSec = (new Date() - runStart) / 1000;
    appendLog(
      runStart, eventsChecked, eventsNew, swimmersDiscovered,
      resultsAdded, resultsSkipped, errors, rescansProcessed,
      durationSec, notes.join('; ')
    );
    Logger.log(
      `main() done in ${durationSec.toFixed(1)}s — ` +
      `events_checked=${eventsChecked}, events_new=${eventsNew}, ` +
      `swimmers_discovered=${swimmersDiscovered}, results_added=${resultsAdded}, ` +
      `results_skipped=${resultsSkipped}, errors=${errors}`
    );
  }
}


// ---------------------------------------------------------------------------
// Nightly trigger setup
// ---------------------------------------------------------------------------

/**
 * Register a daily 02:00 Vienna-time trigger for main().
 * Run this ONCE manually from the Script Editor.
 * Deletes any existing "main" trigger first to avoid duplicates.
 */
function setupTrigger() {
  // Remove existing triggers for main()
  const existing = ScriptApp.getProjectTriggers();
  for (const trigger of existing) {
    if (trigger.getHandlerFunction() === 'main') {
      ScriptApp.deleteTrigger(trigger);
      Logger.log('setupTrigger: deleted existing trigger');
    }
  }

  ScriptApp.newTrigger('main')
    .timeBased()
    .everyDays(1)
    .atHour(2)
    .inTimezone('Europe/Vienna')
    .create();

  Logger.log('setupTrigger: created daily 02:00 Vienna trigger for main()');
}


// ---------------------------------------------------------------------------
// Test — validates against event 2341 only
// ---------------------------------------------------------------------------

/**
 * Targeted integration test: event 2341, club 6614.
 * Expected: 4 SU MöDLING swimmers, 6 disciplines for swimmer 306991.
 */
function testMain() {
  const cfg = readConfig();

  // 1. Club page
  const clubUrl  = CLUB_PAGE_URL_TEMPLATE.replace('{event}', 2341).replace('{club}', cfg.club_id);
  const clubHtml = fetchHtml(clubUrl, cfg);
  if (!clubHtml) { Logger.log('testMain: FAIL — no club HTML'); return; }

  const participants = parseClubPage(clubHtml);
  Logger.log('testMain: participants = ' + JSON.stringify(participants));
  if (participants.length !== 4) {
    Logger.log('testMain: FAIL — expected 4 participants, got ' + participants.length); return;
  }

  // 2. Participant page for BLOBNER Vincent
  const pUrl  = PARTICIPANT_URL_TEMPLATE.replace('{event}', 2341).replace('{participant}', 306991);
  const pHtml = fetchHtml(pUrl, cfg);
  if (!pHtml) { Logger.log('testMain: FAIL — no participant HTML'); return; }

  const swimmer = parseParticipant(pHtml);
  const results = parseResults(pHtml, cfg);
  const meta    = parseMetadata(pHtml, 2341);

  Logger.log('testMain: swimmer = ' + JSON.stringify(swimmer));
  Logger.log('testMain: meta    = ' + JSON.stringify(meta));
  Logger.log('testMain: results = ' + JSON.stringify(results));

  if (swimmer.name !== 'BLOBNER Vincent') {
    Logger.log('testMain: FAIL — wrong name: ' + swimmer.name); return;
  }
  if (meta.event !== '53. Internationales Swimcity Wels Meeting') {
    Logger.log('testMain: FAIL — wrong event: ' + meta.event); return;
  }
  if (Object.keys(results).length !== 6) {
    Logger.log('testMain: FAIL — expected 6 disciplines, got ' + Object.keys(results).length); return;
  }

  Logger.log('testMain: PASS');
}
