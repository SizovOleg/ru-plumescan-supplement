/**
 * @fileoverview RuPlumeScan App — entry orchestrator.
 *
 * Gas-agnostic presentational App для CH₄ plume catalog (Phase 5).
 * Актуальная компоновка (P-02.0d-ux3):
 *   - Шапка (фиксированная): заголовок, подзаголовок, стат-строка каталога,
 *     сегментные вкладки «Фильтры | О проекте» + кнопка-действие «Каталог»,
 *     строка состояния.
 *   - Фильтры: острова «Данные» (газ/год, ▶ анимация, тип источника, годовой
 *     график с подсказками и кликом) и «Слои карты».
 *   - Каталог — плавающая таблица над картой (без пагинации).
 *   - Карточка события — плавающее окно над картой; легенда — угол карты.
 *
 * Constraints (DNA + P-05 spec):
 *   - Catalog asset READ-ONLY в App
 *   - Reference attribution mandatory
 *   - Presentational scope v1 (no live re-detection; Q5 EECU control)
 *   - Validation = matched_X (year-aware ≤150 km); hull/inside_zone retired (P-02.0d)
 *   - AOI = zapsib physico-geographic boundary (West Siberian Plain)
 *
 * @module app/main
 */

/* eslint-disable no-undef */

// ===========================================================================
// Module imports
// ===========================================================================

var theme                = require('users/ntcomz18_sand/plumescan:app/theme');
var tabs                 = require('users/ntcomz18_sand/plumescan:app/tabs');
var gas_registry         = require('users/ntcomz18_sand/plumescan:app/gas_registry');
var reference_registry   = require('users/ntcomz18_sand/plumescan:app/reference_registry');
var styling              = require('users/ntcomz18_sand/plumescan:app/styling');
var layer_factory        = require('users/ntcomz18_sand/plumescan:app/layer_factory');
var popup                = require('users/ntcomz18_sand/plumescan:app/popup');
var controls             = require('users/ntcomz18_sand/plumescan:app/controls');
var table_view           = require('users/ntcomz18_sand/plumescan:app/table_view');
var about_panel          = require('users/ntcomz18_sand/plumescan:app/about_panel');
var legend               = require('users/ntcomz18_sand/plumescan:app/legend');
var year_chart           = require('users/ntcomz18_sand/plumescan:app/year_chart');

// Click handler config — max distance cap для nearest-event lookup
var CLICK_MAX_DIST_KM = 50;

// ===========================================================================
// App state
// ===========================================================================

var state = {
  gas: 'CH4',
  year: '2024',
  srcType: null,
  selectedEvent: null,
  catalogLayers: {},
  referenceLayers: {},
  detectionsOn: true,
  animationKey: null   // ключ ui.util.setInterval, когда анимация активна
};

// Виджеты, которыми управляет не только их владелец (синхронизация состояния)
var yearSelectRef = null;
var playBtnRef = null;
var ANIMATION_MS = 1500;

// ===========================================================================
// Map
// ===========================================================================

var leftMap = ui.Map();
leftMap.setOptions('SATELLITE');
leftMap.style().set({cursor: 'crosshair'});
leftMap.setCenter(77.5, 62.5, 4);
// Hide native GEE Layers panel — all layer control lives in the side panel
leftMap.setControlVisibility({layerList: false});

// AOI boundary outline (West Siberian Plain) — added first so it sits under events
state.boundaryLayer = layer_factory.buildBoundaryLayer(leftMap);
state.catalogLayers = layer_factory.buildCatalogLayers(state.gas, leftMap);
state.referenceLayers = layer_factory.buildAllReferencesForGas(state.gas, leftMap);

// On-map legend overlay (bottom-right) — off the side panel
legend.add(leftMap);

// ===========================================================================
// Status indicator (loading/ready)
// ===========================================================================

var statusLabel = ui.Label('Ready', theme.STYLE.statusReady);

