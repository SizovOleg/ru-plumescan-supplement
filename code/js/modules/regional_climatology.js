/**
 * @fileoverview Regional climatology module с industrial buffer exclusion.
 *
 * Реализует Algorithm v2.3 §3.4.1 — secondary baseline в dual baseline
 * approach. Primary baseline = reference (positive-space, заповедники).
 * Regional = negative-space (clean ≡ NOT industrial), broader spatial
 * coverage but с unknown unknowns per DNA v2.2 §1.5.
 *
 * Per-gas implementation через config.gas selector. Used by Detection
 * Engine (CH₄ Algorithm §3.4.3 hybrid background, NO₂ Algorithm §4 directly,
 * SO₂ Algorithm §5 directly).
 *
 * @module regional_climatology
 */

/* eslint-disable no-undef */

/** Industrial proxy mask (P-00.1 deliverable) — raster 1=industrial, 0=clean. */
exports.INDUSTRIAL_MASK_ASSET =
  'projects/nodal-thunder-481307-u1/assets/RuPlumeScan/industrial/proxy_mask';

/** Per-gas TROPOMI L3 collection IDs and bias-corrected band names. */
exports.GAS_COLLECTIONS = {
  CH4: {
    id: 'COPERNICUS/S5P/OFFL/L3_CH4',
    band: 'CH4_column_volume_mixing_ratio_dry_air_bias_corrected',
    qa_filter: function (img) {
      // Algorithm §3.3 — qa_value, AOD, solar_zenith, physical range
      return img.updateMask(
        img.select('CH4_column_volume_mixing_ratio_dry_air_bias_corrected').gte(1700).and(
          img.select('CH4_column_volume_mixing_ratio_dry_air_bias_corrected').lte(2200)
        )
      );
    },
  },
  NO2: {
    id: 'COPERNICUS/S5P/OFFL/L3_NO2',
    band: 'tropospheric_NO2_column_number_density',
    qa_filter: function (img) {
      // Algorithm §4.3 — stricter qa_value 0.75, cloud_fraction < 0.3
      var masked = img;
      if (img.bandNames().contains('cloud_fraction')) {
        masked = masked.updateMask(masked.select('cloud_fraction').lt(0.3));
      }
      return masked;
    },
  },
  SO2: {
    id: 'COPERNICUS/S5P/OFFL/L3_SO2',
    band: 'SO2_column_number_density',
    qa_filter: function (img) {
      // Algorithm §5.3 — qa_value 0.5, cloud_fraction < 0.3,
      // negative floor -0.001 mol/m² (DNA §2.1 запрет 7).
      var masked = img;
      if (img.bandNames().contains('cloud_fraction')) {
        masked = masked.updateMask(masked.select('cloud_fraction').lt(0.3));
      }
      // Filter only strong negative outliers (preserve small negatives ≈ 0)
      masked = masked.updateMask(
        masked.select('SO2_column_number_density').gte(-0.001)
      );
      return masked;
    },
  },
};

/**
 * Загрузить industrial buffer mask (1=clean, 0=industrial-buffered).
 *
 * Uses focal_max(buffer_km) over `industrial/proxy_mask` (which is уже 15 km
 * buffered per build_industrial_mask.py), затем `.not()` чтобы invert
 * (mask=1 → clean pixel kept).
 *
 * @param {number} buffer_km - Additional buffer expansion (default 15 km
 *   adds to existing 15 km in proxy_mask = effective 30 km exclusion per
 *   Algorithm §3.4.1 default).
 * @return {ee.Image} - Boolean mask 1=clean.
 */
exports.loadCleanMask = function (buffer_km) {
  return ee.Image(exports.INDUSTRIAL_MASK_ASSET)
    .unmask(0)  // outside-aoi pixels treated as 0 (clean baseline default)
    .focal_max({ radius: buffer_km * 1000, units: 'meters' })
    .not();
};

/**
 * Apply industrial buffer mask to ImageCollection.
 *
 * @param {ee.ImageCollection} collection
 * @param {number} buffer_km
 * @return {ee.ImageCollection} - С industrial pixels masked out.
 */
exports.applyIndustrialBuffer = function (collection, buffer_km) {
  var clean_mask = exports.loadCleanMask(buffer_km);
  return collection.map(function (img) {
    return img.updateMask(clean_mask);
  });
};

/**
 * Per-pixel monthly climatology: median + MAD-based sigma + count.
 *
 * History window: years [2019, target_year-1], months
 * [target_month-1, target_month+1] (3-month DOY window per RNA §7.1
 * default doy_window_half_days=30).
 *
 * Median + MAD-based sigma (1.4826 × MAD ≈ robust σ-equivalent для
 * Gaussian-like distributions). Robust to outliers per Algorithm §3.4.1.
 *
 * **DNA §2.1 запрет 4** — для CH₄ pixels masked остаются masked.
 * `unmask(0)` запрещён.
 *
 * @param {string} gas - CH4 | NO2 | SO2
 * @param {number} target_year
 * @param {number} target_month
 * @param {number} buffer_km - Industrial buffer (default 15 km adding to
 *   pre-buffered proxy_mask = 30 km effective).
 * @return {ee.Image} - 3-band Image: median, sigma, count.
 */
exports.buildMonthlyClimatology = function (gas, target_year, target_month, buffer_km) {
  var ds = exports.GAS_COLLECTIONS[gas];

  var coll = ee.ImageCollection(ds.id)
    .select(ds.band)
    .filter(ee.Filter.calendarRange(2019, target_year - 1, 'year'))
    .filter(ee.Filter.calendarRange(target_month - 1, target_month + 1, 'month'))
    .map(ds.qa_filter);

  // Apply industrial buffer
  var clean_mask = exports.loadCleanMask(buffer_km);
  var masked_coll = coll.map(function (img) {
    return img.updateMask(clean_mask);
  });

  // Per-pixel reductions
  var median_img = masked_coll.reduce(ee.Reducer.median()).rename('median');
  var mad_img = masked_coll
    .map(function (img) {
      return img.subtract(median_img).abs();
    })
    .reduce(ee.Reducer.median())
    .multiply(1.4826)
    .rename('sigma');
  var count_img = masked_coll.count().rename('count');

  return median_img.addBands(mad_img).addBands(count_img);
};

/**
 * Full pipeline для одного месяца — convenient wrapper.
 *
 * @param {string} gas
 * @param {number} target_year
 * @param {number} target_month
 * @param {Object} config - `config.background.regional`
 * @return {ee.Image}
 */
exports.buildRegionalClimatology = function (gas, target_year, target_month, config) {
  var buffer_km = config.background && config.background.regional
    ? config.background.regional.industrial_buffer_exclude_km
    : 15;  // proxy_mask уже buffered 15 km, this adds another 15 km = 30 km effective
  return exports.buildMonthlyClimatology(gas, target_year, target_month, buffer_km);
};
