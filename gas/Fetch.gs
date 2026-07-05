/**
 * Fetch.gs
 * ========
 * HTTP layer using UrlFetchApp.
 * Replaces requests.Session + fetch_html() from the Python desktop tool.
 *
 * Two public functions:
 *   fetchHtml(url, cfg)           – single URL, used for testing
 *   fetchAllHtml(urls, cfg)       – batched parallel fetch, returns {url: html|null}
 */

// Browser-mimicking headers — identical to Python HTTP_HEADERS dict (lines 148–156).
const HTTP_HEADERS = {
  'User-Agent':      'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                   + 'AppleWebKit/537.36 (KHTML, like Gecko) '
                   + 'Chrome/124.0.0.0 Safari/537.36',
  'Accept':          'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
  'Accept-Language': 'de-AT,de;q=0.9,en;q=0.7'
};


/**
 * Fetch a single URL and return its HTML as a string, or null on failure.
 * Retries up to cfg.max_retries times with cfg.retry_delays backoff.
 *
 * @param {string} url
 * @param {{max_retries: number, retry_delays: number[], page_timeout: number}} cfg
 * @returns {string|null}
 */
function fetchHtml(url, cfg) {
  // Defensive defaults so the function works even if cfg is partial/undefined
  const maxRetries  = (cfg && cfg.max_retries  != null) ? cfg.max_retries  : 3;
  const retryDelays = (cfg && cfg.retry_delays)         ? cfg.retry_delays : [1, 2, 4];

  const options = {
    method:             'get',
    headers:            HTTP_HEADERS,
    muteHttpExceptions: true,
    followRedirects:    true
  };

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    if (attempt > 0) {
      const delayMs = ((retryDelays[attempt - 1]) || 4) * 1000;
      Utilities.sleep(delayMs);
    }
    try {
      const resp = UrlFetchApp.fetch(url, options);
      if (resp.getResponseCode() === 200) {
        return resp.getContentText('UTF-8');
      }
      Logger.log(`fetchHtml: HTTP ${resp.getResponseCode()} for ${url} (attempt ${attempt + 1})`);
    } catch (e) {
      Logger.log(`fetchHtml: Exception for ${url}: ${e} (attempt ${attempt + 1})`);
    }
  }
  return null;
}


/**
 * Fetch many URLs in parallel using UrlFetchApp.fetchAll().
 * Splits into chunks of cfg.max_parallel (≤ 100, the GAS batch limit).
 * Failed URLs are retried up to cfg.max_retries times.
 *
 * @param {string[]} urls
 * @param {{max_parallel: number, max_retries: number, retry_delays: number[]}} cfg
 * @returns {{[url: string]: string|null}}  Map of url → html (or null on failure)
 */
function fetchAllHtml(urls, cfg) {
  const result   = {};
  const chunkSize = Math.min(cfg.max_parallel || 100, 100);

  // Build request objects
  function makeRequests(urlList) {
    return urlList.map(url => ({
      url,
      method:             'get',
      headers:            HTTP_HEADERS,
      muteHttpExceptions: true,
      followRedirects:    true
    }));
  }

  // Chunk the URL list
  for (let start = 0; start < urls.length; start += chunkSize) {
    const chunk     = urls.slice(start, start + chunkSize);
    let   pending   = chunk.slice();   // URLs still needing a successful response
    let   attempt   = 0;

    while (pending.length > 0 && attempt <= cfg.max_retries) {
      if (attempt > 0) {
        const delayMs = ((cfg.retry_delays[attempt - 1]) || 4) * 1000;
        Utilities.sleep(delayMs);
      }

      const requests  = makeRequests(pending);
      const responses = UrlFetchApp.fetchAll(requests);
      const stillFailing = [];

      for (let i = 0; i < responses.length; i++) {
        const url  = pending[i];
        const resp = responses[i];
        if (resp.getResponseCode() === 200) {
          result[url] = resp.getContentText('UTF-8');
        } else {
          Logger.log(`fetchAllHtml: HTTP ${resp.getResponseCode()} for ${url} (attempt ${attempt + 1})`);
          stillFailing.push(url);
        }
      }

      pending = stillFailing;
      attempt++;
    }

    // Mark permanently failed URLs as null
    for (const url of pending) {
      result[url] = null;
    }
  }

  return result;
}


// ---------------------------------------------------------------------------
// Test helper — run in the Script Editor to verify the fetch layer works.
// ---------------------------------------------------------------------------
function testFetchHtml() {
  const cfg = readConfig();
  const url = 'https://myresults.eu/de-AT/Meets/Recent/2341/Participant/306991';
  const html = fetchHtml(url, cfg);
  if (!html) {
    Logger.log('testFetchHtml: FAIL — no HTML returned');
    return;
  }
  Logger.log('testFetchHtml: received ' + html.length + ' chars');
  Logger.log('testFetchHtml: first 500 chars: ' + html.substring(0, 500));
  Logger.log('testFetchHtml: PASS');
}