function setStatus(msg, kind) {
  statusLabel.setValue(msg);
  statusLabel.style().set(
    kind === 'loading' ? theme.STYLE.statusLoading :
    kind === 'error'   ? theme.STYLE.statusError :
                          theme.STYLE.statusReady
  );
}

// ===========================================================================
// Tab content panels
// ===========================================================================

// Filters tab — controls (Data + Map layers islands)
var filtersTab = ui.Panel({style: {margin: '0'}});

var controlsPanel = controls.build(state, state.catalogLayers, leftMap, getCallbacks());
filtersTab.add(controlsPanel);


// Event detail — floating on-map window (top-right), shown on event click
var detailContent = ui.Panel({style: {margin: '0'}});
var detailWindow = ui.Panel({style: {
  position: 'top-left',
  backgroundColor: '#FFFFFFF2', border: '1px solid ' + theme.COLOR.accentBright,
  borderRadius: '10px', padding: '8px', margin: '8px 0 0 8px',
  width: '300px', maxHeight: '540px', shown: false
}});
// Small ✕ in the top-right corner of the window (right-aligned header row)
var detailHeader = ui.Panel({layout: ui.Panel.Layout.flow('horizontal'),
  style: {stretch: 'horizontal', margin: '0 0 2px 0'}});
detailHeader.add(ui.Label('', {stretch: 'horizontal', margin: '0'}));
detailHeader.add(ui.Button({label: '✕',
  onClick: function() { detailWindow.style().set('shown', false); },
  style: {margin: '0', padding: '0 6px', fontSize: '12px',
          color: theme.COLOR.accent, backgroundColor: theme.COLOR.accentSoft,
          border: '1px solid ' + theme.COLOR.accentBright, borderRadius: '6px'}}));
detailWindow.add(detailHeader);
detailWindow.add(detailContent);
leftMap.add(detailWindow);

function showEventDetail(props) {
  popup.render(detailContent, props, state.gas);
  detailWindow.style().set('shown', true);
}

// Catalog — floating on-map table (bottom-center), toggled on/off
var catalogTable = table_view.build({
  getGas:    function() { return state.gas; },
  getYear:   function() { return state.year; },
  viewEvent: function(props) { viewEventOnMap(props); }
});
leftMap.add(catalogTable.panel);

// About tab — help + methodology + figures + attribution
var aboutTab = about_panel.build();

// ===========================================================================
// Tab navigation (Filters | About; Catalogue is a floating table toggle)
// ===========================================================================

var tabsWidget = tabs.build([
  {id: 'filters', label: 'Filters', panel: filtersTab},
  {id: 'about',   label: 'About',   panel: aboutTab}
], 'filters');

// Кнопка-ДЕЙСТВИЕ «Каталог» — открывает плавающую таблицу над картой.
// Толстая амбер-рамка отличает её от вкладок (это не вкладка, а переключатель).
var catalogOn = {v: false};
var catalogBtn = ui.Button({
  label: '📋 Catalogue',
  onClick: function() {
    catalogTable.toggle();
    catalogOn.v = !catalogOn.v;
    catalogBtn.style().set(catalogOn.v ? theme.STYLE.actionBtnOn
                                       : theme.STYLE.actionBtn);
  },
  style: theme.STYLE.actionBtn
});
tabsWidget.tabBar.add(catalogBtn);

// ===========================================================================
// Map click handler — clickSeq race defense + max distance cap
// ===========================================================================

