/**
 * @fileoverview Gas Registry — gas-agnostic catalog configuration.
 *
 * Single source of truth для per-gas catalog metadata, schema, retrieval
 * parameters. Adding a new gas (NO2/SO2/CO2) = adding an entry to this
 * registry, не rewriting the App. Layer-factory + styling + popup
 * dispatch off `active: true` flag.
 *
 * Hard requirement (P-05 spec):
 *   asset schema extensible (CH4 default, NO2/SO2/CO2 slottable без rewrite)
 *   gas-specific config: seasonal_scope, z_threshold, units, colormap
 *
 * @module app/gas_registry
 */

/* eslint-disable no-undef */

var PROJECT_ID = 'nodal-thunder-481307-u1';
var ASSET_ROOT = 'projects/' + PROJECT_ID + '/assets/RuPlumeScan';

/**
 * Per-gas configuration schema.
 *
 * Required fields:
 *   active            — boolean; if false, layer factory skips this gas
 *   name              — display label
 *   formula           — pretty-printed chemical formula
 *   catalog_root      — GEE asset path к gas-specific catalog parent
 *   years             — array of year strings for which events_YYYY exists
 *   p020a_baseline    — optional: paths к pre-Path-E baseline (для ISSUE 1)
 *   seasonal_scope    — {months: [..], note: '...'} active detection window
 *   z_threshold       — minimum z-score для detection (DNA v2.4 §1.2)
 *   units             — display unit for magnitude (z-score / ppb / molec/cm²)
 *   colormap_z        — palette array used by styling module
 *   references        — array of reference catalog ids (см. reference_registry)
 *   match_radius_km   — DNA empirical match radius (used in popup matched_X flag interp)
 *
 * @type {!Object<string, !Object>}
 */
