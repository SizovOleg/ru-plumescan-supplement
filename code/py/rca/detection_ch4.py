"""
CH₄ detection algorithm primitives (P-02.0a + Path E v3.0 P-02.0c).

Implements Algorithm v3.0.1 §3.4-§3.10 в Python via Earth Engine Python API.
JS module `src/js/modules/detection_ch4.js` mirrors this for GEE Code Editor use.

Path E primitives (Algorithm v3.0+, P-02.0c, replacing v2.x multi-year baseline):
  * apply_latitude_band_correction (Шаг 3)   — Algorithm §3.5 per-pixel temporal-median
  * build_annulus_kernel (Шаг 4a)            — Algorithm §3.4.2 ee.Kernel.fixed
  * compute_z_local (Шаг 4a)                 — Algorithm §3.4.3 per-orbit annulus Z
  * apply_two_condition_mask (Шаг 5a)        — Algorithm §3.6 industrial-only B2 mask

Detection cascade (Algorithm §3.7-§3.10, preserved):
  * extract_clusters            — Algorithm §3.7 connectedComponents
  * compute_cluster_attributes  — Algorithm §3.8 per-cluster metrics
  * validate_wind               — Algorithm §3.9 (v2.3.1) ERA5 850hPa
                                  Шаг 5b will switch к ERA5 10m primary + 850 fallback
  * attribute_source            — Algorithm §3.10 50 km + type ranking

REMOVED в Шаге 4a P-02.0c (commit `2ca1a18`):
  * build_hybrid_background  — multi-year dual baseline (Algorithm v2.3.2 §3.4.3)
  * compute_z_score(orbit, hybrid, month) — multi-year baseline z-score
  Replaced: compute_z_local (per-orbit local annulus). См. Algorithm v3.0.1 §3.4.

REMOVED в Шаге 5a P-02.0c:
  * apply_three_condition_mask — multi-year baseline z + Δ + relative-to-annulus
  Replaced: apply_two_condition_mask (orbit valid + industrial excluded).
  См. Algorithm v3.0.3 §3.6.

DNA §2.1 critical compliances:
  * §2.1.4 unmask(0): not used. updateMask + subtract preserve NaN.
  * §2.1.5 ee.Kernel arithmetic: not used. Annulus = single ee.Kernel.fixed
    (build_annulus_kernel) with explicit weight matrix.
  * §2.1.6 single absolute threshold: per-region adaptive z_min applied at
    orchestrator level (TD-0018).
  * §2.1.17 (v2.3) L2-equivalent positioning: not violated (per-orbit L3).

GPT review #1 fixes preserved (Phase 2A heritage):
  * Issue 5.3 (CRITICAL): wind angle .mod(180) before shortest-distance min
  * Issue 2.1 (HIGH): .select('z') before reduceRegions to avoid band-prefix
    collision in property names
  * Issue 1.2 (HIGH): cos(lat) aspect correction в plume axis PCA
  * Issue 6.1 (HIGH): composite-key sort (single .sort) in attribute_source
  * Issue 5.2 (MEDIUM): null plume_axis_deg → wind_consistent=null (not false)
  * Issue 1.3 (MEDIUM): wind direction explicit +360 step before mod
  * Issue 2.3 (MEDIUM): wind_state enum field {aligned, misaligned,
    insufficient_wind, axis_unknown}
"""

from __future__ import annotations

import math

import ee
import numpy as np

# ---------------------------------------------------------------------------
# Constants (per Algorithm v2.3.2)
# ---------------------------------------------------------------------------

ANALYSIS_SCALE_M = 7000  # TROPOMI L3 grid

# Эталон фона (Algorithm v3.2.0 §3.6.2) — параметр конфигурации, не версия.
#   industrial_buffers — медиана/MAD кольца по пикселям буферных зон инфраструктуры;
#                        центральный пиксель обязан лежать в буфере (опубликованный каталог)
#   regional_clean     — по чистым пикселям; кандидаты ограничиваются явным фильтром
ANNULUS_REFERENCE_INDUSTRIAL = "industrial_buffers"
ANNULUS_REFERENCE_CLEAN = "regional_clean"
ANNULUS_REFERENCES = (ANNULUS_REFERENCE_INDUSTRIAL, ANNULUS_REFERENCE_CLEAN)
SIGMA_FLOOR_PPB = 15.0  # CH4 noise floor (Algorithm §3.5)

# Annulus parameters (Algorithm §3.6)
ANNULUS_OUTER_KM_DEFAULT = 150  # outer disk radius
ANNULUS_INNER_KM_DEFAULT = 50  # inner disk excluded ideally; bias ~12%

# Hybrid background tolerance (Algorithm §3.4.3)
CONSISTENCY_TOLERANCE_PPB_DEFAULT = 30.0  # |ref - reg| < 30 ppb → consistent

# Source type priorities for CH₄ detection (Algorithm §3.10)
SOURCE_TYPE_PRIORITIES_CH4 = {
    "gas_field": 1,
    "viirs_flare_high": 2,
    "coal_mine": 3,
    "tpp_gres": 4,
    "viirs_flare_low": 5,
    "smelter": 6,
}


# ---------------------------------------------------------------------------
# Path E primitive: two-condition mask (Algorithm v3.0.3 §3.6, Шаг 5a P-02.0c)
# Replaces v2.x apply_three_condition_mask (multi-year baseline + relative-to-annulus).
# B2 scope: industrial-only exclusion. Wetland/water deferred к v1.1 (TD-0038/0039).
# ---------------------------------------------------------------------------


def apply_two_condition_mask(
    orbit_image: ee.Image,
    industrial_mask: ee.Image,
    target_band: str = "CH4_column_volume_mixing_ratio_dry_air_bias_corrected",
    annulus_reference: str = ANNULUS_REFERENCE_INDUSTRIAL,
) -> ee.Image:
    """
    Algorithm v3.0.3 §3.6: two-condition pixel mask (Path E B2 industrial-only).

    Used as `proxy_mask` argument к `compute_z_local` — pixels where mask=1 are
    INCLUDED в annulus stats; mask=0 excluded.

    Conditions:
        1. orbit_image имеет valid CH₄ retrieval (TROPOMI native QA via .mask())
        2. pixel входит в выборку кольца по эталону `annulus_reference`
           (industrial_buffers: пиксель внутри буфера инфраструктуры, значение 0;
            regional_clean: чистый пиксель, значение 1)

    Path E B2 scope decision (Шаг 5z escalation, GPT reviews #1+#2):
        * Wetland mask deferred к v1.1 (TD-0038). Methodologically awkward на L3:
          Western Siberia >50% wetland coverage; exclusion would remove majority
          of annulus pixels. Wetlands ARE methane sources — excluding them loses
          signal, не reduces noise.
        * Water mask deferred к v1.1 (TD-0039). Redundant — TROPOMI L3 native QA
          already filters open water via SWIR albedo constraint (qa_value > 0.5
          implies non-water). Edge cases (coastlines, ice transition) могут add
          marginal precision но cost/benefit marginal.

    Args:
        orbit_image: single TROPOMI L3 orbit, post-QA filtering. Must have band
            `target_band`.
        industrial_mask: ee.Image binary (1 = clean, 0 = industrial-buffered),
            полярность ассета proxy_mask_buffered_per_type — see
        annulus_reference: эталон фона, см. ANNULUS_REFERENCES (Algorithm §3.6.2) — see
            Algorithm v3.0+ §3.6.4 для per-source-type buffer construction
            (TD-0027 P-01.0d, RuPlumeScan/industrial/proxy_mask_buffered_per_type).
        target_band: CH₄ band name (default operational).

    Returns:
        ee.Image binary mask, single band 'two_condition_mask'.
        1 = pixel включается в annulus stats; 0 = excluded (industrial OR no
        valid CH₄ retrieval).

    DNA compliance:
        * §2.1.4 unmask(0): NOT used. Mask preserves orbit_image's native NaN
          where retrieval invalid.
        * §2.1.5 ee.Kernel arithmetic: not applicable — no kernel construction.
        * §2.1.6 single absolute threshold: not applicable — binary masks only.
        * §2.1.17 (v2.3) L2-equivalent positioning: not violated.
        * CLAUDE.md §3.2 bestEffort:true: NOT used (no reduceRegion).
    """
    # Condition 1: orbit_image has valid CH4 retrieval (band native mask)
    # .mask() returns 1 где pixel имеет valid value, 0 где masked
    valid_retrieval = orbit_image.select(target_band).mask()

    # Condition 2: состав кольца по эталону. Ассет proxy_mask_buffered_per_type
    # кодирует ЕДИНИЦЕЙ чистый пиксель (`value_1_meaning = "clean"`, строится
    # как industrial.Not()); НУЛЬ — внутри буфера объекта инфраструктуры.
    #   industrial_buffers -> .eq(0): кольцо из промышленных пикселей (опубликованный каталог)
    #   regional_clean     -> .eq(1): кольцо из чистых пикселей
    # История и замеры: docs/FINDING_mask_polarity.md, docs/DECISION_background_reference.md
    if annulus_reference == ANNULUS_REFERENCE_INDUSTRIAL:
        ring_pixels = industrial_mask.eq(0)
    elif annulus_reference == ANNULUS_REFERENCE_CLEAN:
        ring_pixels = industrial_mask.eq(1)
    else:
        raise ValueError(f"annulus_reference: ожидается одно из {ANNULUS_REFERENCES}, получено {annulus_reference!r}")
    non_industrial = ring_pixels

    # Both conditions must be true for inclusion в annulus stats
    return valid_retrieval.And(non_industrial).rename("two_condition_mask")


