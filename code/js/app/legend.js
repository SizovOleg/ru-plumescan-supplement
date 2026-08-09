/**
 * @fileoverview On-map legend overlay — source-type colours + size scale.
 *
 * Added к the map via leftMap.add() with bottom-right position (P-02.0d-ux2).
 * Moves the legend off the side panel (reclaims ~410px vertical). Collapsible.
 *
 * @module app/legend
 */

/* eslint-disable no-undef */

var theme   = require('users/ntcomz18_sand/plumescan:app/theme');
var styling = require('users/ntcomz18_sand/plumescan:app/styling');

// Source types in legend order (matches styling palette; excludes 'unknown')
var ORDER = ['gas_field', 'oil_field', 'viirs_flare_high', 'viirs_flare_low',
             'tpp_gres', 'tpp_chp', 'metallurgy', 'coal_mine', 'urban', 'other'];

/**
 * Build + add the on-map legend overlay.
 * @param {!ui.Map} map
 * @return {!ui.Panel} the legend panel (already added к map)
 */
exports.add = function(map) {
  var panel = ui.Panel({style: theme.STYLE.legendPanel});

  // Header row with collapse toggle
  var bodyPanel = ui.Panel({style: {margin: '0', padding: '0'}});
  var collapsed = {v: false};
  var toggleBtn = ui.Button({
    label: '–',
    onClick: function() {
      collapsed.v = !collapsed.v;
      bodyPanel.style().set('shown', !collapsed.v);
      toggleBtn.setLabel(collapsed.v ? '+' : '–');
    },
    style: {margin: '0', padding: '0 6px', fontSize: '12px',
            color: theme.COLOR.accent, backgroundColor: '#FFFFFF00',
            border: '0px solid'}
  });
  var headerRow = ui.Panel({
    layout: ui.Panel.Layout.flow('horizontal'),
    style: {margin: '0 0 4px 0', stretch: 'horizontal'}
  });
  headerRow.add(ui.Label('Legend', theme.mergeStyle(theme.STYLE.cardH, {margin: '0', stretch: 'horizontal'})));
  headerRow.add(toggleBtn);
  panel.add(headerRow);

  // Colour rows (compact)
  ORDER.forEach(function(k) {
    var row = ui.Panel({layout: ui.Panel.Layout.flow('horizontal'), style: {margin: '0'}});
    row.add(ui.Label('●', {color: styling.SOURCE_TYPE_COLORS[k], fontSize: '13px',
                           margin: '0 4px 0 0', padding: '0'}));
    row.add(ui.Label(styling.labelForSourceType(k),
                     theme.mergeStyle(theme.STYLE.tableRow, {margin: '1px 0', padding: '0'})));
    bodyPanel.add(row);
  });

  bodyPanel.add(theme.divider());
  bodyPanel.add(ui.Label('Marker size = signal strength',
                         theme.mergeStyle(theme.STYLE.caption, {margin: '2px 0', fontWeight: 'bold'})));
  bodyPanel.add(ui.Label('small ● 3   ● 5   ● 10   ⬤ 15+ (z-score)',
                         theme.mergeStyle(theme.STYLE.tableRow, {margin: '1px 0'})));
  bodyPanel.add(ui.Label('z-score = how far a methane reading rises above the local background.',
                         theme.mergeStyle(theme.STYLE.caption, {margin: '2px 0'})));

  panel.add(bodyPanel);
  map.add(panel);
  return panel;
};