var clickSeq = 0;
leftMap.onClick(function(coords) {
  var cfg = gas_registry.get(state.gas);
  if (!cfg.active) return;

  var seq = ++clickSeq;
  var gasAtClick = state.gas;
  var yearAtClick = state.year;
  var srcTypeAtClick = state.srcType;

  setStatus('Loading event…', 'loading');

  var assetId = gas_registry.catalogAsset(state.gas, state.year);
  var fc = ee.FeatureCollection(assetId);
  if (state.srcType) {
    fc = fc.filter(ee.Filter.eq('nearest_source_type', state.srcType));
  }
  var pt = ee.Geometry.Point([coords.lon, coords.lat]);
  var nearest = fc.map(function(f) {
    return f.set('dist_km', f.geometry().centroid().distance(pt, 1000).divide(1000));
  }).sort('dist_km').first();

  nearest.evaluate(function(feat) {
    if (seq !== clickSeq) return;
    if (gasAtClick !== state.gas || yearAtClick !== state.year ||
        srcTypeAtClick !== state.srcType) return;

    if (!feat || !feat.properties) {
      detailWindow.style().set('shown', false);
      setStatus('No event nearby — click closer to a marker', 'error');
      return;
    }
    var dist = feat.properties.dist_km;
    if (typeof dist === 'number' && dist > CLICK_MAX_DIST_KM) {
      detailWindow.style().set('shown', false);
      setStatus('Nearest event ' + dist.toFixed(0) + ' km away (> ' +
                CLICK_MAX_DIST_KM + ' km)', 'error');
      return;
    }
    state.selectedEvent = feat.properties;
    showEventDetail(feat.properties);  // floating window opens on the map
    setStatus('Event loaded', 'ready');
  });
});

// ===========================================================================
// Right-panel layout — fixed header zone + scrollable body
// ===========================================================================

// Шапка (фиксированная): заголовок, подзаголовок, стат-строка, вкладки, статус
var headerZone = ui.Panel({style: theme.STYLE.headerZone});
headerZone.add(ui.Label('RuPlumeScan', theme.STYLE.appTitle));
headerZone.add(ui.Label('Satellite methane super-emitter catalogue · ' +
                        'West Siberian Plain · TROPOMI L3',
                        theme.STYLE.appSubtitle));
headerZone.add(ui.Label(year_chart.statLine(state.gas), theme.STYLE.statStrip));
headerZone.add(tabsWidget.tabBar);
headerZone.add(statusLabel);   // статус виден всегда, не уезжает со скроллом

// Прокручиваемая часть — содержимое вкладок
var scrollBody = ui.Panel({style: theme.STYLE.scrollBody});
scrollBody.add(tabsWidget.content);

var rightPanel = ui.Panel({style: theme.STYLE.rightPanel});
rightPanel.add(headerZone);
rightPanel.add(scrollBody);

// ===========================================================================
// Initial state: show only current year layer
// ===========================================================================

(function setInitialYearVisibility() {
  var cfg = gas_registry.get(state.gas);
  cfg.years.forEach(function(y) {
    if (state.catalogLayers[y]) {
      state.catalogLayers[y].setShown(y === state.year && state.detectionsOn);
    }
  });
})();

ui.root.clear();
ui.root.add(ui.SplitPanel({
  firstPanel:  ui.Panel([leftMap]),
  secondPanel: rightPanel,
  orientation: 'horizontal',
  wipe: false
}));

// ===========================================================================
// Callbacks (closure factory — рад circular references к tab panels)
// ===========================================================================

