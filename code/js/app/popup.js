/**
 * @fileoverview Popup — event detail panel с Stage 3 flag semantic rendering.
 *
 * CRITICAL semantic (per state_refresh_20260523_addendum.md):
 *   inside_X_validation_zone (HULL FLAG) = spatial containment, geographic
 *                                          plausibility, NOT validation
 *   matched_X_150km          (MATCH FLAG) = year-aware temporal validation
 *
 * App popup MUST show BOTH flags DISTINCTLY с different labels. Collapsing
 * к single «validated» boolean loses information AND misrepresents semantics.
 *
 * Theme tokens via theme.js — larger fonts (13-14px body, 15px card headers).
 *
 * @module app/popup
 */

/* eslint-disable no-undef */

var theme              = require('users/ntcomz18_sand/plumescan:app/theme');
var reference_registry = require('users/ntcomz18_sand/plumescan:app/reference_registry');
var gas_registry       = require('users/ntcomz18_sand/plumescan:app/gas_registry');
var styling            = require('users/ntcomz18_sand/plumescan:app/styling');

function fmt(v, digits) {
  return (typeof v === 'number') ? v.toFixed(digits) : '?';
}

/**
 * Match-only flag block (P-02.0d 2026-06-20 — hull / inside_zone retired with
 * AOI re-scope к zapsib). Validation = matched_X (year-aware ≤150 km) only.
 *
 * @param {!ui.Panel} card
 * @param {!Object} props
 * @param {string} refId
 */
function flagBlockForReference(card, props, refId) {
  var ref = reference_registry.get(refId);
  if (!ref) return;

  var matchVal = props[ref.matched_X_field];
  var radius = ref.match_radius_km || 150;

  card.add(ui.Label(ref.name + ' (' + ref.temporal_coverage + ')', theme.STYLE.cardH));

  var matchColor = (matchVal === 1) ? theme.COLOR.success : theme.COLOR.textMuted;
  var verdict = (matchVal === 1)
    ? '✓ Matched — a ' + ref.name + ' detection from the same year lies within ' + radius + ' km'
    : '✗ Not matched — no ' + ref.name + ' detection from the same year within ' + radius + ' km';
  card.add(ui.Label(verdict, theme.mergeStyle(theme.STYLE.body,
    {color: matchColor, fontWeight: 'bold'})));
  card.add(theme.divider());
}

/**
 * Populate a popup panel с full event details + Stage 3 flag block.
 *
 * @param {!ui.Panel} panel — cleared + populated
 * @param {!Object} props
 * @param {string} gasId
 */
exports.render = function(panel, props, gasId) {
  panel.clear();
  var gasCfg = gas_registry.get(gasId);
  var deltaUnits = (gasCfg && gasCfg.delta_units) ? gasCfg.delta_units : '';

  // Header card
  var headerCard = theme.card('Event details');
  headerCard.add(ui.Label('Date (UTC)', theme.STYLE.fieldLabel));
  headerCard.add(ui.Label((props.date_utc || (props.year ? String(props.year) : '?')) +
                          ' ' + (props.time_utc || ''), theme.STYLE.fieldValue));
  headerCard.add(ui.Label('Location (lon, lat)', theme.STYLE.fieldLabel));
  headerCard.add(ui.Label(
    fmt(props.centroid_lon, 3) + ', ' + fmt(props.centroid_lat, 3),
    theme.STYLE.fieldValue));
  // Сила сигнала — крупной цифрой (главный количественный показатель события)
  headerCard.add(ui.Label('Signal strength (z-score)', theme.STYLE.fieldLabel));
  var zRow = ui.Panel({layout: ui.Panel.Layout.flow('horizontal'),
                       style: {margin: '0 0 4px 0'}});
  zRow.add(ui.Label(fmt(props.max_z, 1), theme.STYLE.statBig));
  zRow.add(ui.Label(
    (typeof props.max_delta === 'number'
      ? '+' + fmt(props.max_delta, 0) + (deltaUnits ? ' ' + deltaUnits : '') + '   ·   '
      : '') +
    fmt(props.area_km2, 0) + ' km²',
    theme.mergeStyle(theme.STYLE.bodyMuted, {margin: '8px 0 0 8px'})));
  headerCard.add(zRow);
  headerCard.add(ui.Label('Likely source', theme.STYLE.fieldLabel));
  headerCard.add(ui.Label(
    styling.labelForSourceType(props.nearest_source_type) +
    (props.nearest_source_distance_km
      ? ' (' + fmt(props.nearest_source_distance_km, 0) + ' km away)' : ''),
    theme.STYLE.fieldValue));

  if (typeof props.corr_albedo === 'number') {
    var albedoNote = (props.corr_albedo > 0.5)
      ? 'bright surface — possible snow influence'
      : (props.corr_albedo < -0.3)
        ? 'dark / wet surface — interpret with care'
        : 'clean signal';
    headerCard.add(ui.Label('Surface check', theme.STYLE.fieldLabel));
    headerCard.add(ui.Label(albedoNote, theme.STYLE.fieldValue));
  }
  panel.add(headerCard);

  // Validation card (match against reference catalogs)
  var validationCard = theme.card('Cross-check against reference catalogs');
  validationCard.add(ui.Label(
    'Does an independent satellite reference catalogue report a detection from the ' +
    'same year within 150 km? Reference catalogues focus on gas-field super-emitters, ' +
    'so many flare detections here have no reference match.',
    theme.STYLE.caption
  ));
  validationCard.add(theme.divider());
  reference_registry.forGas(gasId).forEach(function(refId) {
    flagBlockForReference(validationCard, props, refId);
  });
  panel.add(validationCard);
};

/** Empty-state stub when no event clicked yet. */
exports.renderEmpty = function(panel) {
  panel.clear();
  var card = theme.card('Event details');
  card.add(ui.Label(
    'Click any marker on the map to see event details here, ' +
    'or use the View button in the Catalog tab.',
    theme.STYLE.body
  ));
  panel.add(card);
};