# ---------------------------------------------------------------------------
# Primitive 3: connectedComponents clustering
# ---------------------------------------------------------------------------


def extract_clusters(
    mask_image: ee.Image,
    min_cluster_px: int = 5,
    max_size: int = 256,
    connectedness: int = 8,
) -> ee.Image:
    """
    Algorithm §3.7: connectedComponents 8-conn (default), min cluster size filter.

    `min_cluster_px=5` ≈ 245 km² minimum signal area at 7 km grid.

    GPT review #1 follow-up (Issue 2.2 — discovered Шаг 5 integration test):
    `connectedComponents` returns multi-band image (input band + 'labels').
    Downstream `reduceToVectors` requires single-band, поэтому explicit
    .select('labels') before returning ensures single-band output.
    """
    # 8-connected = ee.Kernel.square(1); 4-connected = ee.Kernel.plus(1)
    kernel = ee.Kernel.square(1) if connectedness == 8 else ee.Kernel.plus(1)

    labeled = mask_image.connectedComponents(connectedness=kernel, maxSize=max_size)

    # Filter by size
    pixel_counts = mask_image.connectedPixelCount(
        maxSize=max_size, eightConnected=(connectedness == 8)
    )
    significant = pixel_counts.gte(min_cluster_px)

    # Select labels band only — connectedComponents preserves input band, нам нужен только labels
    return labeled.select("labels").updateMask(significant)


# ---------------------------------------------------------------------------
# Primitive 4: per-cluster attributes
# ---------------------------------------------------------------------------


def compute_cluster_attributes(
    cluster_image: ee.Image,
    orbit_image: ee.Image,
    baseline_value: ee.Image,
    z_image: ee.Image,
    aoi: ee.Geometry,
    target_band: str = "CH4_column_volume_mixing_ratio_dry_air_bias_corrected",
    scale_m: int = ANALYSIS_SCALE_M,
) -> ee.FeatureCollection:
    """
    Algorithm §3.8: vectorize clusters + per-cluster reduceRegions для metrics.

    plume_axis_deg НЕ computed here (requires client-side eigendecomposition —
    handled at orchestrator level via reduceRegions(coords) → numpy.linalg.eig).

    Returns FC с per-cluster: cluster_id (geometry implicit), max_z, mean_z,
    max_delta, mean_delta, n_pixels, area_km2, centroid_lon/lat.

    GPT review #1 Issue 2.1 fix: explicit .select('z') / single-band delta
    before reduceRegions; reducers use .setOutputs() for unambiguous property
    naming. Multi-band z_image (output of compute_z_score) would otherwise
    produce band-prefixed property names (z_max etc.) and cluster z-statistics
    would silently come out null.
    """
    # Vectorize clusters
    vectors = cluster_image.reduceToVectors(
        geometry=aoi,
        scale=scale_m,
        geometryType="polygon",
        eightConnected=True,
        bestEffort=False,
        maxPixels=int(1e9),
        labelProperty="cluster_id",
    )

    # Single-band z and delta — avoid band-prefix collision in reduceRegions output
    z_only = z_image.select("z")
    delta_only = orbit_image.select(target_band).subtract(baseline_value)

    # Per-cluster z-score statistics (renamed via setOutputs)
    z_reducer = (
        ee.Reducer.max()
        .setOutputs(["max_z"])
        .combine(ee.Reducer.mean().setOutputs(["mean_z"]), "", True)
        .combine(ee.Reducer.count().setOutputs(["n_pixels"]), "", True)
    )
    with_z = z_only.reduceRegions(
        collection=vectors,
        reducer=z_reducer,
        scale=scale_m,
    )

    # Per-cluster delta statistics
    delta_reducer = (
        ee.Reducer.max()
        .setOutputs(["max_delta"])
        .combine(ee.Reducer.mean().setOutputs(["mean_delta"]), "", True)
    )
    with_delta = delta_only.reduceRegions(
        collection=with_z,
        reducer=delta_reducer,
        scale=scale_m,
    )

    def _enrich_geometric(feat: ee.Feature) -> ee.Feature:
        centroid = feat.geometry().centroid(maxError=1)
        coords = ee.List(centroid.coordinates())
        area_km2 = feat.geometry().area(maxError=1).divide(1e6)
        return feat.set(
            {
                "centroid_lon": coords.get(0),
                "centroid_lat": coords.get(1),
                "area_km2": area_km2,
            }
        )

    return with_delta.map(_enrich_geometric)


# ---------------------------------------------------------------------------
# Primitive 5: wind validation (Algorithm v3.1 §3.9 — ERA5 10m + 850 hPa consistency)
# Шаг 5b2 P-02.0c: switched primary level от 850 hPa к 10m (boundary-layer phenomenon).
# 850 hPa retained as consistency cross-check (not primary).
# ---------------------------------------------------------------------------


def _era5_wind_bands(wind_level: str) -> tuple[str, str]:
    """ERA5 band names for wind level. Supported: '10m', '100m', '850hPa', etc.

    Args:
        wind_level: 'NNm' (height above surface) or 'NNNhPa' (pressure level)

    Returns:
        (u_band_name, v_band_name)
    """
    if not (wind_level.endswith("m") or wind_level.endswith("hPa")):
        raise ValueError(
            f"Invalid wind_level: {wind_level!r}. Use '10m', '100m', '850hPa', etc."
        )
    return f"u_component_of_wind_{wind_level}", f"v_component_of_wind_{wind_level}"


