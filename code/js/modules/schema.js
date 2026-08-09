/**
 * @fileoverview Common Plume Schema — JavaScript-валидация для GEE
 * FeatureCollection-выходов. Соответствует Algorithm.md §2.1.
 *
 * Используется:
 *   - Detection-модулями (CH4 / NO2 / SO2) перед Export.toAsset для
 *     гарантии что каждое Feature соответствует Common Schema.
 *   - Comparison Engine для нормализации при cross-source matching.
 *
 * Парная Python-реализация: src/py/rca/common_schema.py.
 */

/* eslint-disable no-undef */

/**
 * Текущая версия Common Plume Schema. См. DNA §2.3 — изменение = breaking change.
 *
 * v1.0 -> v1.1 (2026-04-29): added 5 dual-baseline fields per Algorithm v2.3 §2.1:
 *   delta_vs_regional_climatology, delta_vs_reference_baseline,
 *   baseline_consistency_flag, matched_inside_reference_zone, nearest_reference_zone.
 */
exports.SCHEMA_VERSION = '1.1';

/** Допустимые газы. */
exports.GAS_TYPES = ['CH4', 'NO2', 'SO2'];

/** Уровни confidence. */
exports.CONFIDENCE_LEVELS = ['low', 'medium', 'high', 'very_high'];

/** Классы событий per DNA §1.3. */
exports.EVENT_CLASSES = [
  'CH4_only',
  'NO2_only',
  'SO2_only',
  'CH4_NO2',
  'NO2_SO2',
  'CH4_SO2',
  'CH4_NO2_SO2',
  'diffuse_CH4',
  'wind_ambiguous',
];

/** Допустимые единицы magnitude_proxy. */
exports.MAGNITUDE_UNITS = ['ppb', 'µmol/m²', 'umol/m2', 't/h', 'kg/h', 'mol/m²'];

/** Методы детекции. */
exports.DETECTION_METHODS = [
  'regional_threshold',
  'beirle_divergence',
  'fioletov_rotation',
  'external_reference',
];

/** Допустимые source_catalog. */
exports.SOURCE_CATALOGS = [
  'ours',
  'schuit2023',
  'imeo_mars',
  'cams_hotspot',
  'lauvaux2022',
  'carbon_mapper',
  'cherepanova2023',
  'fioletov_so2',
  'beirle2021_no2',
];

/** Типы industrial source. */
exports.SOURCE_TYPES = [
  'coal_mine',
  'oil_gas',
  'power_plant',
  'metallurgy',
  'urban',
  'wetland',
  'other',
];

/**
 * Все поля Common Plume Schema. Группировка та же что в Python-версии.
 * Used by `requiredFields()` и `allFields()`.
 */
var ALL_FIELDS = [
  // Identification
  'event_id', 'source_catalog', 'source_event_id', 'schema_version', 'ingestion_date',
  // Базовая атрибутика
  'gas', 'date_utc', 'time_utc', 'orbit',
  // Геометрия (geometry — отдельно как Feature.geometry, не property)
  'lon', 'lat', 'area_km2', 'n_pixels',
  // Detection metrics
  'max_z', 'mean_z', 'max_delta', 'mean_delta', 'detection_method',
  // Wind context
  'wind_u', 'wind_v', 'wind_speed', 'wind_dir_deg',
  'plume_axis_deg', 'wind_alignment_score', 'wind_source',
  // Source attribution
  'nearest_source_id', 'nearest_source_distance_km', 'nearest_source_type',
  // Magnitude proxy
  'magnitude_proxy', 'magnitude_proxy_unit',
  // Quantification
  'ime_kg', 'q_kg_h_experimental', 'q_uncertainty_factor',
  'quantification_method', 'quantification_disclaimer',
  // Classification
  'class', 'confidence', 'confidence_score', 'qa_flags',
  // Dual baseline (NEW в v1.1, Algorithm v2.3 §2.1)
  'delta_vs_regional_climatology', 'delta_vs_reference_baseline',
  'baseline_consistency_flag', 'matched_inside_reference_zone', 'nearest_reference_zone',
  // Cross-source agreement
  'matched_schuit2023', 'schuit_event_id',
  'matched_imeo_mars', 'imeo_event_id',
  'matched_cams', 'cams_event_id',
  'agreement_score', 'last_comparison_date',
  // Configuration provenance
  'algorithm_version', 'config_id', 'params_hash', 'run_id', 'run_date',
  // ML-readiness
  'expert_label', 'label_source', 'label_date',
  'label_confidence', 'feature_vector',
];

/** Обязательные поля для любого Feature (независимо от source). */
var REQUIRED_FIELDS = [
  'event_id', 'source_catalog', 'source_event_id', 'schema_version',
  'ingestion_date', 'gas', 'date_utc', 'lon', 'lat',
];

/**
 * Дополнительно обязательные поля для `source_catalog == "ours"`
 * (DNA §2.1: «Не выдавать Run без полного config snapshot»).
 */
var REQUIRED_FOR_OURS = [
  'algorithm_version', 'config_id', 'params_hash', 'run_id', 'run_date',
  'detection_method',
];