var GAS_REGISTRY = {

  CH4: {
    active: true,
    name: 'Methane',
    formula: 'CH₄',
    catalog_root: ASSET_ROOT + '/catalog/CH4',
    years: ['2019', '2020', '2021', '2022', '2023', '2024', '2025'],
    catalog_template: 'events_{year}',
    p020a_baseline: {
      enabled: true,
      asset_template: ASSET_ROOT + '/catalog/CH4/events_{year}_p020a_baseline',
      available_years: ['2019', '2022', '2024'],
      note: 'P-02.0a multi-year baseline (pre-Path E pivot). Used in 2024 investigation view для ISSUE 1 density comparison.'
    },
    seasonal_scope: {
      months: [3, 4, 5, 6, 7, 8, 9, 10],
      note: 'M03-M10 — effective sun angle / SWIR retrieval season constraint (DNA v2.4 §3.2)'
    },
    z_threshold: 3.0,
    units: 'z-score',
    delta_units: 'ppb',  // CH4 column delta in ppb (TROPOMI L3 XCH4 units)
    magnitude_field: 'max_z',
    colormap_z: ['#4a90e2', '#7ec850', '#f5b400', '#e57373', '#c62828'],
    colormap_z_breaks: [3.0, 5.0, 7.0, 10.0, 15.0],
    references: ['schuit2023', 'imeo_mars'],
    match_radius_km: 150,
    algorithm_version: 'v3.1.5 Path E',
    // P-02.0d frozen catalog (zapsib-clipped). Verified 2026-07-05 —
    // docs/p_02_0d_validation_numbers.md. Числа фиксированы (каталог заморожен),
    // поэтому статистика и годовой график читаются из конфига: 0 EECU.
    catalog_stats: {
      n_total: 122,
      n_valid: 88,
      n_artifact: 34,
      n_super_emitter_z_gt_5: 80,
      max_z_observed: 85.47,
      n_flare: 96,       // viirs_flare_high 89 + viirs_flare_low 7
      n_gas_field: 25,
      n_tpp: 1,
      tier1_precision: 0.438,
      tier1_recall: 0.469,
      tier2_combined_precision: 0.654,
      note: 'AOI = zapsib. Tier 1 PASS (43.8%/46.9%). Tier 2 PASS combined 2023-2025 (65.4%); 2022 excluded (0 MARS inside boundary).'
    },
    // Годовая разбивка для интерактивного графика (valid / artifact)
    per_year_stats: {
      '2019': {valid: 11, artifact: 5},
      '2020': {valid: 8,  artifact: 1},
      '2021': {valid: 14, artifact: 2},
      '2022': {valid: 3,  artifact: 4},
      '2023': {valid: 8,  artifact: 13},
      '2024': {valid: 31, artifact: 8},
      '2025': {valid: 13, artifact: 1}
    }
  },

  // ─────────────────────────────────────────────────────────────────────
  // STUB demonstrations — config-only, active=false. Adding a real catalog
  // for these gases = flip active к true + populate years + upload assets.
  // No App-code rewrite required.
  // ─────────────────────────────────────────────────────────────────────

  NO2: {
    active: false,  // stub: NO2 Path E catalog not yet produced
    name: 'Nitrogen Dioxide',
    formula: 'NO₂',
    catalog_root: ASSET_ROOT + '/catalog/NO2',
    years: [],
    catalog_template: 'events_{year}',
    p020a_baseline: {enabled: false},
    seasonal_scope: {
      months: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
      note: 'Winter OK except December polar night (lat > 67°N solar zenith angle constraint)'
    },
    z_threshold: 3.0,
    units: 'z-score',
    delta_units: 'molec/cm²',  // NO2 column delta
    magnitude_field: 'max_z',
    colormap_z: ['#d4f1f4', '#75e6da', '#189ab4', '#05445e', '#0c2461'],
    colormap_z_breaks: [3.0, 5.0, 7.0, 10.0, 15.0],
    references: [],
    match_radius_km: 100,
    algorithm_version: 'pending',
    catalog_stats: {note: 'No catalog yet; awaiting Phase 6 NO2 Path E port'}
  },

  SO2: {
    active: false,
    name: 'Sulfur Dioxide',
    formula: 'SO₂',
    catalog_root: ASSET_ROOT + '/catalog/SO2',
    years: [],
    catalog_template: 'events_{year}',
    p020a_baseline: {enabled: false},
    seasonal_scope: {
      months: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
      note: 'Winter OK except December polar night (TROPOMI SO2 retrieval requires sun)'
    },
    z_threshold: 3.0,
    units: 'z-score',
    delta_units: 'DU',  // SO2 Dobson Units
    magnitude_field: 'max_z',
    colormap_z: ['#fff5e6', '#ffcc99', '#ff9933', '#cc5200', '#661a00'],
    colormap_z_breaks: [3.0, 5.0, 7.0, 10.0, 15.0],
    references: [],
    match_radius_km: 100,
    algorithm_version: 'pending',
    catalog_stats: {note: 'No catalog yet; SO2 specific к Norilsk + Karabash + minor power'}
  }
  // CO2 removed (P-02.0d-ux2) — not planned.
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Resolve catalog asset id for (gas, year).
 * @param {string} gasId — key of GAS_REGISTRY
 * @param {string} year — string like '2024'
 * @return {string} full GEE asset path
 */
exports.catalogAsset = function(gasId, year) {
  var cfg = GAS_REGISTRY[gasId];
  if (!cfg) throw new Error('Unknown gas: ' + gasId);
  var tmpl = cfg.catalog_template.replace('{year}', year);
  return cfg.catalog_root + '/' + tmpl;
};

/**
 * Resolve P-02.0a baseline asset id for (gas, year).
 * @param {string} gasId
 * @param {string} year
 * @return {?string} asset path или null if не doesn't apply
 */
exports.baselineAsset = function(gasId, year) {
  var cfg = GAS_REGISTRY[gasId];
  if (!cfg || !cfg.p020a_baseline || !cfg.p020a_baseline.enabled) return null;
  var avail = cfg.p020a_baseline.available_years;
  if (avail.indexOf(year) < 0) return null;
  return cfg.p020a_baseline.asset_template.replace('{year}', year);
};

/** List ids of all active (catalog-loaded) gases. */
exports.activeGases = function() {
  var out = [];
  for (var k in GAS_REGISTRY) {
    if (GAS_REGISTRY.hasOwnProperty(k) && GAS_REGISTRY[k].active) out.push(k);
  }
  return out;
};

/** List all gases (active + stubs) — used для App «extension roadmap» panel. */
exports.allGases = function() {
  var out = [];
  for (var k in GAS_REGISTRY) {
    if (GAS_REGISTRY.hasOwnProperty(k)) out.push(k);
  }
  return out;
};

exports.get = function(gasId) {
  return GAS_REGISTRY[gasId];
};

exports.GAS_REGISTRY = GAS_REGISTRY;
