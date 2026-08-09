/**
 * @fileoverview Catalog table — floating on-map panel (bottom-center), toggle.
 *
 * P-02.0d-ux2: replaces the paginated Catalog tab. ALL events for the current
 * (gas, year) in one scrollable list (no pagination). Toggled on/off; rows jump
 * к the event + open the detail window.
 *
 * @module app/table_view
 */

/* eslint-disable no-undef */

var theme         = require('users/ntcomz18_sand/plumescan:app/theme');
var gas_registry  = require('users/ntcomz18_sand/plumescan:app/gas_registry');
var styling       = require('users/ntcomz18_sand/plumescan:app/styling');

var state = {
  cacheKey: null, events: [], callbacks: null,
  panel: null, listPanel: null, titleLabel: null, shown: false
};

/**
 * Build the floating catalog table (added к map by caller via .panel).
 * @param {!Object} callbacks getGas() getYear() viewEvent(props) getZenodoUrl()
 * @return {{panel: !ui.Panel, toggle: function(), refresh: function()}}
 */
exports.build = function(callbacks) {
  state.callbacks = callbacks;

  state.panel = ui.Panel({style: {
    position: 'bottom-center',
    width: '720px', maxHeight: '320px',
    backgroundColor: '#FFFFFFF2', border: '1px solid ' + theme.COLOR.accentBright,
    borderRadius: '10px', padding: '8px', margin: '0 0 10px 0', shown: false
  }});

  // Header row: title + close
  var header = ui.Panel({layout: ui.Panel.Layout.flow('horizontal'),
                         style: {margin: '0 0 4px 0', stretch: 'horizontal'}});
  state.titleLabel = ui.Label('Plume catalogue', theme.mergeStyle(theme.STYLE.cardH,
    {margin: '0', stretch: 'horizontal'}));
  header.add(state.titleLabel);
  header.add(ui.Button({label: '✕', onClick: function() { setShown(false); },
    style: {margin: '0', padding: '0 8px', fontSize: '12px', color: theme.COLOR.accent,
            backgroundColor: theme.COLOR.accentSoft, border: '1px solid ' + theme.COLOR.accentBright,
            borderRadius: '6px'}}));
  state.panel.add(header);

  // Column header (amber)
  var hStyle = {fontSize: '12px', fontWeight: 'bold', color: '#B45309', margin: '0'};
  var colRow = ui.Panel({layout: ui.Panel.Layout.flow('horizontal'),
    style: {backgroundColor: theme.COLOR.accentSoft, borderRadius: '6px',
            padding: '3px 2px', margin: '0 0 3px 0'}});
  colRow.add(ui.Label('Date', theme.mergeStyle(hStyle, {width: '110px'})));
  colRow.add(ui.Label('lon, lat', theme.mergeStyle(hStyle, {width: '160px'})));
  colRow.add(ui.Label('z', theme.mergeStyle(hStyle, {width: '56px'})));
  colRow.add(ui.Label('source', theme.mergeStyle(hStyle, {width: '210px'})));
  state.panel.add(colRow);

  // Scrollable list area
  state.listPanel = ui.Panel({style: {maxHeight: '210px', margin: '0'}});
  state.panel.add(state.listPanel);

  refresh();
  return {panel: state.panel, toggle: toggle, refresh: refresh};
};

function setShown(v) {
  state.shown = v;
  state.panel.style().set('shown', v);
  if (v) refresh();
}
function toggle() { setShown(!state.shown); }
exports.refresh = refresh;

function refresh() {
  if (!state.panel || !state.shown) return;
  var gasId = state.callbacks.getGas(), year = state.callbacks.getYear();
  var key = gasId + ':' + year;
  state.titleLabel.setValue('Plume catalogue — ' + gasId + ' / ' + year + ' (loading…)');

  if (key === state.cacheKey) { renderRows(gasId, year); return; }

  var fc = ee.FeatureCollection(gas_registry.catalogAsset(gasId, year));
  fc.toList(fc.size()).evaluate(function(list) {
    if (state.callbacks.getGas() !== gasId || state.callbacks.getYear() !== year) return;
    state.events = list || [];
    state.cacheKey = key;
    renderRows(gasId, year);
  });
}

function renderRows(gasId, year) {
  state.titleLabel.setValue('Plume catalogue — ' + gasId + ' / ' + year +
                            ' (' + state.events.length + ' events)');
  state.listPanel.clear();
  state.events.forEach(function(feat) {
    state.listPanel.add(buildRow(feat.properties || {}));
  });
}

function buildRow(p) {
  var row = ui.Panel({layout: ui.Panel.Layout.flow('horizontal'),
    style: {margin: '0 0 3px 0', padding: '3px 2px',
            backgroundColor: theme.COLOR.islandAlt, border: '1px solid ' + theme.COLOR.border,
            borderRadius: '6px'}});
  row.add(ui.Label((p.date_utc || (p.year ? String(p.year) : '?')).substring(0, 10),
    theme.mergeStyle(theme.STYLE.tableRow, {width: '110px'})));
  row.add(ui.Label(fmt(p.centroid_lon, 2) + ', ' + fmt(p.centroid_lat, 2),
    theme.mergeStyle(theme.STYLE.tableRow, {width: '160px'})));
  row.add(ui.Label(fmt(p.max_z, 1),
    theme.mergeStyle(theme.STYLE.tableRow, {width: '56px', color: zColor(p.max_z)})));
  row.add(ui.Label(styling.labelForSourceType(p.nearest_source_type),
    theme.mergeStyle(theme.STYLE.tableRow, {width: '210px',
      color: styling.colorForSourceType(p.nearest_source_type)})));
  row.add(ui.Button({label: 'View',
    onClick: (function(props) { return function() { state.callbacks.viewEvent(props); }; })(p),
    style: {margin: '0 0 0 4px', fontSize: '11px', padding: '1px 8px',
            color: theme.COLOR.accent, backgroundColor: theme.COLOR.accentSoft,
            border: '1px solid ' + theme.COLOR.accentBright, borderRadius: '6px'}}));
  return row;
}

function fmt(v, d) { return (typeof v === 'number') ? v.toFixed(d) : '?'; }
function zColor(z) {
  if (typeof z !== 'number') return '#6B6B6B';
  if (z >= 10) return '#C62828';
  if (z >= 5)  return '#B45309';
  return '#2E7D32';
}