/**
 * Возвращает список всех имён полей Common Schema.
 * @return {Array<string>}
 */
exports.allFields = function () {
  return ALL_FIELDS.slice();
};

/**
 * Возвращает список обязательных имён полей. Если передан `sourceCatalog`,
 * добавляются provenance-поля для `"ours"`.
 * @param {string=} sourceCatalog Опциональный source_catalog для contextual required.
 * @return {Array<string>}
 */
exports.requiredFields = function (sourceCatalog) {
  var fields = REQUIRED_FIELDS.slice();
  if (sourceCatalog === 'ours') {
    REQUIRED_FOR_OURS.forEach(function (f) { fields.push(f); });
  }
  return fields;
};

/**
 * Серверная (server-side) проверка одного `ee.Feature` на соответствие
 * Common Schema. В отличие от Python, здесь это не runtime-валидация
 * (на server-side нет try/catch), а конструкция Feature с новыми
 * properties: `_schema_valid` (bool) и `_schema_errors` (string,
 * comma-separated).
 *
 * Используется в pre-export шаге Detection pipeline:
 *   var validated = candidates.map(schema.tagFeatureValidity);
 *   var errors = validated.filter(ee.Filter.eq('_schema_valid', false));
 *
 * @param {ee.Feature} feature Feature с properties Common Schema.
 * @return {ee.Feature} Feature с добавленными `_schema_valid`,
 *   `_schema_errors`.
 */
exports.tagFeatureValidity = function (feature) {
  var props = feature.toDictionary();
  var sourceCatalog = props.get('source_catalog');

  // Required fields presence — server-side: для каждого required field
  // проверяем что property exists и не null. Bug pre-fix (CR review CLAIM
  // от 2026-04-29): missingRequired использовал ee.List(constants).filter()
  // который filter-ил список констант, не Feature properties. Now uses
  // .keys()/.values() of toDictionary() для actual property check.
  var propsKeys = props.keys();
  var missingRequired = ee.List(REQUIRED_FIELDS).filter(
    ee.Filter.notNull(['item']).Not()
  ).cat(
    // Fields present в REQUIRED_FIELDS but NOT в feature properties keys
    ee.List(REQUIRED_FIELDS).removeAll(propsKeys)
  ).cat(
    // Fields present в keys but null/undefined value
    ee.List(REQUIRED_FIELDS).filter(
      ee.Filter.lte('item', '0')  // dummy filter — replaced below
    )
  );
  // Build correct missing list using server-side iteration
  missingRequired = ee.List(REQUIRED_FIELDS).iterate(
    function (field, accum) {
      var fieldStr = ee.String(field);
      var hasKey = propsKeys.contains(fieldStr);
      var notNull = ee.Algorithms.If(
        hasKey,
        ee.Algorithms.If(props.get(fieldStr), true, false),
        false
      );
      return ee.Algorithms.If(
        notNull,
        accum,
        ee.List(accum).add(fieldStr)
      );
    },
    ee.List([])
  );
  missingRequired = ee.List(missingRequired);

  // Provenance check для source_catalog="ours"
  var oursMissingProvenance = ee.List(REQUIRED_FOR_OURS).iterate(
    function (field, accum) {
      var fieldStr = ee.String(field);
      var hasKey = propsKeys.contains(fieldStr);
      var notNull = ee.Algorithms.If(
        hasKey,
        ee.Algorithms.If(props.get(fieldStr), true, false),
        false
      );
      return ee.Algorithms.If(
        notNull,
        accum,
        ee.List(accum).add(fieldStr)
      );
    },
    ee.List([])
  );
  oursMissingProvenance = ee.List(ee.Algorithms.If(
    ee.String(sourceCatalog).equals('ours'),
    oursMissingProvenance,
    ee.List([])
  ));

  // Enum checks
  var hasGas = ee.List(exports.GAS_TYPES).contains(props.get('gas'));
  var hasSource = ee.List(exports.SOURCE_CATALOGS).contains(sourceCatalog);
  var validSchema = ee.String(props.get('schema_version')).equals(exports.SCHEMA_VERSION);

  var noMissing = missingRequired.size().eq(0);
  var noProvMissing = oursMissingProvenance.size().eq(0);

  var allOk = ee.Number(hasGas).and(hasSource).and(validSchema)
    .and(noMissing).and(noProvMissing);

  return feature.set({
    _schema_valid: allOk,
    _schema_missing_required: missingRequired,
    _schema_missing_provenance: oursMissingProvenance,
    _schema_errors: ee.Algorithms.If(
      allOk,
      '',
      ee.String('failed enum/schema_version check OR missing required: ')
        .cat(missingRequired.join(','))
        .cat(' OR missing provenance: ')
        .cat(oursMissingProvenance.join(','))
    ),
  });
};

/**
 * Client-side валидация одного plain object (например, из
 * `ee.Feature.toDictionary().getInfo()` или Configuration UI).
 * Возвращает `{valid: bool, errors: Array<string>}`.
 *
 * @param {Object} feature Plain object с полями Common Schema.
 * @return {{valid: boolean, errors: Array<string>}}
 */