def validate_wind(
    cluster_fc: ee.FeatureCollection,
    era5_collection: ee.ImageCollection,
    orbit_time_millis: int | ee.Date,
    wind_level: str = "10m",
    consistency_check_level: str | None = "850hPa",
    consistency_threshold_deg: float = 45.0,
    alignment_threshold_deg: float = 30.0,
    min_wind_speed_ms: float = 2.0,
    temporal_window_hours: int = 3,
) -> ee.FeatureCollection:
    """
    Algorithm v3.1 §3.9 (Шаг 5b2 P-02.0c): ERA5 wind sampling at cluster centroids,
    primary level 10m + optional 850 hPa consistency cross-check.

    Шаг 5b2 change vs v3.0.x:
        Primary level switched от 850 hPa к 10m. Methane plume transport is a
        boundary-layer phenomenon — surface wind (10m) is more representative
        of plume dispersion direction than free-tropospheric (850 hPa).
        Schneising 2020 + Pandey 2019 use 10m + PBL framework. TD-0031 (set
        850 hPa primary) superseded by this update; TD-0031 marked RESOLVED.

    Consistency cross-check (Finding 2):
        If consistency_check_level is set (default '850hPa'), validate_wind
        also samples that level и compares direction. If |dir_primary -
        dir_check| > consistency_threshold_deg, sets QA flag
        'wind_levels_inconsistent' on the cluster. Soft confidence
        downweight, не hard reject.

    Vector averaging (NOT directional — prevents 359°→0° wrap).
    Alignment via shortest angular distance к 180°-symmetric axis line:
        raw = |wind_dir - axis|, reduced mod 180 → [0, 180)
        angle_diff = min(raw_mod180, 180 - raw_mod180) → [0, 90]

    Three-state wind classification (preserved from v2.3.1 Issue 2.3):
        wind_state ∈ {aligned, misaligned, insufficient_wind, axis_unknown}
        wind_consistent: true if aligned, false if misaligned, null otherwise

    GPT review #1 angle-math fixes preserved:
      * Issue 5.3: .mod(180) before angle_diff min
      * Issue 1.3: wind_dir +360 mod 360 explicit step
      * Issue 5.2: null plume_axis_deg → wind_consistent=null

    Args:
        cluster_fc: FC with plume_axis_deg property pre-set per cluster.
        era5_collection: ee.ImageCollection('ECMWF/ERA5/HOURLY').
        orbit_time_millis: orbit timestamp (millis or ee.Date).
        wind_level: primary wind level string (default '10m'). ERA5 supports:
            '10m', '100m' (height above surface);
            '850hPa', '700hPa', '500hPa', etc. (pressure levels).
        consistency_check_level: optional cross-check level (default '850hPa').
            Set к None to skip consistency check.
        consistency_threshold_deg: |dir_primary - dir_check| above this →
            flag wind_levels_inconsistent (default 45°).
        alignment_threshold_deg: |wind_dir - plume_axis| ≤ this → aligned (default 30°).
        min_wind_speed_ms: speed below this → insufficient_wind (default 2.0).
        temporal_window_hours: ERA5 sampling window ± hours (default 3).

    Sets per-cluster properties:
        wind_u, wind_v               — primary level (default 10m)
        wind_speed                   — primary level
        wind_dir_deg                 — primary level (FROM convention)
        wind_alignment_score         — [0,1] vs plume axis
        wind_consistent              — bool/null
        wind_state                   — enum
        wind_level                   — string label (e.g., '10m')
        wind_source                  — descriptor (e.g., 'ERA5_HOURLY_10m')
        wind_levels_inconsistent_qa  — bool (only if consistency_check_level set)
        wind_consistency_diff_deg    — actual angle difference (only if check)
    """
    band_u_pri, band_v_pri = _era5_wind_bands(wind_level)
    bands_select = [band_u_pri, band_v_pri]

    if consistency_check_level:
        band_u_chk, band_v_chk = _era5_wind_bands(consistency_check_level)
        bands_select += [band_u_chk, band_v_chk]
    else:
        band_u_chk = band_v_chk = None

    orbit_date = ee.Date(orbit_time_millis)
    window = era5_collection.filterDate(
        orbit_date.advance(-temporal_window_hours, "hour"),
        orbit_date.advance(temporal_window_hours, "hour"),
    ).select(bands_select)
    mean_wind = window.mean()  # vector averaging — u, v separately

    def _validate(feat: ee.Feature) -> ee.Feature:
        centroid = feat.geometry().centroid(maxError=1)
        sample = mean_wind.reduceRegion(
            reducer=ee.Reducer.first(),
            geometry=centroid,
            scale=27830,  # ERA5 native ~28 km (0.25° at equator)
        )

        # Primary level (default 10m)
        u_pri = ee.Number(sample.get(band_u_pri))
        v_pri = ee.Number(sample.get(band_v_pri))
        wind_speed = u_pri.hypot(v_pri)

        # Atmospheric FROM convention: 0=N, 90=E.
        # wind_to_deg = atan2(u, v) → [-180, 180]; +360 mod 360 → [0, 360)
        # wind_dir (FROM) = wind_to_deg + 180 mod 360
        wind_to_deg_pri = u_pri.atan2(v_pri).multiply(180.0 / math.pi).add(360).mod(360)
        wind_dir = wind_to_deg_pri.add(180).mod(360)

        # Plume axis null handling
        plume_axis_value = feat.get("plume_axis_deg")
        plume_axis = ee.Number(ee.Algorithms.If(plume_axis_value, plume_axis_value, 0))

        # Shortest angular distance к 180°-symmetric axis (Issue 5.3)
        raw_diff_mod = wind_dir.subtract(plume_axis).abs().mod(180)
        angle_diff = raw_diff_mod.min(ee.Number(180).subtract(raw_diff_mod))

        sufficient_wind = wind_speed.gte(min_wind_speed_ms)
        axis_known = ee.Algorithms.If(plume_axis_value, True, False)

        # Three-state wind classification (Issue 2.3 preserved)
        wind_state = ee.Algorithms.If(
            axis_known,
            ee.Algorithms.If(
                sufficient_wind,
                ee.Algorithms.If(
                    angle_diff.lte(alignment_threshold_deg),
                    "aligned",
                    "misaligned",
                ),
                "insufficient_wind",
            ),
            "axis_unknown",
        )

        ok_to_check = ee.Algorithms.If(axis_known, sufficient_wind, False)
        wind_consistent = ee.Algorithms.If(
            ok_to_check,
            angle_diff.lte(alignment_threshold_deg),
            None,
        )

        alignment_score = ee.Number(1).subtract(angle_diff.divide(90).min(1))

        props = {
            "wind_u": u_pri,
            "wind_v": v_pri,
            "wind_speed": wind_speed,
            "wind_dir_deg": wind_dir,
            "wind_alignment_score": alignment_score,
            "wind_consistent": wind_consistent,
            "wind_state": wind_state,
            "wind_level": wind_level,
            "wind_source": f"ERA5_HOURLY_{wind_level}",
        }

        # Consistency cross-check (Finding 2)
        if consistency_check_level:
            u_chk = ee.Number(sample.get(band_u_chk))
            v_chk = ee.Number(sample.get(band_v_chk))
            wind_to_deg_chk = u_chk.atan2(v_chk).multiply(180.0 / math.pi).add(360).mod(360)
            wind_dir_chk = wind_to_deg_chk.add(180).mod(360)

            # Angular difference (shortest path mod 180)
            raw_consistency = wind_dir.subtract(wind_dir_chk).abs().mod(360)
            consistency_diff = raw_consistency.min(
                ee.Number(360).subtract(raw_consistency)
            )

            inconsistent = consistency_diff.gt(consistency_threshold_deg)

            props.update({
                "wind_levels_inconsistent_qa": inconsistent,
                "wind_consistency_diff_deg": consistency_diff,
                f"wind_u_{consistency_check_level}": u_chk,
                f"wind_v_{consistency_check_level}": v_chk,
            })

        return feat.set(props)

    return cluster_fc.map(_validate)


