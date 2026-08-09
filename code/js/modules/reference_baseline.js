/**
 * @fileoverview Reference Baseline construction module.
 *
 * Реализует Algorithm v2.3 §11 (Reference Baseline Builder) — positive-space
 * baseline на основе российских заповедников (DNA v2.2 §1.2 «Reference Clean Zone»).
 *
 * Используется Detection Engine (Algorithm §3.4.0) и UI App для построения per-month
 * reference baseline value, anchored в federal protected areas. Pair с regional
 * climatology (Algorithm §3.4.1) даёт dual baseline approach с consistency
 * cross-check (Algorithm §3.4.3).
 *
 * Реализация перенесена из RNA v1.2 §11.2 (адаптированы пути под `nodal-thunder-481307-u1`).
 *
 * @module reference_baseline
 */

/* eslint-disable no-undef */

/** Asset path to reference zones FeatureCollection (P-00.1 deliverable). */
exports.PROTECTED_AREAS_ASSET =
  'projects/nodal-thunder-481307-u1/assets/RuPlumeScan/reference/protected_areas';

/** Per-gas TROPOMI L3 collection IDs and bias-corrected band names. */
exports.GAS_COLLECTIONS = {
  CH4: {
    id: 'COPERNICUS/S5P/OFFL/L3_CH4',
    band: 'CH4_column_volume_mixing_ratio_dry_air_bias_corrected',
  },
  NO2: {
    id: 'COPERNICUS/S5P/OFFL/L3_NO2',
    band: 'tropospheric_NO2_column_number_density',
  },
  SO2: {
    id: 'COPERNICUS/S5P/OFFL/L3_SO2',
    band: 'SO2_column_number_density',
  },
};

/**
 * Загрузить Reference Clean Zones, отфильтровать по quality_status.
 *
 * Per DNA §2.1 запрет 16 — `optional_pending_quality` zones (Алтайский по
 * умолчанию) НЕ включаются в production baseline до прохождения QA test.
 * `config.use_altaisky_if_quality_passed=true` + Алтайский с
 * `quality_status="active"` (после QA pass) — единственный путь для inclusion.
 *
 * @param {Object} config - `config.reference_baseline` подсекция.
 * @param {Array<string>} config.use_zones - какие zones включить.
 * @param {boolean} config.use_altaisky_if_quality_passed - try add Altaisky.
 * @return {ee.FeatureCollection} - active zones для baseline construction.
 */
exports.loadReferenceZones = function (config) {
  var zones_fc = ee.FeatureCollection(exports.PROTECTED_AREAS_ASSET);

  // Filter to active zones (excludes optional_pending_quality / unreliable)
  var active = zones_fc.filter(ee.Filter.eq('quality_status', 'active'));

  // Filter to zones in use_zones list
  active = active.filter(ee.Filter.inList('zone_id', config.use_zones));

  // Optionally include Altaisky if quality passed
  if (config.use_altaisky_if_quality_passed) {
    var altaisky = zones_fc.filter(ee.Filter.and(
      ee.Filter.eq('zone_id', 'altaisky'),
      ee.Filter.eq('quality_status', 'active')
    ));
    active = active.merge(altaisky);
  }

  return active;
};

/**
 * Применить per-zone internal buffer (negative buffer для исключения edge effects).
 *
 * Реализационная gotcha (Algorithm §13 + RNA §10.10): negative `buffer()` на
 * complex polygon без предварительного `simplify()` может дать invalid geometry.
 * Решение — pre-simplify с `maxError=100` (m) перед apply negative buffer.
 *
 * @param {ee.FeatureCollection} zones - zones с `internal_buffer_km` property.
 * @return {ee.FeatureCollection} - zones с shrunk geometry.
 */
exports.applyInternalBuffers = function (zones) {
  return zones.map(function (zone) {
    var buffer_km = ee.Number(zone.get('internal_buffer_km'));
    var simplified = zone.geometry().simplify({ maxError: 100 });
    var buffered = simplified.buffer(buffer_km.multiply(-1000));
    return zone.setGeometry(buffered);
  });
};

/**
 * Построить per-zone climatology values (single baseline_ppb + sigma_ppb + count
 * per zone per target_month).
 *
 * Per Algorithm §3.4.0 Step 3: median (robust to outliers) + MAD-based sigma
 * (1.4826 × MAD ≈ robust σ-equivalent for Gaussian-like distributions).
 *
 * History window: years [2019, target_year-1], months [target_month-1, +1]
 * (3-month DOY window per RNA §7.1 default `doy_window_half_days=30`).
 *
 * @param {ee.FeatureCollection} zones - после applyInternalBuffers.
 * @param {string} gas - CH4 | NO2 | SO2.
 * @param {number} target_year
 * @param {number} target_month
 * @param {Object} config - full Configuration (uses analysis_scale_m).
 * @return {ee.FeatureCollection} - zones с added baseline_ppb, sigma_ppb,
 *   count_avg, target_year, target_month, gas properties.
 */
