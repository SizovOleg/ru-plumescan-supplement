/**
 * @fileoverview Controls — Filters tab (compact, island design language).
 *
 * P-02.0d-ux2 iter2: Data island (gas+year, source) · Map layers island
 * (Detections / Reference / Context groups). Investigation removed; per-year
 * toggles removed (Year dropdown is the only year mechanism).
 *
 * @module app/controls
 */

/* eslint-disable no-undef */

var theme              = require('users/ntcomz18_sand/plumescan:app/theme');
var gas_registry       = require('users/ntcomz18_sand/plumescan:app/gas_registry');
var reference_registry = require('users/ntcomz18_sand/plumescan:app/reference_registry');
var styling            = require('users/ntcomz18_sand/plumescan:app/styling');
var year_chart         = require('users/ntcomz18_sand/plumescan:app/year_chart');

var HALF = {width: '180px', margin: '0 6px 0 0'};
var GROUP = {fontSize: '12px', fontWeight: 'bold', color: '#B45309', margin: '8px 2px 2px 2px'};

exports.build = function(state, layers, map, callbacks) {
  var panel = ui.Panel({style: {margin: '0'}});

  // ─── Island: Data ───────────────────────────────────────────────
  var dataCard = theme.card('Data');

  var gasItems = gas_registry.allGases().map(function(g) {
    var cfg = gas_registry.get(g);
    return {label: cfg.formula + ' ' + cfg.name + (cfg.active ? '' : ' (soon)'),
            value: g};
  });
  var gasSelect = ui.Select({
    items: gasItems, value: state.gas,
    onChange: function(v) {
      if (!gas_registry.get(v).active) {
        ui.alert(gas_registry.get(v).name + ' catalogue is not available yet.');
        gasSelect.setValue(state.gas, false); return;
      }
      callbacks.setGas(v);
    },
    style: {width: '176px', margin: '0 6px 0 0'}
  });
  var yearSelect = ui.Select({
    items: gas_registry.get(state.gas).years, value: state.year,
    onChange: function(v) { callbacks.setYear(v); },
    style: {width: '96px', margin: '0 6px 0 0'}
  });
  // Кнопка анимации по годам (▶ / ■) — таймером владеет main.js
  var playBtn = ui.Button({
    label: '▶',
    onClick: function() {
      var on = callbacks.toggleAnimation();
      playBtn.setLabel(on ? '■' : '▶');
      playBtn.style().set(on ? theme.STYLE.actionBtnOn : theme.STYLE.actionBtn);
    },
    style: theme.STYLE.actionBtn
  });
  callbacks.registerPlayButton(playBtn);

  dataCard.add(ui.Label('Gas / year', theme.STYLE.fieldLabel));
  var gyRow = ui.Panel({layout: ui.Panel.Layout.flow('horizontal'), style: {margin: '0 0 6px 0'}});
  gyRow.add(gasSelect);
  gyRow.add(yearSelect);
  gyRow.add(playBtn);
  dataCard.add(gyRow);
  callbacks.registerYearSelect(yearSelect);

  dataCard.add(ui.Label('Source type', theme.STYLE.fieldLabel));
  var srcItems = [{label: 'All source types', value: '(all)'}];
  for (var k in styling.SOURCE_TYPE_COLORS) {
    if (styling.SOURCE_TYPE_COLORS.hasOwnProperty(k) && k !== 'unknown') {
      srcItems.push({label: styling.labelForSourceType(k), value: k});
    }
  }
  dataCard.add(ui.Select({
    items: srcItems, value: state.srcType || '(all)',
    onChange: function(v) { callbacks.setSourceType(v === '(all)' ? null : v); },
    style: {width: '100%', margin: '0 0 4px 0'}
  }));

  // Годовой график: наведение — подсказка, клик по столбцу — выбор года
  dataCard.add(ui.Label('Detections per year (click a bar to select)',
                        theme.STYLE.fieldLabel));
  dataCard.add(year_chart.build(state.gas, function(y) { callbacks.setYear(y); }));
  panel.add(dataCard);

  // ─── Island: Map layers (consolidated) ──────────────────────────
  var layersCard = theme.card('Map layers');

  // Detections group — one on/off for the selected year (Year dropdown picks year)
  layersCard.add(ui.Label('Detections', GROUP));
  var gasCfg = gas_registry.get(state.gas);
  layersCard.add(ui.Checkbox({
    label: gasCfg.formula + ' events (selected year)',
    value: true,
    onChange: function(v) { callbacks.toggleDetections(v); },
    style: {margin: '2px 4px', fontSize: '13px'}
  }));

  // Reference group — Schuit + MARS horizontal
  layersCard.add(ui.Label('Reference catalogues', GROUP));
  var refRow = ui.Panel({layout: ui.Panel.Layout.flow('horizontal'), style: {margin: '0'}});
  reference_registry.forGas(state.gas).forEach(function(refId) {
    var ref = reference_registry.get(refId);
    refRow.add(ui.Checkbox({
      label: ref.name.replace('UNEP IMEO ', '') + ' (' + ref.n_aoi_events + ')',
      value: false,
      onChange: function(v) { callbacks.toggleReference(refId, 'points', v); },
      style: {margin: '0 10px 0 4px', fontSize: '12px'}
    }));
  });
  layersCard.add(refRow);

  // Context group — boundary
  layersCard.add(ui.Label('Context', GROUP));
  layersCard.add(ui.Checkbox({
    label: 'West Siberia boundary',
    value: true,
    onChange: function(v) { callbacks.toggleBoundary(v); },
    style: {margin: '2px 4px', fontSize: '13px'}
  }));

  panel.add(layersCard);

  return panel;
};
