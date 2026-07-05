/**
 * Config.gs
 * =========
 * Reads all configuration values from the "Config" sheet tab.
 * Replaces config.json + load_config() from the Python desktop tool.
 */

/**
 * Read all key/value rows from the Config sheet and return a typed config object.
 *
 * Expected sheet layout (columns A and B):
 *   club_id            6614
 *   club_name_match    SU MöDLING
 *   max_parallel       100
 *   page_timeout       15
 *   max_retries        3
 *   retry_delays       1,2,4
 *   translation_*      <German stroke name>
 *
 * @returns {{
 *   club_id: number,
 *   club_name_match: string,
 *   max_parallel: number,
 *   page_timeout: number,
 *   max_retries: number,
 *   retry_delays: number[],
 *   translations: {[eng: string]: string}
 * }}
 */
function readConfig() {
  const sheet = getSheet('Config');
  const rows  = sheet.getDataRange().getValues();   // [[key, value], ...]

  const raw = {};
  for (const [key, value] of rows) {
    const k = String(key).trim();
    if (k) raw[k] = value;
  }

  // Typed scalars
  const cfg = {
    club_id:          parseInt(raw['club_id'],         10),
    club_name_match:  String(raw['club_name_match'] || 'SU MöDLING').trim(),
    max_parallel:     parseInt(raw['max_parallel'],    10) || 100,
    page_timeout:     parseInt(raw['page_timeout'],    10) || 15,
    max_retries:      parseInt(raw['max_retries'],     10) || 3,
    retry_delays:     String(raw['retry_delays'] || '1,2,4')
                        .split(',')
                        .map(s => parseFloat(s.trim()))
                        .filter(n => !isNaN(n)),
    translations:     {}
  };

  // Collect translation_* keys into a map  {English: German}
  for (const [k, v] of Object.entries(raw)) {
    if (k.startsWith('translation_')) {
      const engKey = k.replace('translation_', '');
      cfg.translations[engKey] = String(v).trim();
    }
  }

  // Fallback translations if Config tab is incomplete
  const defaultTranslations = {
    Backstroke:   'Rücken',
    Breaststroke: 'Brust',
    Butterfly:    'Schmetterling',
    Freestyle:    'Freistil',
    'Ind. Medley': 'Lagen',
    Medley:       'Lagen',
    Free:         'Freistil'
  };
  for (const [k, v] of Object.entries(defaultTranslations)) {
    if (!cfg.translations[k]) cfg.translations[k] = v;
  }

  return cfg;
}


// ---------------------------------------------------------------------------
// Test helper — run this once in the Script Editor to verify the Config tab.
// ---------------------------------------------------------------------------
function testReadConfig() {
  const cfg = readConfig();
  Logger.log('club_id         : ' + cfg.club_id);
  Logger.log('club_name_match : ' + cfg.club_name_match);
  Logger.log('max_parallel    : ' + cfg.max_parallel);
  Logger.log('page_timeout    : ' + cfg.page_timeout);
  Logger.log('max_retries     : ' + cfg.max_retries);
  Logger.log('retry_delays    : ' + JSON.stringify(cfg.retry_delays));
  Logger.log('translations    : ' + JSON.stringify(cfg.translations));
  Logger.log('testReadConfig  : PASS');
}
