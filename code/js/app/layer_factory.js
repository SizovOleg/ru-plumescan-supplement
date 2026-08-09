/**
 * @fileoverview Layer Factory — gas-agnostic catalog + reference layer builder.
 *
 * Adding a new gas = config in gas_registry. Adding a reference catalog =
 * config in reference_registry. Layer factory consumes both registries
 * to build map layers без gas-specific branching.
 *
 * Output:
 *   buildCatalogLayers(gasId, ui.Map) — adds 7 year-layers + 1 «all years» merged
 *   buildBaselineLayer(gasId, year, ui.Map) — adds P-02.0a baseline overlay (ISSUE 1)
 *   buildReferenceLayer(refId, ui.Map) — adds hull polygon + point FC for a reference
 *
 * All layers tracked in a registry (returned dict) so controls module can
 * toggle visibility без direct ui.Map mutation outside this module.
 *
 * @module app/layer_factory
 */

/* eslint-disable no-undef */

var gas_registry = require('users/ntcomz18_sand/plumescan:app/gas_registry');
var reference_registry = require('users/ntcomz18_sand/plumescan:app/reference_registry');
var styling = require('users/ntcomz18_sand/plumescan:app/styling');

// AOI boundary — West Siberian Plain (zapsib physico-geographic boundary, P-02.0d)
var ZAPSIB_ASSET = 'projects/nodal-thunder-481307-u1/assets/zapsib';
var ZAPSIB = ee.FeatureCollection(ZAPSIB_ASSET);
var ZAPSIB_GEOM = ZAPSIB.geometry();  // for filterBounds clipping (containment)
// Pre-dissolved single-feature outline asset (computed once via union, не per load)
var ZAPSIB_OUTLINE = ee.FeatureCollection(
    'projects/nodal-thunder-481307-u1/assets/RuPlumeScan/zapsib_boundary');

exports.zapsibGeom = function() { return ZAPSIB_GEOM; };

/**
 * Build the AOI boundary outline layer (pre-dissolved static asset, light line,
 * no fill — does not occlude events; no per-load union compute).
 * @param {!ui.Map} map
 * @return {!ui.Map.Layer}
 */
exports.buildBoundaryLayer = function(map) {
  var outline = ee.Image().byte().paint({
    featureCollection: ZAPSIB_OUTLINE, color: 1, width: 2
  }).visualize({palette: ['#fff59d']});  // light yellow — visible on satellite
  var layer = ui.Map.Layer(outline, {}, 'West Siberia Plain boundary', true);
  map.layers().add(layer);
  return layer;
};

/**
 * Build per-year catalog layers for the given gas. Each year becomes
 * a separate `ui.Map.Layer` toggleable independently.
 *
 * @param {string} gasId
 * @param {!ui.Map} map
 * @return {!Object<string, !ui.Map.Layer>} layer registry: year → Layer
 */
exports.buildCatalogLayers = function(gasId, map) {
  var cfg = gas_registry.get(gasId);
  if (!cfg) throw new Error('Unknown gas: ' + gasId);
  if (!cfg.active) {
    print('layer_factory: skipping gas ' + gasId + ' (active=false)');
    return {};
  }

  var registry = {};
  cfg.years.forEach(function(year) {
    var assetId = gas_registry.catalogAsset(gasId, year);
    var fc = ee.FeatureCollection(assetId);
    var styled = styling.styleFc(fc);

    var layer = ui.Map.Layer(
      styled.style({styleProperty: 'style', neighborhood: 16}),
      {},
      gasId + ' events ' + year,
      true  // visible by default
    );
    map.layers().add(layer);
    registry[year] = layer;
  });

  return registry;
};

// buildBaselineLayer removed (P-02.0d-ux2) — Investigation/method-comparison view
// retired from the App. P-02.0a baseline asset retained in project for paper
// figure F6, but no longer rendered in the App.

/**
 * Build reference catalog overlay: event points (colored by reference identity).
 * Hull layers removed (P-02.0d 2026-06-20 — AOI re-scoped к zapsib; hulls + inside_zone
 * validation flags retired, validation rests on matched_X only).
 *
 * @param {string} refId
 * @param {!ui.Map} map
 * @return {{points: !ui.Map.Layer}}
 */
exports.buildReferenceLayer = function(refId, map) {
  var ref = reference_registry.get(refId);
  if (!ref) throw new Error('Unknown reference: ' + refId);

  var refColor = ref.color.replace('#', '');
  // Clip reference points к AOI (P-02.0d) — show only inside-boundary detections
  // (Schuit 32, MARS 163), не the full off-plain catalog.
  var pointsFc = ee.FeatureCollection(ref.fc_asset).filterBounds(ZAPSIB_GEOM);
  var pointsLayer = ui.Map.Layer(
    pointsFc.style({
      color: refColor,
      fillColor: refColor + 'CC',
      pointSize: 5,
      pointShape: 'diamond',
      width: 1
    }),
    {},
    ref.name + ' events',
    false
  );
  map.layers().add(pointsLayer);

  return {points: pointsLayer};
};

/** Convenience: build all references for given gas. */
exports.buildAllReferencesForGas = function(gasId, map) {
  var registry = {};
  var refIds = reference_registry.forGas(gasId);
  refIds.forEach(function(refId) {
    registry[refId] = exports.buildReferenceLayer(refId, map);
  });
  return registry;
};
