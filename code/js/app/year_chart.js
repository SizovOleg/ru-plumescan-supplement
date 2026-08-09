/**
 * @fileoverview Годовой график каталога — интерактивная навигация по годам.
 *
 * Столбцы: достоверные / вероятные артефакты по годам. Данные берутся из
 * gas_registry.per_year_stats (каталог заморожен) — серверных запросов нет,
 * стоимость 0 EECU.
 *
 * Живое поведение (нативное для ui.Chart / Google Charts, работает и в
 * опубликованном приложении):
 *   - всплывающая подсказка при наведении на столбец;
 *   - клик по столбцу → переключение года (график = навигация).
 *
 * @module app/year_chart
 */

/* eslint-disable no-undef */

var theme        = require('users/ntcomz18_sand/plumescan:app/theme');
var gas_registry = require('users/ntcomz18_sand/plumescan:app/gas_registry');

/**
 * Построить график для газа.
 *
 * @param {string} gasId
 * @param {function(string)} onYearPick — вызывается с годом при клике по столбцу
 * @return {!ui.Chart}
 */
exports.build = function(gasId, onYearPick) {
  var cfg = gas_registry.get(gasId);
  var stats = cfg.per_year_stats || {};

  var rows = [['Year', 'Valid', 'Artifact']];
  cfg.years.forEach(function(y) {
    var s = stats[y] || {valid: 0, artifact: 0};
    rows.push([y, s.valid, s.artifact]);
  });

  var chart = ui.Chart(rows, 'ColumnChart', {
    isStacked: true,
    legend: {position: 'none'},
    colors: ['#2E7D32', '#B45309'],
    height: 150,
    chartArea: {width: '86%', height: '68%'},
    hAxis: {textStyle: {fontSize: 11}, gridlines: {color: 'transparent'}},
    vAxis: {textStyle: {fontSize: 10}, gridlines: {color: '#ECE6DC'},
            minValue: 0, baselineColor: '#D8DEE4'},
    backgroundColor: {fill: 'transparent'},
    tooltip: {textStyle: {fontSize: 12}}
  });
  chart.style().set({stretch: 'horizontal', margin: '0', height: '150px'});

  // Клик по столбцу → выбор года. Защитно: если метод недоступен в среде,
  // всплывающие подсказки всё равно работают, приложение не падает.
  if (chart.onClick && onYearPick) {
    chart.onClick(function(xValue) {
      if (xValue) onYearPick(String(xValue));
    });
  }
  return chart;
};

/**
 * Стат-строка каталога для шапки: «122 события · 96 факелов · …».
 * @param {string} gasId
 * @return {string}
 */
exports.statLine = function(gasId) {
  var s = (gas_registry.get(gasId) || {}).catalog_stats || {};
  if (!s.n_total) return '';
  var maxZ = String(s.max_z_observed || '');
  return s.n_total + ' detections  ·  ' + s.n_flare + ' flares  ·  ' +
         s.n_gas_field + ' gas fields  ·  max z ' + maxZ;
};
