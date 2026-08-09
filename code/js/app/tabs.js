/**
 * @fileoverview Tab navigation widget — emulates tabs in ui.* sandbox.
 *
 * GEE Code Editor не имеет native tabs widget. Эмулируем через row of buttons
 * сверху + container panel снизу, который показывает active panel и скрывает
 * остальные через .style({shown: false}).
 *
 * Usage:
 *   var tabs = require('users/ntcomz18_sand/plumescan:app/tabs');
 *   var widget = tabs.build([
 *     {id: 'filters', label: 'Filters', panel: filtersPanel},
 *     {id: 'catalog', label: 'Catalog', panel: catalogPanel},
 *     {id: 'about',   label: 'About',   panel: aboutPanel}
 *   ], 'filters');  // initial tab
 *   rightPanel.add(widget);
 *
 * @module app/tabs
 */

/* eslint-disable no-undef */

var theme = require('users/ntcomz18_sand/plumescan:app/theme');

/**
 * Build a segmented tabbed widget. Returns tabBar (для fixed header zone) and
 * content (для scrollable body) SEPARATELY so the bar can stay fixed while the
 * body scrolls.
 *
 * @param {!Array<{id: string, label: string, panel: !ui.Panel}>} tabsDef
 * @param {string} initialActiveId
 * @return {{tabBar: !ui.Panel, content: !ui.Panel, activate: function(string)}}
 */
exports.build = function(tabsDef, initialActiveId) {
  // Segmented bar (horizontal pills)
  var tabBar = ui.Panel({
    layout: ui.Panel.Layout.flow('horizontal'),
    style: {margin: '6px 0 0 0'}
  });

  // Content container — holds all panels; only active one visible
  var content = ui.Panel({style: {margin: '0'}});

  var buttons = {};
  var panels = {};

  function activate(targetId) {
    tabsDef.forEach(function(t) {
      var isActive = (t.id === targetId);
      buttons[t.id].style().set(isActive ? theme.STYLE.tabActive : theme.STYLE.tabInactive);
      panels[t.id].style().set('shown', isActive);
    });
  }

  tabsDef.forEach(function(t) {
    var btn = ui.Button({
      label: t.label,
      onClick: (function(id) { return function() { activate(id); }; })(t.id),
      style: theme.STYLE.tabInactive
    });
    tabBar.add(btn);
    buttons[t.id] = btn;
    panels[t.id] = t.panel;
    content.add(t.panel);
  });

  activate(initialActiveId || tabsDef[0].id);

  return {tabBar: tabBar, content: content, activate: activate};
};