exports.buildZoneBaselines = function (zones, gas, target_year, target_month, config) {
  var ds = exports.GAS_COLLECTIONS[gas];

  return zones.map(function (zone) {
    var zone_geom = zone.geometry();

    var filtered = ee.ImageCollection(ds.id)
      .select(ds.band)
      .filter(ee.Filter.calendarRange(2019, target_year - 1, 'year'))
      .filter(ee.Filter.calendarRange(target_month - 1, target_month + 1, 'month'))
      .map(function (img) { return img.clip(zone_geom); });

    // Per-pixel median and MAD-based sigma
    var median_image = filtered.reduce(ee.Reducer.median());
    var mad_image = filtered
      .map(function (img) { return img.subtract(median_image).abs(); })
      .reduce(ee.Reducer.median())
      .multiply(1.4826);
    var count_image = filtered.count();

    // Aggregate в single value per zone (mean over zone pixels)
    var baseline_value = median_image.reduceRegion({
      reducer: ee.Reducer.mean(),
      geometry: zone_geom,
      scale: 7000,
      maxPixels: 1e8,
    }).values().get(0);

    var sigma_value = mad_image.reduceRegion({
      reducer: ee.Reducer.mean(),
      geometry: zone_geom,
      scale: 7000,
      maxPixels: 1e8,
    }).values().get(0);

    var count_value = count_image.reduceRegion({
      reducer: ee.Reducer.mean(),
      geometry: zone_geom,
      scale: 7000,
      maxPixels: 1e8,
    }).values().get(0);

    return zone.set({
      baseline_ppb: baseline_value,
      sigma_ppb: sigma_value,
      count_avg: count_value,
      target_year: target_year,
      target_month: target_month,
      gas: gas,
    });
  });
};

/**
 * Latitude-stratified baseline image для AOI: каждый pixel получает baseline
 * ближайшего по latitude reference zone.
 *
 * Server-side iteration через `ee.List.iterate()` без `evaluate()` callback
 * (per Algorithm §13 GEE gotcha).
 *
 * @param {ee.Geometry} aoi
 * @param {ee.FeatureCollection} zone_baselines - после buildZoneBaselines.
 * @param {number} scale_m - reproject scale.
 * @return {ee.Image} - bands `reference_baseline`, `reference_sigma`,
 *   `min_lat_distance` (zone assignment proxy).
 */
exports.buildStratifiedBaseline = function (aoi, zone_baselines, scale_m) {
  var lat_image = ee.Image.pixelLonLat().select('latitude');

  // Подача zones как list (max 10 для bounded compute)
  var zones_list = zone_baselines.toList(zone_baselines.size().min(10));

  // Initialize: very large distance, default baseline = 0 (will be overwritten)
  var init_image = ee.Image.cat([
    ee.Image.constant(99999).rename('min_lat_distance'),
    ee.Image.constant(0).rename('reference_baseline'),
    ee.Image.constant(0).rename('reference_sigma'),
  ]);

  // Iterate zones: each round update pixel if это closer zone
  var result = ee.List.sequence(0, zones_list.size().subtract(1)).iterate(
    function (idx, accum) {
      var zone = ee.Feature(zones_list.get(ee.Number(idx)));
      var zone_lat = ee.Number(zone.get('centroid_lat'));
      var zone_baseline = ee.Number(zone.get('baseline_ppb'));
      var zone_sigma = ee.Number(zone.get('sigma_ppb'));

      var lat_dist = lat_image.subtract(zone_lat).abs();
      var accum_img = ee.Image(accum);
      var closer_mask = lat_dist.lt(accum_img.select('min_lat_distance'));

      // Update bands where current zone is closer
      var new_min_dist = lat_dist.where(closer_mask.not(), accum_img.select('min_lat_distance'));
      var new_baseline = ee.Image.constant(zone_baseline)
        .where(closer_mask.not(), accum_img.select('reference_baseline'));
      var new_sigma = ee.Image.constant(zone_sigma)
        .where(closer_mask.not(), accum_img.select('reference_sigma'));

      return ee.Image.cat([
        new_min_dist.rename('min_lat_distance'),
        new_baseline.rename('reference_baseline'),
        new_sigma.rename('reference_sigma'),
      ]);
    },
    init_image
  );

  return ee.Image(result).reproject({ crs: 'EPSG:4326', scale: scale_m }).clip(aoi);
};

/**
 * Полный pipeline: load → buffer → buildZoneBaselines → stratify.
 *
 * @param {string} gas
 * @param {number} target_year
 * @param {number} target_month
 * @param {ee.Geometry} aoi
 * @param {Object} config - full Configuration.
 * @return {ee.Image} - per-pixel reference baseline для (gas, year, month, AOI).
 */
exports.buildReferenceBaseline = function (gas, target_year, target_month, aoi, config) {
  var zones = exports.loadReferenceZones(config.reference_baseline);
  var buffered = exports.applyInternalBuffers(zones);
  var zone_baselines = exports.buildZoneBaselines(buffered, gas, target_year, target_month, config);
  var stratified = exports.buildStratifiedBaseline(aoi, zone_baselines, config.analysis_scale_m);

  return stratified;
};

/**
 * Проверка: попадает ли geometry внутрь любого reference zone.
 *
 * Используется при detection для `matched_inside_reference_zone` flag в
 * Common Plume Schema (DNA v2.2 §4.2 ML-readiness slot — strong negative
 * training signal: industrial activity внутри zapovednik запрещена законом).
 *
 * @param {ee.Geometry} pixel_or_geom - candidate detection geometry.
 * @return {ee.String} - zone_id если внутри какой-то zone, иначе 'none'.
 */
exports.checkInsideZone = function (pixel_or_geom) {
  var zones = ee.FeatureCollection(exports.PROTECTED_AREAS_ASSET);
  var intersecting = zones.filterBounds(pixel_or_geom);

  return ee.Algorithms.If(
    intersecting.size().gt(0),
    intersecting.first().get('zone_id'),
    ee.String('none')
  );
};