function getCallbacks() {
  return {
    setGas: function(gasId) {
      stopAnimation();          // таймер относится к годам прежнего газа
      state.gas = gasId;
      rebuildAllLayers();
    },
    setYear: function(year) { applyYear(year); },
    // Регистрация виджетов, состояние которых синхронизируется извне
    registerYearSelect: function(w) { yearSelectRef = w; },
    registerPlayButton: function(b) { playBtnRef = b; },
    // Анимация по годам: ui.util.setInterval → ui.util.clearTimeout.
    // Слои по годам уже построены, переключается только видимость —
    // тайлы кэшируются после первого показа, прироста EECU почти нет.
    toggleAnimation: function() {
      if (state.animationKey !== null) { stopAnimation(); return false; }
      var cfg = gas_registry.get(state.gas);
      var years = cfg.years;
      state.animationKey = ui.util.setInterval(function() {
        var i = years.indexOf(state.year);
        applyYear(years[(i + 1) % years.length]);
      }, ANIMATION_MS);
      setStatus('Year animation running…', 'loading');
      return true;
    },
    setSourceType: function(srcType) {
      state.srcType = srcType;
      rebuildCurrentYearLayer();
    },
    toggleDetections: function(visible) {
      state.detectionsOn = visible;
      var l = state.catalogLayers[state.year];
      if (l) l.setShown(visible);
    },
    toggleReference: function(refId, partKey, visible) {
      if (state.referenceLayers[refId] && state.referenceLayers[refId][partKey]) {
        state.referenceLayers[refId][partKey].setShown(visible);
      }
    },
    toggleBoundary: function(visible) {
      if (state.boundaryLayer) state.boundaryLayer.setShown(visible);
    }
  };
}


// ===========================================================================
// «View event on map» — invoked from Catalog tab row
// ===========================================================================

function viewEventOnMap(props) {
  if (typeof props.centroid_lon === 'number' && typeof props.centroid_lat === 'number') {
    leftMap.setCenter(props.centroid_lon, props.centroid_lat, 9);
    state.selectedEvent = props;
    showEventDetail(props);  // floating window on the map
    setStatus('Showing event ' + (props.event_id || ''), 'ready');
  } else {
    setStatus('Event has no centroid — cannot jump', 'error');
  }
}

// ===========================================================================
// Год: единая точка применения (dropdown, клик по графику, анимация)
// ===========================================================================

function applyYear(year) {
  state.year = year;
  var cfg = gas_registry.get(state.gas);
  cfg.years.forEach(function(y) {
    if (state.catalogLayers[y]) {
      state.catalogLayers[y].setShown(y === year && state.detectionsOn);
    }
  });
  // Синхронизация выпадающего списка (без повторного вызова onChange)
  if (yearSelectRef) yearSelectRef.setValue(year, false);
  table_view.refresh();
}

function stopAnimation() {
  if (state.animationKey !== null) {
    ui.util.clearTimeout(state.animationKey);
    state.animationKey = null;
  }
  if (playBtnRef) {
    playBtnRef.setLabel('▶');
    playBtnRef.style().set(theme.STYLE.actionBtn);
  }
  setStatus('Ready', 'ready');
}

// ===========================================================================
// Layer rebuild helpers
// ===========================================================================

function rebuildAllLayers() {
  leftMap.layers().reset();
  state.boundaryLayer = layer_factory.buildBoundaryLayer(leftMap);  // re-add boundary (reset cleared it)
  state.catalogLayers = layer_factory.buildCatalogLayers(state.gas, leftMap);
  state.referenceLayers = layer_factory.buildAllReferencesForGas(state.gas, leftMap);
  var cfg = gas_registry.get(state.gas);
  cfg.years.forEach(function(y) {
    if (state.catalogLayers[y]) {
      state.catalogLayers[y].setShown(y === state.year && state.detectionsOn);
    }
  });
  table_view.refresh();
}

function rebuildCurrentYearLayer() {
  var year = state.year;
  if (state.catalogLayers[year]) {
    leftMap.layers().remove(state.catalogLayers[year]);
  }
  var assetId = gas_registry.catalogAsset(state.gas, year);
  var fc = ee.FeatureCollection(assetId);
  if (state.srcType) fc = fc.filter(ee.Filter.eq('nearest_source_type', state.srcType));
  var styled = styling.styleFc(fc);
  var layer = ui.Map.Layer(
    styled.style({styleProperty: 'style', neighborhood: 16}),
    {},
    state.gas + ' events ' + year + (state.srcType ? ' (' + state.srcType + ')' : ''),
    state.detectionsOn
  );
  leftMap.layers().add(layer);
  state.catalogLayers[year] = layer;
}