# ---------------------------------------------------------------------------
# Primitive 6: source attribution (50 km radius + type ranking)
# ---------------------------------------------------------------------------


def filter_candidates_to_buffers(
    cluster_fc: ee.FeatureCollection,
    industrial_mask: ee.Image,
    scale_m: float = 5500.0,
) -> ee.FeatureCollection:
    """Algorithm v3.2.0 §3.6.6: оставить кандидатов внутри промышленных буферов.

    До v3.2.0 это ограничение возникало побочным эффектом: маска кольца
    одновременно маскировала выход `compute_z_local`, поэтому z существовала
    только внутри буферов. После приведения маски к её назначению (ограничивать
    выборку кольца, но не отбор кандидатов) ограничение нужно задавать явно —
    так, как оно и описано в §3.6.6 и в статье: событие принимается, если его
    центроид лежит в буферной зоне объекта инфраструктуры.

    Args:
        cluster_fc: коллекция кандидатов с геометрией
        industrial_mask: ассет proxy_mask_buffered_per_type (1 = чисто,
            0 = внутри буфера промышленного объекта)
        scale_m: масштаб опроса маски

    Returns:
        подмножество cluster_fc с признаком `inside_industrial_buffer` = 1
    """
    def _flag(feat: ee.Feature) -> ee.Feature:
        centroid = feat.geometry().centroid(maxError=1)
        val = industrial_mask.reduceRegion(
            reducer=ee.Reducer.first(), geometry=centroid, scale=scale_m
        ).values().get(0)
        # Ноль в маске означает «внутри буфера», поэтому проверять val на
        # истинность нельзя: ee.Algorithms.If(0, ...) уходит в ложную ветку.
        # Сравниваем с None явно; вне покрытия ассета кандидат не принимается.
        inside = ee.Algorithms.If(
            ee.Algorithms.IsEqual(val, None), 0, ee.Number(val).eq(0))
        return feat.set("inside_industrial_buffer", ee.Number(inside))

    return cluster_fc.map(_flag).filter(ee.Filter.eq("inside_industrial_buffer", 1))


def attribute_source(
    cluster_fc: ee.FeatureCollection,
    source_points: ee.FeatureCollection,
    search_radius_km: float = 50.0,
    type_priorities: dict[str, int] | None = None,
) -> ee.FeatureCollection:
    """
    Algorithm §3.10: nearest source within search_radius, ranked by type priority.

    Priority lower = better (gas_field=1 wins over viirs_flare_high=2).
    Ties broken by distance.

    Sets nearest_source_id, nearest_source_distance_km, nearest_source_type.
    If no source within radius → all three null.

    GPT review #1 Issue 6.1 fix: composite-key sort (priority * 1e6 + distance)
    instead of double .sort() — single allocation, avoids stable-sort assumption,
    reduces inner-map memory pressure.
    """
    priorities_dict = type_priorities or SOURCE_TYPE_PRIORITIES_CH4
    priorities = ee.Dictionary(priorities_dict)
    default_priority = 999

    def _attribute(cluster: ee.Feature) -> ee.Feature:
        centroid = cluster.geometry().centroid(maxError=1)
        nearby = source_points.filterBounds(centroid.buffer(search_radius_km * 1000))

        def _rank(source: ee.Feature) -> ee.Feature:
            distance = centroid.distance(source.geometry()).divide(1000)  # km
            stype = source.get("source_type_category")
            priority = ee.Number(priorities.get(stype, default_priority))
            # Composite rank: priority dominant (× 1e6), distance breaks ties
            composite = priority.multiply(1_000_000).add(distance)
            return source.set(
                {
                    "distance_km": distance,
                    "priority": priority,
                    "composite_rank": composite,
                }
            )

        ranked = nearby.map(_rank).sort("composite_rank")  # single sort

        size = ranked.size()
        return ee.Feature(
            ee.Algorithms.If(
                size.gt(0),
                cluster.set(
                    {
                        "nearest_source_id": ee.Feature(ranked.first()).get("source_id"),
                        "nearest_source_distance_km": ee.Feature(ranked.first()).get("distance_km"),
                        "nearest_source_type": ee.Feature(ranked.first()).get(
                            "source_type_category"
                        ),
                    }
                ),
                cluster.set(
                    {
                        "nearest_source_id": None,
                        "nearest_source_distance_km": None,
                        "nearest_source_type": None,
                    }
                ),
            )
        )

    return cluster_fc.map(_attribute)


# ---------------------------------------------------------------------------
# Helper: client-side plume axis via eigendecomposition
# ---------------------------------------------------------------------------


def compute_plume_axis_client_side(
    pixel_lons: list[float], pixel_lats: list[float]
) -> float | None:
    """
    Compute plume axis bearing (compass; 0=N, 90=E; range [0, 180)) via 2D PCA
    on cluster pixel coordinates.

    Client-side post-reduceRegion (researcher decision Шаг 4): server-side
    `ee.Array.eigen` exists но fragile — sample pixel coords through reduceRegion,
    do numpy.linalg.eigh locally.

    GPT review #1 Issue 1.2 fix: cos(lat) aspect correction. At 54°N,
    1° lon ≈ 65 km vs 1° lat ≈ 111 km (cos 54° ≈ 0.588). Without correction PCA
    on raw degrees would over-weight latitudinal extent ~1.7× and bias E-W
    elongated clusters toward N-S axis, corrupting wind alignment validation.
    Correction: scale lons by cos(mean_lat) before covariance, recover bearing
    from km-space eigenvector.

    Returns None если < 3 pixels (eigendecomposition undefined).
    """
    if len(pixel_lons) < 3 or len(pixel_lats) < 3:
        return None

    lons = np.array(pixel_lons, dtype=float)
    lats = np.array(pixel_lats, dtype=float)

    # Aspect correction: scale lons to km-equivalent at cluster mean latitude
    mean_lat = float(np.mean(lats))
    cos_lat = math.cos(math.radians(mean_lat))
    if cos_lat < 1e-6:  # at poles, axis ill-defined
        return None
    lons_scaled = (lons - lons.mean()) * cos_lat
    lats_centered = lats - lats.mean()

    coords = np.column_stack([lons_scaled, lats_centered])  # km-space (relative)
    cov = np.cov(coords.T)
    eigvals, eigvecs = np.linalg.eigh(cov)
    dominant = eigvecs[:, np.argmax(eigvals)]

    # In km-space, bearing = atan2(east_km, north_km) (compass: 0=N, 90=E)
    angle = float(np.degrees(np.arctan2(dominant[0], dominant[1])))
    # Normalize to [0, 180) — axis is symmetric
    return angle % 180


# ---------------------------------------------------------------------------
# Path E primitive (Algorithm v3.0 §3.5 — latitude-band correction)
# Шаг 3 P-02.0c. Server-side EE + pure-numpy helper для unit tests.
# ---------------------------------------------------------------------------

# Latitude-band correction defaults (Algorithm v3.0 §3.5.2)
BAND_WIDTH_DEG_DEFAULT = 0.5  # ±0.5° latitude band granularity
TEMPORAL_WINDOW_DAYS_DEFAULT = 7  # ±7 days temporal window для pixel-temporal median
BAND_STD_THRESHOLD_PPB_DEFAULT = 10.0  # band-temporal-std threshold для partial flag

# CH4 noise floor (consistent с Algorithm §3.5 sigma_floor)
CH4_DEVIATION_THRESHOLD_PPB = 15.0


