/**
 * @fileoverview Styling — source_type color + magnitude (z) sizing.
 *
 * P-05 spec: «source_type color + max_z size styling». Gas-agnostic —
 * source_type palette is shared (semantic), magnitude colormap pulled per-gas
 * from gas_registry. Marker size scales monotonically с magnitude.
 *
 * @module app/styling
 */

/* eslint-disable no-undef */

var gas_registry = require('users/ntcomz18_sand/plumescan:app/gas_registry');

/**
 * Source-type color palette (semantic, gas-agnostic).
 * Anchored к major industrial categories used across Path E catalogs.
 * @type {!Object<string, string>}
 */
var SOURCE_TYPE_COLORS = {
  'gas_field':         '#c62828',  // red — gas extraction
  'oil_field':         '#8b4513',  // saddlebrown — oil
  'viirs_flare_high':  '#ff9800',  // orange — bright flares (likely vent/flare)
  'viirs_flare_low':   '#ffb74d',  // light orange — faint flares
  'tpp_gres':          '#7b1fa2',  // purple — thermal power, GRES
  'tpp_chp':           '#9c27b0',  // light purple — combined heat & power
  'metallurgy':        '#37474f',  // dark slate
  'coal_mine':         '#212121',  // black — coal
  'urban':             '#1976d2',  // blue — urban / landfill / utility
  'other':             '#757575',  // gray — unattributed
  'unknown':           '#bdbdbd'   // light gray — null/missing source_type
};

exports.SOURCE_TYPE_COLORS = SOURCE_TYPE_COLORS;

/**
 * Human-readable source-type labels (plain language for UI; no raw enum values).
 * @type {!Object<string, string>}
 */
var SOURCE_TYPE_LABELS = {
  gas_field: 'Gas field', oil_field: 'Oil field',
  viirs_flare_high: 'Gas flare (bright)', viirs_flare_low: 'Gas flare (faint)',
  tpp_gres: 'Power plant (GRES)', tpp_chp: 'Power / heating plant',
  metallurgy: 'Metallurgy', coal_mine: 'Coal mine',
  urban: 'Urban / landfill', other: 'Other', unknown: 'Unattributed'
};
exports.SOURCE_TYPE_LABELS = SOURCE_TYPE_LABELS;

/** Plain-language label for a source_type enum value. */
exports.labelForSourceType = function(srcType) {
  if (!srcType || !SOURCE_TYPE_LABELS[srcType]) return SOURCE_TYPE_LABELS['unknown'];
  return SOURCE_TYPE_LABELS[srcType];
};

/**
 * Resolve source_type → hex color, fallback к 'unknown'.
 * @param {?string} srcType
 * @return {string}
 */
exports.colorForSourceType = function(srcType) {
  if (!srcType || !SOURCE_TYPE_COLORS[srcType]) return SOURCE_TYPE_COLORS['unknown'];
  return SOURCE_TYPE_COLORS[srcType];
};

/**
 * Marker radius (pixels) scaled by magnitude (z-score) — monotonic.
 *   z <  3 → 3 px
 *   z =  5 → 6 px
 *   z = 10 → 10 px
 *   z ≥ 15 → 14 px
 * @param {number} z
 * @return {number} radius px
 */
exports.markerSizeForZ = function(z) {
  if (!z || z < 3) return 3;
  if (z < 5) return 4 + (z - 3);    // 4..6
  if (z < 10) return 6 + (z - 5);   // 6..11
  if (z < 15) return 11 + (z - 10) * 0.6;  // 11..14
  return 14;
};

/**
 * Build server-side style property for a FC.map() → coloured + sized markers.
 * Adds a `style` property to each feature; consumer applies via .style({styleProperty: 'style'}).
 *
 * @param {!ee.FeatureCollection} fc
 * @return {!ee.FeatureCollection}
 */
exports.styleFc = function(fc) {
  return fc.map(function(f) {
    // Defensive null-handling — nearest_source_type may be missing
    var rawType = f.get('nearest_source_type');
    var srcType = ee.String(ee.Algorithms.If(rawType, rawType, 'unknown'));

    var z = ee.Number(ee.Algorithms.If(f.get('max_z'), f.get('max_z'), 0)).max(0);

    // Map source_type к color (server-side dictionary)
    var colorDict = ee.Dictionary({
      gas_field: 'c62828', oil_field: '8b4513', viirs_flare_high: 'ff9800',
      viirs_flare_low: 'ffb74d', tpp_gres: '7b1fa2', tpp_chp: '9c27b0',
      metallurgy: '37474f', coal_mine: '212121', urban: '1976d2',
      other: '757575', unknown: 'bdbdbd'
    });
    var color = ee.String(colorDict.get(srcType, 'bdbdbd'));

    // Marker size piecewise linear (mirror markerSizeForZ client-side).
    // ee.Number has no .expression() — use ee.Algorithms.If chain.
    var zClamped = z.min(15);
    var size = ee.Number(ee.Algorithms.If(zClamped.lt(3), 3,
               ee.Algorithms.If(zClamped.lt(5),  zClamped.subtract(3).add(4),
               ee.Algorithms.If(zClamped.lt(10), zClamped.subtract(5).add(6),
               ee.Algorithms.If(zClamped.lt(15), zClamped.subtract(10).multiply(0.6).add(11),
                                14)))));

    return f.set('style', {
      color: color,
      fillColor: color.cat('CC'),  // ~80% alpha
      pointSize: size,
      pointShape: 'circle',
      width: 1
    });
  });
};

/**
 * Colormap for max_z heatmap rendering — pulled from gas registry.
 * Used by polygon-style layers if catalog has polygon geometry.
 * @param {string} gasId
 * @return {{min: number, max: number, palette: !Array<string>}}
 */
exports.zVisParams = function(gasId) {
  var cfg = gas_registry.get(gasId);
  var breaks = cfg.colormap_z_breaks;
  return {
    min: breaks[0],
    max: breaks[breaks.length - 1],
    palette: cfg.colormap_z
  };
};
