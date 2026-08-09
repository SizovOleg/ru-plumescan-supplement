/**
 * @fileoverview Region presets — curated emitter region zoom hooks.
 *
 * 8-region preset selector (per P-05 spec). ui.Select onChange → leftMap.setCenter.
 * Each preset carries lon/lat/zoom + short context note + relevant gas (для
 * future multi-gas filtering: NO2 cluster ≠ CH4 cluster).
 *
 * Future extension: Task 2 on-demand text-search hook stub stored как
 * `exports.onDemandSearchPlaceholder()` — currently returns null; replaced
 * when Task 2 operational scope kicks in.
 *
 * @module app/region_presets
 */

/* eslint-disable no-undef */

/**
 * Preset region schema.
 *
 *   id              — short key
 *   label           — display string
 *   lon, lat        — center coordinates
 *   zoom            — initial zoom level
 *   relevant_gases  — array; presets that don't apply к active gas can be hidden
 *   note            — short tooltip / context
 *
 * @type {!Array<!Object>}
 */
var REGION_PRESETS = [
  {
    id: 'aoi_overview',
    label: 'AOI overview',
    lon: 77.5, lat: 62.5, zoom: 4,
    relevant_gases: ['CH4', 'NO2', 'SO2', 'CO2'],
    note: 'Full Western Siberia AOI 60-95°E × 50-75°N'
  },
  {
    id: 'bovanenkovo',
    label: 'Bovanenkovo (Yamal gas)',
    lon: 68.5, lat: 70.5, zoom: 8,
    relevant_gases: ['CH4'],
    note: 'Bovanenkovo gas field, Schuit 2021 22 t/h gold-standard reference. Peak Yamal latitude — out-of-Schuit-hull artifact case.'
  },
  {
    id: 'yamburg',
    label: 'Yamburg (Yamal gas)',
    lon: 75.0, lat: 67.6, zoom: 8,
    relevant_gases: ['CH4'],
    note: 'Yamburg gas field, persistent CH4 emission source. Multiple Path E detections 2021-2024.'
  },
  {
    id: 'sabetta',
    label: 'Sabetta LNG',
    lon: 72.0, lat: 71.3, zoom: 8,
    relevant_gases: ['CH4'],
    note: 'Yamal LNG complex. High-latitude (71.3°N) detection zone.'
  },
  {
    id: 'surgut',
    label: 'Surgut (KhMAO oil)',
    lon: 73.4, lat: 61.2, zoom: 8,
    relevant_gases: ['CH4', 'NO2'],
    note: 'KhMAO oil cluster ~71°E 60-61°N. Densest 2024 P-02.0a baseline cluster (ISSUE 1 visual anchor).'
  },
  {
    id: 'chelyabinsk',
    label: 'Chelyabinsk (Urals TPP)',
    lon: 61.0, lat: 56.7, zoom: 8,
    relevant_gases: ['CH4', 'NO2', 'SO2'],
    note: 'Chelyabinsk thermal power plants. 2024 MARS-validated frontier (out-of-Schuit hull + matched к MARS at 39 km).'
  },
  {
    id: 'kuzbass',
    label: 'Kuzbass (coal)',
    lon: 87.5, lat: 54.0, zoom: 8,
    relevant_gases: ['CH4', 'NO2'],
    note: 'Kuzbass coal basin. Regression test anchor (kuzbass_2022_09_20).'
  },
  {
    id: 'norilsk',
    label: 'Norilsk (metallurgy)',
    lon: 88.2, lat: 69.3, zoom: 7,
    relevant_gases: ['SO2'],
    note: 'Norilsk Cu-Ni-Pd metallurgy. SO2-dominant — placeholder для future SO2 catalog ingestion.'
  }
];

exports.REGION_PRESETS = REGION_PRESETS;

/** Filter presets к those applicable к given gas. */
exports.forGas = function(gasId) {
  return REGION_PRESETS.filter(function(p) {
    return p.relevant_gases.indexOf(gasId) >= 0;
  });
};

exports.get = function(presetId) {
  for (var i = 0; i < REGION_PRESETS.length; i++) {
    if (REGION_PRESETS[i].id === presetId) return REGION_PRESETS[i];
  }
  return null;
};

/**
 * STUB — Task 2 on-demand region/text-search hook.
 * Currently returns null. Replaced when Task 2 operational scope kicks in
 * (free-text region search + on-demand re-detection seam).
 *
 * @param {string} query — free-text input (placeholder)
 * @return {?Object} — preset-like {lon, lat, zoom, note} OR null
 */
exports.onDemandSearchPlaceholder = function(query) {
  // TODO: Task 2 — integrate с external geocoder OR fuzzy-match against
  // extended region list. Stub returns null = «use preset selector instead».
  return null;
};
