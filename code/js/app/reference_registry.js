/**
 * @fileoverview Reference Registry — external reference catalog metadata.
 *
 * Registry of validation reference catalogs (Schuit 2023, IMEO MARS).
 * Each entry carries asset paths (FC + hull), license, citation, color,
 * temporal coverage, и applicable gas. Layer factory + attribution panel
 * + popup match-flag interpretation все dispatch from here.
 *
 * Adding a new reference (Lauvaux 2022, future catalogs) = adding entry.
 *
 * @module app/reference_registry
 */

/* eslint-disable no-undef */

var PROJECT_ID = 'nodal-thunder-481307-u1';
var REFS_ROOT = 'projects/' + PROJECT_ID + '/assets/RuPlumeScan/refs';

/**
 * Reference catalog metadata schema.
 *
 * Required:
 *   name              — display label
 *   fc_asset          — point FC GEE asset (reference detections)
 *   color             — hex color для UI rendering (points)
 *   license           — string («CC BY 4.0», etc.)
 *   license_url
 *   citation_short    — display in attribution panel
 *   citation_full     — full citation
 *   gas               — gas id this reference applies к
 *   temporal_coverage — string, e.g. '2021' or '2022-2026'
 *   n_aoi_events      — count inside zapsib AOI (P-02.0d)
 *   matched_X_field   — property name for year-aware match flag
 *   match_radius_km   — DNA §1.4 empirical match radius
 *   schema_note       — popup hint
 *
 * P-02.0d (2026-06-20): hull_asset + inside_X_hull_field retired (AOI re-scope
 * к zapsib; validation = matched_X only).
 *
 * @type {!Object<string, !Object>}
 */
var REFERENCE_REGISTRY = {

  // Note (P-02.0d 2026-06-20): hull assets + inside_X_validation_zone flags
  // removed. AOI re-scoped to zapsib (physico-geographic boundary); validation
  // rests on matched_X (year-aware 150 km) only. n_aoi_events = inside-zapsib.
  schuit2023: {
    name: 'Schuit 2023',
    fc_asset: REFS_ROOT + '/schuit2023_v1',
    color: '#1a73e8',  // blue
    license: 'CC BY 4.0',
    license_url: 'https://creativecommons.org/licenses/by/4.0/',
    citation_short: 'Schuit et al. (2023)',
    citation_full: 'Schuit, B. J., et al. (2023). Automated detection and monitoring of methane super-emitters using satellite data. Atmospheric Chemistry and Physics, 23, 9071-9098. DOI: 10.5194/acp-23-9071-2023',
    gas: 'CH4',
    temporal_coverage: '2021',
    n_aoi_events: 32,  // inside zapsib (was 123 bbox)
    matched_X_field: 'matched_schuit_150km',
    match_radius_km: 150,  // DNA v2.4 §1.4 empirical cross-catalog match radius
    schema_note: 'Single-year (2021) snapshot catalog. matched_X covers same-year events only.'
  },

  imeo_mars: {
    name: 'UNEP IMEO MARS',
    fc_asset: REFS_ROOT + '/imeo_mars_v1',
    color: '#e91e63',  // pink/magenta
    license: 'CC BY-NC-SA 4.0',
    license_url: 'https://creativecommons.org/licenses/by-nc-sa/4.0/',
    citation_short: 'UNEP IMEO MARS',
    citation_full: 'United Nations Environment Programme — International Methane Emissions Observatory (IMEO), Methane Alert and Response System (MARS). methanedata.unep.org. Catalog retrieved 2026-05-15.',
    gas: 'CH4',
    temporal_coverage: '2022-2026',
    n_aoi_events: 163,  // inside zapsib (was 446 bbox)
    matched_X_field: 'matched_mars_150km',
    match_radius_km: 150,  // DNA v2.4 §1.4
    schema_note: 'Multi-year mission catalog. matched_mars covers same-year events from 2023 onward inside zapsib; 2022 has 0 events inside boundary (Tier 2 degenerate).'
  }
};

exports.REFERENCE_REGISTRY = REFERENCE_REGISTRY;
exports.get = function(refId) { return REFERENCE_REGISTRY[refId]; };
exports.list = function() {
  var out = [];
  for (var k in REFERENCE_REGISTRY) {
    if (REFERENCE_REGISTRY.hasOwnProperty(k)) out.push(k);
  }
  return out;
};

/** References applicable к a given gas. */
exports.forGas = function(gasId) {
  var out = [];
  for (var k in REFERENCE_REGISTRY) {
    if (REFERENCE_REGISTRY.hasOwnProperty(k) && REFERENCE_REGISTRY[k].gas === gasId) {
      out.push(k);
    }
  }
  return out;
};