def apply_latitude_band_correction_numpy(
    orbit_values: np.ndarray,
    pixel_temporal_medians: np.ndarray,
    lats: np.ndarray,
    band_width_deg: float = BAND_WIDTH_DEG_DEFAULT,
    band_std_threshold_ppb: float = BAND_STD_THRESHOLD_PPB_DEFAULT,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Algorithm v3.0 §3.5: per-pixel persistent-bias removal (numpy core).

    Pure-numpy version — testable без EE Initialize. Server-side EE wrapper
    `apply_latitude_band_correction` mirrors эту логику над ee.Image.

    Algorithm:
      1. Bin pixels по int(lat / band_width_deg)
      2. Per band: band_typical = median(pixel_temporal_medians в band)
      3. Per pixel: persistent_dev = pixel_temporal_median - band_typical
      4. corrected = orbit_value - persistent_dev

    Эффект:
      * Normal pixel:  pixel_temporal ≈ band_typical → persistent_dev ≈ 0 → no change
      * Stripe pixel (persistent over ±7 days):  pixel_temporal carries +stripe →
        persistent_dev = +stripe → corrected ≈ baseline ✓
      * Transient plume:  pixel_temporal ≈ baseline (plume not in temporal window) →
        persistent_dev ≈ 0 → orbit value preserved (plume retained) ✓

    Failure mode (lat_band_correction_partial flag):
      Set когда band_temporal_std > band_std_threshold_ppb. High band-temporal
      std сигнализирует bimodal/multimodal contamination (e.g., stripe filling
      >50% of band) — correction unreliable, flag downstream.

    Args:
        orbit_values: shape (H, W) — current orbit XCH4 (NaN preserved as masked)
        pixel_temporal_medians: shape (H, W) — per-pixel ±N-day median
            (precomputed). NaN allowed (no correction applied к pixels с NaN
            temporal_median).
        lats: shape (H, W) — pixel latitudes (degrees)
        band_width_deg: latitude band granularity (default 0.5°)
        band_std_threshold_ppb: band-temporal std threshold для partial flag

    Returns:
        corrected: shape (H, W) — orbit_values - persistent_dev. NaN preserved.
            Pixels с NaN temporal_median → corrected = orbit (no change).
        partial_flag: shape (H, W), int — 1 где band_temporal_std > threshold,
            else 0. NaN-masked orbit pixels still get flag value (для downstream
            classification — pixel value masked, но flag informs).

    DNA §2.1.4 compliance: NaN preserved through correction (no unmask(0)).
    """
    if orbit_values.shape != pixel_temporal_medians.shape:
        raise ValueError(
            f"shape mismatch: orbit {orbit_values.shape} vs temporal "
            f"{pixel_temporal_medians.shape}"
        )
    if orbit_values.shape != lats.shape:
        raise ValueError(
            f"shape mismatch: orbit {orbit_values.shape} vs lats {lats.shape}"
        )

    flat_orbit = orbit_values.flatten().astype(np.float64)
    flat_temporal = pixel_temporal_medians.flatten().astype(np.float64)
    flat_lats = lats.flatten()

    # Valid для band-statistics: orbit AND temporal both not NaN
    valid_for_stats = ~np.isnan(flat_orbit) & ~np.isnan(flat_temporal)
    # Valid для correction: temporal not NaN (orbit can be anything; correction
    # subtracts persistent_dev — NaN orbit stays NaN после subtraction)
    valid_for_correction = ~np.isnan(flat_temporal)

    corrected = flat_orbit.copy()
    partial = np.zeros(flat_orbit.shape, dtype=int)

    if not valid_for_stats.any():
        return corrected.reshape(orbit_values.shape), partial.reshape(orbit_values.shape)

    band_ids = np.floor(flat_lats / band_width_deg).astype(int)

    for band_id in np.unique(band_ids[valid_for_stats]):
        in_band_stats = (band_ids == band_id) & valid_for_stats
        if in_band_stats.sum() < 3:
            # Too few valid pixels — skip correction для band
            continue

        band_temps = flat_temporal[in_band_stats]
        band_typical = float(np.median(band_temps))
        band_std = float(np.std(band_temps))

        # Apply correction to ALL pixels в band с valid temporal_median
        in_band_correct = (band_ids == band_id) & valid_for_correction
        persistent_dev = flat_temporal[in_band_correct] - band_typical
        corrected[in_band_correct] = flat_orbit[in_band_correct] - persistent_dev

        # Failure mode: bimodal/multimodal contamination
        if band_std > band_std_threshold_ppb:
            in_band_any = band_ids == band_id
            partial[in_band_any] = 1

    return corrected.reshape(orbit_values.shape), partial.reshape(orbit_values.shape)


def apply_latitude_band_correction(
    orbit_image: ee.Image,
    aoi: ee.Geometry,
    band_width_deg: float = BAND_WIDTH_DEG_DEFAULT,
    temporal_window_days: int = TEMPORAL_WINDOW_DAYS_DEFAULT,
    band_std_threshold_ppb: float = BAND_STD_THRESHOLD_PPB_DEFAULT,
    target_band: str = "CH4_column_volume_mixing_ratio_dry_air_bias_corrected",
    pixel_size_m: float = ANALYSIS_SCALE_M,
    collection_id: str = "COPERNICUS/S5P/OFFL/L3_CH4",
) -> ee.Image:
    """
    Algorithm v3.0 §3.5: per-orbit latitude-band correction (server-side EE).

    Server-side wrapper над `apply_latitude_band_correction_numpy` логикой,
    реализованной через EE primitives. Unit-tested через pure-numpy helper;
    integration tested через real Export task в Шаге 6 single-year regression.

    Pipeline:
      1. orbit_date ← orbit_image['system:time_start']
      2. temporal_collection ← TROPOMI L3 в [orbit_date ± N days] над AOI
      3. pixel_temporal_median ← temporal_collection.median() (per-pixel ±N-day)
      4. band_id image ← floor(lat / band_width_deg)
      5. Per-band stats: median + std reduceRegion с group(band_id)
      6. Remap band_id → band_typical, band_std (per-band lookup tables)
      7. persistent_dev ← pixel_temporal_median - band_typical_image
      8. corrected ← orbit_value - persistent_dev (DNA §2.1.4 — NaN preserved
         through subtract; no unmask(0))
      9. partial_flag ← band_std_image > threshold

    Returns ee.Image с двумя bands:
      * '{target_band}_lat_corrected' — orbit_value - persistent_dev
      * 'lat_band_correction_partial' — bool flag, 1 в bands с std > threshold

    Args:
        orbit_image: single TROPOMI orbit, post-QA. Must have system:time_start.
        aoi: ee.Geometry для masking band-stats reduction
        band_width_deg: ±0.5° default (Algorithm §3.5.2)
        temporal_window_days: ±7 days default
        band_std_threshold_ppb: 10.0 ppb default — partial flag trigger
        target_band: CH4 band name (default operational)
        pixel_size_m: reduction scale (default ANALYSIS_SCALE_M = 7000)
        collection_id: TROPOMI L3 source (parameterized для test injection)

    DNA compliance:
      * §2.1.4 unmask(0): not used. Subtract operates on masked orbit_image —
        NaN-masked pixels stay NaN.
      * §2.1.5 ee.Kernel arithmetic: not used. Correction is pixel-additive.
      * §2.1.6 single absolute threshold: not applicable — correction is
        background-relative (band_typical varies per band).
      * CLAUDE.md §3.2 bestEffort: not used in reduceRegion.
    """
    orbit_date = ee.Date(orbit_image.get("system:time_start"))

    # Step 1: temporal-window collection
    temporal_collection = (
        ee.ImageCollection(collection_id)
        .select(target_band)
        .filterDate(
            orbit_date.advance(-temporal_window_days, "day"),
            orbit_date.advance(temporal_window_days + 1, "day"),
        )
        .filterBounds(aoi)
    )

    # Bug #3 fix (Шаг 6b1 P-02.0c): empty temporal collection (low-orbit months
    # like M10 polar) → median() returns 0-band image → downstream Image.gt
    # errors с "0 vs 1 bands". Server-side fallback к orbit_image itself,
    # ensuring pixel_temporal_median always has 1 band. When fallback used,
    # persistent_dev ≈ 0 (orbit - orbit), correction degrades к no-op gracefully.
    pixel_temporal_median = ee.Image(
        ee.Algorithms.If(
            temporal_collection.size().gt(0),
            temporal_collection.median().clip(aoi),
            orbit_image.select(target_band),  # fallback: no correction available
        )
    )

    # Step 2: latitude band ID image
    lat_image = ee.Image.pixelLonLat().select("latitude").clip(aoi)
    band_id = lat_image.divide(band_width_deg).floor().rename("band_id")

    # Step 3: per-band stats (median + std) via grouped reducer
    stats_image = pixel_temporal_median.rename("temporal_value").addBands(band_id)

    grouped = stats_image.reduceRegion(
        reducer=(
            ee.Reducer.median()
            .combine(reducer2=ee.Reducer.stdDev(), sharedInputs=True)
            .group(groupField=1, groupName="band_id")
        ),
        geometry=aoi,
        scale=pixel_size_m,
        maxPixels=int(1e10),
    )

    # Defensive: grouped.get("groups") may be null если AOI пусто; ee.List wrap handles
    groups = ee.List(ee.Algorithms.If(grouped.get("groups"), grouped.get("groups"), []))

    # Extract parallel lists для remap.
    # Bug fix (Шаг 6b1 P-02.0c): grouped reducer dict schema может miss stdDev key
    # для groups с insufficient samples (n < 2). Defensive ee.Algorithms.If guards
    # against missing keys. partial_flag may degrade к no-op for sparse months,
    # но main correction (median-based) still works.
    def _safe_get(d, key, default):
        d_dict = ee.Dictionary(d)
        return ee.Number(
            ee.Algorithms.If(
                d_dict.keys().contains(key),
                d_dict.get(key),
                default,
            )
        )

    band_ids_list = groups.map(lambda d: _safe_get(d, "band_id", -9999))
    band_typicals_list = groups.map(lambda d: _safe_get(d, "median", 0))
    band_stds_list = groups.map(lambda d: _safe_get(d, "stdDev", 0))

    # Step 4: remap band_id image к band_typical + band_std.
    # Bug #3 fix: defaultValue ensures single-band output even с empty from_/to lists
    # (sparse months — empty groups). Without defaultValue, remap may return 0-band
    # image, breaking downstream .gt() с "0 vs 1 bands" error.
    band_typical_image = band_id.remap(
        from_=band_ids_list,
        to=band_typicals_list,
        defaultValue=0,
    ).rename("band_typical")
    band_std_image = band_id.remap(
        from_=band_ids_list,
        to=band_stds_list,
        defaultValue=0,
    ).rename("band_std")

    # Step 5: persistent_dev = pixel_temporal - band_typical
    persistent_dev = pixel_temporal_median.subtract(band_typical_image).rename(
        "persistent_dev"
    )

    # Step 6: corrected = orbit_value - persistent_dev
    corrected = (
        orbit_image.select(target_band)
        .subtract(persistent_dev)
        .rename(f"{target_band}_lat_corrected")
    )

    # Step 7: partial_flag = band_std > threshold
    partial_flag = band_std_image.gt(band_std_threshold_ppb).rename(
        "lat_band_correction_partial"
    )

    return corrected.addBands(partial_flag)


# ---------------------------------------------------------------------------
# Path E primitive (Algorithm v3.0 §3.4 — per-orbit local annulus Z-score)
# Шаг 4a P-02.0c. Server-side EE + pure-numpy helpers для unit tests.
# Replaces v2.x build_hybrid_background + compute_z_score (multi-year baseline).
# ---------------------------------------------------------------------------

# Annulus kernel defaults (Algorithm v3.0.1 §3.4.2)
TROPOMI_L3_PIXEL_SIZE_KM = 5.5  # nominal L3 grid pixel size


def build_annulus_weights_numpy(
    inner_km: float = ANNULUS_INNER_KM_DEFAULT,
    outer_km: float = ANNULUS_OUTER_KM_DEFAULT,
    pixel_size_km: float = TROPOMI_L3_PIXEL_SIZE_KM,
) -> np.ndarray:
    """
    Pure-numpy weight matrix construction для annulus kernel (testable без EE).

    Кольцо: pixels с distance from center в [inner_km, outer_km] получают
    weight=1; outside annulus или в inner exclusion — weight=0. Нормировано
    к sum=1.

    Args:
        inner_km: радиус внутреннего exclusion (default 50 km)
        outer_km: радиус внешнего capture (default 150 km)
        pixel_size_km: L3 grid pixel size (default 5.5 km — TROPOMI nominal)

    Returns:
        np.ndarray (size_px, size_px), normalized weights
            где size_px = 2 * ceil(outer_km / pixel_size_km) + 1
    """
    if inner_km >= outer_km:
        raise ValueError(
            f"inner_km ({inner_km}) must be < outer_km ({outer_km})"
        )
    if pixel_size_km <= 0:
        raise ValueError(f"pixel_size_km must be > 0, got {pixel_size_km}")

    half_extent_px = math.ceil(outer_km / pixel_size_km)
    size_px = 2 * half_extent_px + 1
    weights = np.zeros((size_px, size_px), dtype=np.float64)

    for i in range(size_px):
        for j in range(size_px):
            dy_km = (i - half_extent_px) * pixel_size_km
            dx_km = (j - half_extent_px) * pixel_size_km
            r_km = math.sqrt(dx_km ** 2 + dy_km ** 2)
            if inner_km <= r_km <= outer_km:
                weights[i, j] = 1.0

    s = weights.sum()
    if s == 0:
        raise ValueError(
            f"Empty annulus — inner={inner_km}, outer={outer_km}, "
            f"px={pixel_size_km}. Check defaults."
        )

    return weights / s


def build_annulus_kernel(
    inner_km: float = ANNULUS_INNER_KM_DEFAULT,
    outer_km: float = ANNULUS_OUTER_KM_DEFAULT,
    pixel_size_km: float = TROPOMI_L3_PIXEL_SIZE_KM,
) -> ee.Kernel:
    """
    Algorithm v3.0.1 §3.4.2: annulus kernel via `ee.Kernel.fixed` (DNA §2.1.5).

    DNA §2.1.5 prohibits arithmetic over `ee.Kernel` objects. Annulus
    constructed как single fixed-weight kernel — explicit weight matrix
    via `build_annulus_weights_numpy`, wrapped в `ee.Kernel.fixed`.

    Args:
        inner_km: inner exclusion radius (default 50 km — 3× typical plume radius)
        outer_km: outer capture radius (default 150 km — < synoptic-scale)
        pixel_size_km: L3 grid pixel (default 5.5 km — TROPOMI nominal)

    Returns:
        ee.Kernel.fixed instance, готовый к reduceNeighborhood (normalized weights — для mean/median/MAD).
        For raw count operations use `build_annulus_count_kernel` instead.
    """
    weights = build_annulus_weights_numpy(inner_km, outer_km, pixel_size_km)
    half_extent_px = weights.shape[0] // 2
    return ee.Kernel.fixed(
        width=weights.shape[1],
        height=weights.shape[0],
        weights=weights.tolist(),
        x=half_extent_px,
        y=half_extent_px,
        normalize=False,  # already normalized в build_annulus_weights_numpy
    )


def build_annulus_count_kernel(
    inner_km: float = ANNULUS_INNER_KM_DEFAULT,
    outer_km: float = ANNULUS_OUTER_KM_DEFAULT,
    pixel_size_km: float = TROPOMI_L3_PIXEL_SIZE_KM,
) -> ee.Kernel:
    """
    Binary 0/1 annulus kernel для raw count operations (Шаг 6b1 P-02.0c bug fix).

    Counterpart к `build_annulus_kernel` (normalized weights). Used inside
    `compute_z_local` для `sample_count` band — `reduceNeighborhood(Reducer.sum)`
    с binary kernel returns raw integer count of valid pixels в annulus.

    Bug context: original implementation used normalized annulus_kernel для both
    weighted operations (mean/median/MAD) AND count. Since weights sum к 1,
    `sum(mask × weights) = fraction in [0, 1]`, не raw count. `min_annulus_count=50`
    impossible to satisfy → all Z values masked silently → 0 clusters.

    Args:
        inner_km / outer_km / pixel_size_km: same defaults as build_annulus_kernel

    Returns:
        ee.Kernel.fixed instance с binary 0/1 weights, готов к reduceNeighborhood
        для raw count.
    """
    weights_normalized = build_annulus_weights_numpy(inner_km, outer_km, pixel_size_km)
    binary_weights = (weights_normalized > 0).astype(np.float64)
    half_extent_px = binary_weights.shape[0] // 2
    return ee.Kernel.fixed(
        width=binary_weights.shape[1],
        height=binary_weights.shape[0],
        weights=binary_weights.tolist(),
        x=half_extent_px,
        y=half_extent_px,
        normalize=False,
    )


# Path E robust statistics constants (Algorithm v3.0.4 §3.4.3, Шаг 5b1 P-02.0c)
MAD_TO_SIGMA_GAUSSIAN = 1.4826  # consistent estimator: σ = 1.4826 × MAD for Gaussian
ANNULUS_REPROJECT_CRS_DEFAULT = "EPSG:6931"  # NSIDC EASE-Grid 2.0 N (LAEA, equal-area)
MIN_ANNULUS_COUNT_DEFAULT = 50  # min valid samples в annulus для Z computation


def compute_z_local_numpy(
    orbit_values: np.ndarray,
    proxy_mask: np.ndarray,
    annulus_weights: np.ndarray,
    min_annulus_count: int = MIN_ANNULUS_COUNT_DEFAULT,
    annulus_only: bool = False,
) -> np.ndarray:
    """
    Pure-numpy compute_z_local — testable без EE Initialize.

    Algorithm v3.0.4 §3.4.3 (Шаг 5b1 robust statistics refactor):
        median_a = median(orbit[i] : i ∈ annulus, valid)
        MAD_a    = median(|orbit[i] - median_a|)
        σ_robust = 1.4826 × MAD_a   (consistent estimator для Gaussian)
        Z(x)     = (orbit[x] - median_a) / σ_robust

    skipMasked=True semantic: pixels с proxy_mask=False OR NaN orbit value
    excluded from annulus stats. Target pixel orbit value used regardless
    of its own mask status.

    Min annulus count: pixels с < min_annulus_count valid samples в annulus
    → Z=NaN (insufficient support to estimate baseline).

    Args:
        orbit_values: shape (H, W) — orbit XCH4 (NaN allowed для masked pixels)
        proxy_mask: shape (H, W) — True где pixel включается в annulus stats
            (industrial masked → False)
        annulus_weights: shape (K, K) — kernel weights from
            build_annulus_weights_numpy. K = 2 * half_extent + 1
        min_annulus_count: minimum valid samples в annulus для Z computation
            (default 50). Pixels с insufficient support → NaN

    Returns:
        z: shape (H, W) — per-pixel Z_local. NaN где:
          * sample count < min_annulus_count
          * MAD == 0 (uniform annulus, Z undefined)
          * orbit pixel is NaN

    Implementation: per-pixel iterate over annulus offsets; collect valid
    samples; np.median on samples for median, MAD. Slower than convolve-based
    mean/std but median is non-linear (cannot be computed via convolution).
    Acceptable для unit tests; production runs server-side EE wrapper.

    Replaces (Шаг 5b1): convolve-based mean/std → samples-based median/MAD.
    Robust к heavy-tailed background, less sensitive к heteroscedasticity
    в mixed land-cover annuli (per GPT review #1+#2 recommendations).
    """
    if orbit_values.shape != proxy_mask.shape:
        raise ValueError(
            f"shape mismatch: orbit {orbit_values.shape} vs mask {proxy_mask.shape}"
        )

    H, W = orbit_values.shape
    K = annulus_weights.shape[0]
    half = K // 2

    # Pre-extract annulus offsets (cells where weight > 0)
    annulus_offsets = []
    for ky in range(K):
        for kx in range(K):
            if annulus_weights[ky, kx] > 0:
                annulus_offsets.append((ky - half, kx - half))

    valid_mask_2d = ~np.isnan(orbit_values) & proxy_mask.astype(bool)
    z = np.full((H, W), np.nan, dtype=np.float64)

    for i in range(H):
        for j in range(W):
            if not annulus_only and not proxy_mask[i, j]:
                continue  # опубликованная семантика: центр обязан быть в proxy_mask
            if np.isnan(orbit_values[i, j]):
                continue

            # Collect valid annulus samples
            samples = []
            for dy, dx in annulus_offsets:
                yi, xi = i + dy, j + dx
                if 0 <= yi < H and 0 <= xi < W and valid_mask_2d[yi, xi]:
                    samples.append(orbit_values[yi, xi])

            n = len(samples)
            if n < min_annulus_count:
                continue  # insufficient annulus support → Z=NaN

            samples_arr = np.asarray(samples, dtype=np.float64)
            median_a = np.median(samples_arr)
            mad_a = np.median(np.abs(samples_arr - median_a))
            sigma_robust = MAD_TO_SIGMA_GAUSSIAN * mad_a

            if sigma_robust > 0:
                z[i, j] = (orbit_values[i, j] - median_a) / sigma_robust

    return z


def compute_z_local(
    orbit_image: ee.Image,
    annulus_kernel: ee.Kernel,
    proxy_mask: ee.Image,
    target_band: str = "CH4_column_volume_mixing_ratio_dry_air_bias_corrected",
    reproject_crs: str = ANNULUS_REPROJECT_CRS_DEFAULT,
    reproject_scale_m: float = 5500.0,
    min_annulus_count: int = MIN_ANNULUS_COUNT_DEFAULT,
    annulus_count_kernel: ee.Kernel | None = None,
    annulus_only: bool = False,
    mad_floor_ppb: float = 0.0,
) -> ee.Image:
    """
    Algorithm v3.0.4 §3.4.3: per-orbit local annulus Z-score (server-side EE).

    Per-orbit, no historical baseline dependency. Replaces v2.x
    `compute_z_score(orbit, hybrid_background, month)` (multi-year baseline,
    removed в Шаге 4a).

        Z_local(x) = (orbit(x) - median_annulus(x)) / (1.4826 × MAD_annulus(x))

    Robust statistics (median + MAD) replace mean/std from Шаг 4a (GPT review
    #1+#2 recommendation Finding R1):
      * Less sensitive к heavy-tailed retrieval noise distribution
      * Robust к partial annulus contamination from un-masked source pixels
      * Reduces heteroscedasticity в mixed land-cover annuli

    GEODESIC FIX (Шаг 5b1, Finding 1 P0):
        TROPOMI L3 native projection EPSG:4326 (0.01° pixel grid). Without
        explicit `.reproject(crs="EPSG:6931", scale=5500)`, ee.Kernel.fixed
        cells operate on native pixel grid (~1.1 km lat, 0.3-0.7 km lon
        depending on latitude) — annulus would be ~5× too small in lat
        AND latitude-asymmetric (2.48× E-W между 50°N и 75°N). EPSG:6931 =
        NSIDC EASE-Grid 2.0 N Lambert Azimuthal Equal Area, optimal для
        high-latitude AOI. См. Шаг 5z probe (commit `05d425f`).

    Min annulus count (Finding R3 — directional bias guard):
        Pixels с < min_annulus_count valid samples в annulus → Z masked.
        Default 50 pixels. Insufficient support indicates either edge effects,
        heavy mask contamination, или low-coverage orbit segment.

    Args:
        orbit_image: single TROPOMI orbit, post-QA + post-§3.5 latitude-band
            correction (recommended). Must have band `target_band`.
        annulus_kernel: from `build_annulus_kernel()` — DNA §2.1.5 compliant
            ee.Kernel.fixed.
        proxy_mask: ee.Image binary (1 where pixel included в annulus stats,
            0 where excluded — industrial mask). See §3.6 apply_two_condition_mask.
        target_band: CH4 band name (default operational).
        reproject_crs: EE-accepted equal-area CRS (default EPSG:6931 NSIDC
            EASE-Grid 2.0 N — verified в Шаг 5z probe). Override only если
            specific projection requirement.
        reproject_scale_m: target scale в meters (default 5500.0 — matches
            annulus_kernel pixel_size_km × 1000 = TROPOMI L3 nominal grid).
        min_annulus_count: min valid samples в annulus для Z computation
            (default 50).

    Returns:
        ee.Image с четырьмя bands:
          * 'Z_local'                       — robust z-score (median/MAD-based;
                                              masked где insufficient samples
                                              OR MAD==0)
          * '{target_band}_median_local'    — annulus median (debugging)
          * '{target_band}_mad_local'       — annulus MAD (debugging)
          * '{target_band}_n_local'         — annulus sample count (validity)

    DNA compliance:
      * §2.1.4 unmask(0): NOT used. updateMask + subtract preserve NaN.
      * §2.1.5 ee.Kernel arithmetic: NOT used. Single ee.Kernel.fixed annulus.
      * §2.1.6 single absolute threshold: not applicable — Z is anomaly metric.
      * §2.1.17 (v2.3) L2-equivalent positioning: not violated (per-orbit L3).
    """
    # GEODESIC FIX: reproject orbit + mask к equal-area CRS at 5500m scale
    # Без этого ee.Kernel.fixed cells = native EPSG:4326 0.01° offsets,
    # annulus ~5× too small + latitude-asymmetric
    masked_orbit = orbit_image.updateMask(proxy_mask).reproject(
        crs=reproject_crs, scale=reproject_scale_m
    )
    target_reprojected = orbit_image.select(target_band).reproject(
        crs=reproject_crs, scale=reproject_scale_m
    )

    # Robust statistics: median + MAD
    median_annulus = (
        masked_orbit.select(target_band)
        .reduceNeighborhood(
            reducer=ee.Reducer.median(),
            kernel=annulus_kernel,
            # annulus_only=False (опубликованный каталог): выход маскируется там,
            # где центральный пиксель вне proxy_mask — маска ограничивает и кольцо,
            # и кандидатов. annulus_only=True: маска ограничивает только выборку
            # кольца, z считается везде (Algorithm §3.6.2, docs/DECISION_background_reference.md)
            skipMasked=not annulus_only,
        )
        .rename(f"{target_band}_median_local")
    )

    # MAD: median(|values - median|)
    abs_dev = masked_orbit.select(target_band).subtract(median_annulus).abs()
    mad_annulus = (
        abs_dev.reduceNeighborhood(
            reducer=ee.Reducer.median(),
            kernel=annulus_kernel,
            skipMasked=not annulus_only,  # см. комментарий у median_annulus
        )
        .rename(f"{target_band}_mad_local")
    )
    # σ_robust = 1.4826 × MAD (consistent estimator для Gaussian)
    # Нижняя граница MAD: вырожденное кольцо (MAD -> 0) даёт z в тысячах
    # (2 из 1064 испытаний над заповедниками, step8f). 0.0 = без ограничения,
    # ровно как в опубликованном каталоге
    mad_for_sigma = mad_annulus.max(mad_floor_ppb) if mad_floor_ppb > 0 else mad_annulus
    sigma_robust = mad_for_sigma.multiply(MAD_TO_SIGMA_GAUSSIAN)

    # Annulus sample count для validity check.
    # Шаг 6b1 P-02.0c bug fix: must use BINARY 0/1 annulus kernel для raw count.
    # Normalized annulus_kernel (sum к 1) gives fraction (0-1), не raw count.
    # If annulus_count_kernel not provided, fallback к use main kernel — но
    # caller must provide для correct min_annulus_count semantics.
    count_kernel = annulus_count_kernel if annulus_count_kernel is not None else annulus_kernel
    sample_count = (
        masked_orbit.select(target_band)
        .mask()
        .reduceNeighborhood(
            reducer=ee.Reducer.sum(),
            kernel=count_kernel,
            skipMasked=False,  # count needs full kernel evaluation
        )
        .rename(f"{target_band}_n_local")
    )

    # Z = (orbit - median) / σ_robust
    z_raw = (
        target_reprojected.subtract(median_annulus)
        .divide(sigma_robust)
        .rename("Z_local")
    )

    # Mask Z where insufficient annulus support
    valid_annulus = sample_count.gte(min_annulus_count)
    z = z_raw.updateMask(valid_annulus)

    return z.addBands(median_annulus).addBands(mad_annulus).addBands(sample_count)


# ---------------------------------------------------------------------------
# Module exports
# ---------------------------------------------------------------------------

__all__ = [
    # Path E primitives (Algorithm v3.0+)
    "apply_latitude_band_correction",
    "apply_latitude_band_correction_numpy",
    "build_annulus_kernel",
    "build_annulus_count_kernel",
    "build_annulus_weights_numpy",
    "compute_z_local",
    "filter_candidates_to_buffers",
    "compute_z_local_numpy",
    "ANNULUS_REFERENCE_INDUSTRIAL",
    "ANNULUS_REFERENCE_CLEAN",
    "ANNULUS_REFERENCES",
    "apply_two_condition_mask",
    # Detection cascade (P-02.0a heritage)
    "extract_clusters",
    "compute_cluster_attributes",
    "validate_wind",
    "attribute_source",
    "compute_plume_axis_client_side",
    # Constants
    "SIGMA_FLOOR_PPB",
    "ANNULUS_OUTER_KM_DEFAULT",
    "ANNULUS_INNER_KM_DEFAULT",
    "CONSISTENCY_TOLERANCE_PPB_DEFAULT",
    "SOURCE_TYPE_PRIORITIES_CH4",
    "ANALYSIS_SCALE_M",
    "BAND_WIDTH_DEG_DEFAULT",
    "TEMPORAL_WINDOW_DAYS_DEFAULT",
    "BAND_STD_THRESHOLD_PPB_DEFAULT",
    "CH4_DEVIATION_THRESHOLD_PPB",
    "TROPOMI_L3_PIXEL_SIZE_KM",
    "MAD_TO_SIGMA_GAUSSIAN",
    "ANNULUS_REPROJECT_CRS_DEFAULT",
    "MIN_ANNULUS_COUNT_DEFAULT",
]