exports.validatePlumeEvent = function (feature) {
  var errors = [];

  // Required fields presence
  var sourceCatalog = feature.source_catalog;
  var required = exports.requiredFields(sourceCatalog);
  required.forEach(function (field) {
    if (feature[field] === null || feature[field] === undefined) {
      errors.push('missing required field: ' + field);
    }
  });

  // Enum checks
  if (feature.gas !== undefined && exports.GAS_TYPES.indexOf(feature.gas) === -1) {
    errors.push('gas must be one of [' + exports.GAS_TYPES.join(',') + '], got "' + feature.gas + '"');
  }
  if (
    feature.source_catalog !== undefined &&
    exports.SOURCE_CATALOGS.indexOf(feature.source_catalog) === -1
  ) {
    errors.push(
      'source_catalog must be one of [' + exports.SOURCE_CATALOGS.join(',') +
      '], got "' + feature.source_catalog + '"'
    );
  }
  if (
    feature.confidence !== undefined && feature.confidence !== null &&
    exports.CONFIDENCE_LEVELS.indexOf(feature.confidence) === -1
  ) {
    errors.push(
      'confidence must be one of [' + exports.CONFIDENCE_LEVELS.join(',') +
      '], got "' + feature.confidence + '"'
    );
  }
  if (
    feature['class'] !== undefined && feature['class'] !== null &&
    exports.EVENT_CLASSES.indexOf(feature['class']) === -1
  ) {
    errors.push(
      'class must be one of [' + exports.EVENT_CLASSES.join(',') +
      '], got "' + feature['class'] + '"'
    );
  }
  if (
    feature.detection_method !== undefined && feature.detection_method !== null &&
    exports.DETECTION_METHODS.indexOf(feature.detection_method) === -1
  ) {
    errors.push(
      'detection_method must be one of [' + exports.DETECTION_METHODS.join(',') +
      '], got "' + feature.detection_method + '"'
    );
  }
  if (
    feature.magnitude_proxy_unit !== undefined && feature.magnitude_proxy_unit !== null &&
    exports.MAGNITUDE_UNITS.indexOf(feature.magnitude_proxy_unit) === -1
  ) {
    errors.push(
      'magnitude_proxy_unit must be one of [' + exports.MAGNITUDE_UNITS.join(',') +
      '], got "' + feature.magnitude_proxy_unit + '"'
    );
  }

  // Coordinate ranges
  if (typeof feature.lon === 'number' && (feature.lon < -180 || feature.lon > 180)) {
    errors.push('lon must be in [-180, 180], got ' + feature.lon);
  }
  if (typeof feature.lat === 'number' && (feature.lat < -90 || feature.lat > 90)) {
    errors.push('lat must be in [-90, 90], got ' + feature.lat);
  }

  // Schema version
  if (feature.schema_version !== undefined && feature.schema_version !== exports.SCHEMA_VERSION) {
    errors.push(
      'schema_version mismatch: expected "' + exports.SCHEMA_VERSION +
      '", got "' + feature.schema_version + '"'
    );
  }

  // wind_alignment_score range
  if (
    typeof feature.wind_alignment_score === 'number' &&
    (feature.wind_alignment_score < 0 || feature.wind_alignment_score > 1)
  ) {
    errors.push('wind_alignment_score must be in [0, 1]');
  }

  // confidence_score range
  if (
    typeof feature.confidence_score === 'number' &&
    (feature.confidence_score < 0 || feature.confidence_score > 1)
  ) {
    errors.push('confidence_score must be in [0, 1]');
  }

  return { valid: errors.length === 0, errors: errors };
};

/**
 * Применяет config snapshot (algorithm_version, config_id, params_hash,
 * run_id, run_date) ко всем Features в коллекции. DNA §2.1 требует
 * эти поля для каждого Feature с `source_catalog="ours"`.
 *
 * @param {ee.Feature} feature Feature без provenance.
 * @param {Object} config Configuration object с полями algorithmVersion,
 *   configId, paramsHash, runId, runDate.
 * @return {ee.Feature} Feature с добавленными config snapshot полями.
 */
exports.applyConfigSnapshot = function (feature, config) {
  return feature.set({
    algorithm_version: config.algorithmVersion || config.algorithm_version,
    config_id: config.configId || config.config_id,
    params_hash: config.paramsHash || config.params_hash,
    run_id: config.runId || config.run_id,
    run_date: config.runDate || config.run_date,
  });
};

/**
 * Применяет config snapshot к каждому Feature в коллекции через `.map()`.
 * Использует factory pattern для closures (RNA §4.3, Algorithm §12.1).
 *
 * @param {ee.FeatureCollection} collection
 * @param {Object} config См. applyConfigSnapshot.
 * @return {ee.FeatureCollection}
 */
exports.applyConfigSnapshotToCollection = function (collection, config) {
  // Factory pattern: capture config в closure через bind вместо
  // обращения к внешним переменным.
  var snapshotter = function (cfg) {
    return function (feature) {
      return exports.applyConfigSnapshot(feature, cfg);
    };
  };
  return collection.map(snapshotter(config));
};
