"""
Detection orchestrator helpers (Phase 2A, P-02.0a Шаг 5).

Pure-Python helpers + lightweight server-side functions used by
`setup/build_ch4_event_catalog.py`. Separated from `detection_ch4`
primitives to keep primitive module focused on Algorithm §3 mathematical
core; helpers handle TD-0017/0018/0021 mitigations + manual overrides.

Five helper categories:
  1. get_zmin                   — per-region adaptive z_min (TD-0018, DNA §2.1.6)
  2. is_transboundary_easterly  — TD-0017 24h-back ERA5 trajectory check
  3. zone_boundary_step_ppb     — TD-0021 baseline_consistency tolerance inflation
  4. apply_event_overrides      — manual attribution from event_overrides.json
  5. build_event_config         — config dict для compute_provenance

Per CLAUDE.md §1 — code English, comments Russian.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import ee

# ---------------------------------------------------------------------------
# Constants (Phase 1c P-01.2 handoff + TD references)
# ---------------------------------------------------------------------------

# TD-0018 — Kuzbass strict z_min (P-01.2 handoff §3 — primary mitigation)
KUZBASS_LAT_RANGE = (53.0, 55.0)
KUZBASS_LON_RANGE = (86.0, 88.0)
KUZBASS_Z_MIN = 4.0
DEFAULT_Z_MIN = 3.0

# TD-0017 — Transboundary easterly transport check
TRANSBOUNDARY_LAT_RANGE = (53.0, 56.0)
TRANSBOUNDARY_LON_MIN = 92.0
TRANSBOUNDARY_BACK_HOURS = 24
# Easterly = wind FROM E direction (atmospheric convention 0=N, 90=E)
EASTERLY_RANGE_DEG = (45.0, 135.0)

# TD-0021 — Zone-boundary step inflation (P-01.2 handoff quantification at 75°E)
# Step = baseline reference discontinuity at zone-boundary latitude
ZONE_BOUNDARIES_LAT = [57.5, 62.0]
ZONE_BOUNDARY_STEP_PPB: dict[float, float] = {
    57.5: 35.0,  # Kuznetsky → Yugansky transition (M07 step +34.85 ppb)
    62.0: 16.0,  # Yugansky → Verkhne-Tazovsky transition (M07 step −16.18 ppb absolute)
}
ZONE_BOUNDARY_TOLERANCE_KM = 100.0

# Approximate km-per-degree-latitude (constant; lon scaling по cos(lat) elsewhere)
KM_PER_DEG_LAT = 111.0

# TROPOMI CH4 usable retrieval months over Western Siberia AOI (50-75°N).
# CH4 active window: M03–M10 (March–October) per architect domain knowledge
# 2026-05-12 + Šаг 6b2 Stage 3 empirical confirmation:
#   * M01 (winter): polar night at 50-75°N → 0 SWIR retrieval → Export
#     «Table is empty» empirically confirmed (FAILED, 13.1 EECU-hr wasted)
#   * M03 (spring shoulder): low sun angle, partial snow cover →
#     empirically empty в 2024 (FAILED, 21.0 EECU-hr wasted) — included
#     anyway in catalog scope (real CH4 active per researcher domain), but
#     may produce 0 events in specific years (caveat documented)
#   * M11, M12 (autumn/winter): polar night, excluded
#   * M02: shoulder of polar night, retrievals minimal, excluded
# Previous scope [1, 3, 4, 6, 7, 9, 10] (Šаг 0.x probe) erroneously included
# M01 (winter) AND omitted M05 + M08 (peak summer months). Architect
# correction 2026-05-12: production scope = M03–M10 (8 months CH4 active
# window per sun angle / SWIR retrieval constraints).
# Tool-paper §3 framing: «CH4 catalog covers M03–M10 (March–October) per
# sun angle / SWIR retrieval constraints; winter months excluded due к
# polar night limitations at 50–75°N latitudes».
REFERENCE_AVAILABLE_MONTHS = [3, 4, 5, 6, 7, 8, 9, 10]

# VIIRS flare radiance threshold (Algorithm §3.10 source classification)
VIIRS_RADIANCE_THRESHOLD_HIGH = 100.0  # nW/cm²/sr — ≥ → high, < → low


# ---------------------------------------------------------------------------
# Helper 1: per-region z_min (TD-0018, DNA §2.1.6)
# ---------------------------------------------------------------------------


def get_zmin(centroid_lat: float, centroid_lon: float) -> float:
    """
    Return adaptive z_min для cluster centroid coordinates.

    Per Algorithm §3.6 + TD-0018 Phase 1c handoff:
      * Kuzbass region (lat∈[53,55], lon∈[86,88]) → 4.0 (strict — compounded
        uncertainty: pre-fix mask gap + low Kuznetsky Alatau reference counts)
      * Default → 3.0

    DNA §2.1 запрет 6 — single global z_min prohibited. Orchestrator MUST call
    this helper per-cluster after extraction; never pass single z_min to
    apply_three_condition_mask globally over multi-region AOI.
    """
    in_kuzbass_lat = KUZBASS_LAT_RANGE[0] <= centroid_lat <= KUZBASS_LAT_RANGE[1]
    in_kuzbass_lon = KUZBASS_LON_RANGE[0] <= centroid_lon <= KUZBASS_LON_RANGE[1]
    if in_kuzbass_lat and in_kuzbass_lon:
        return KUZBASS_Z_MIN
    return DEFAULT_Z_MIN


def build_zmin_filter() -> ee.Filter:
    """
    Server-side ee.Filter equivalent of get_zmin — для post-cluster filtering
    в orchestrator after compute_cluster_attributes computes max_z + centroid.

    Logic:
        * Cluster outside Kuzbass region: max_z >= 3.0 (default) — already
          enforced by upstream apply_three_condition_mask с z_min=3.0
        * Cluster inside Kuzbass region: max_z >= 4.0 (strict)

    Returns: ee.Filter that keeps clusters meeting their region's threshold.
    """
    # Kuzbass bounding box conditions (all must hold для "in Kuzbass")
    in_kuzbass = ee.Filter.And(
        ee.Filter.gte("centroid_lat", KUZBASS_LAT_RANGE[0]),
        ee.Filter.lte("centroid_lat", KUZBASS_LAT_RANGE[1]),
        ee.Filter.gte("centroid_lon", KUZBASS_LON_RANGE[0]),
        ee.Filter.lte("centroid_lon", KUZBASS_LON_RANGE[1]),
    )
    # Outside Kuzbass: any of these (lat or lon out of range)
    outside_kuzbass = ee.Filter.Or(
        ee.Filter.lt("centroid_lat", KUZBASS_LAT_RANGE[0]),
        ee.Filter.gt("centroid_lat", KUZBASS_LAT_RANGE[1]),
        ee.Filter.lt("centroid_lon", KUZBASS_LON_RANGE[0]),
        ee.Filter.gt("centroid_lon", KUZBASS_LON_RANGE[1]),
    )
    # Keep если: outside Kuzbass (default 3.0 already met by detection) OR
    #            inside Kuzbass с max_z >= 4.0
    keep_inside_kuzbass = ee.Filter.And(in_kuzbass, ee.Filter.gte("max_z", KUZBASS_Z_MIN))
    return ee.Filter.Or(outside_kuzbass, keep_inside_kuzbass)


# ---------------------------------------------------------------------------
# Helper 2: TD-0017 transboundary easterly transport check (server-side)
# ---------------------------------------------------------------------------


def is_transboundary_candidate(centroid_lat: float, centroid_lon: float) -> bool:
    """
    Pure-Python check: does cluster centroid fall into TD-0017 risk zone?

    Risk zone: lat ∈ [53, 56], lon ≥ 92 (eastern AOI edge — Krasnoyarsk
    industrial cluster transport susceptible).
    """
    lat_ok = TRANSBOUNDARY_LAT_RANGE[0] <= centroid_lat <= TRANSBOUNDARY_LAT_RANGE[1]
    lon_ok = centroid_lon >= TRANSBOUNDARY_LON_MIN
    return lat_ok and lon_ok


def annotate_transboundary_qa(
    events_fc: ee.FeatureCollection,
    era5_collection: ee.ImageCollection,
    wind_level_hpa: int = 850,
) -> ee.FeatureCollection:
    """
    TD-0017 LIGHT implementation: 24h-back ERA5 wind direction check.

    For events с centroid lat∈[53,56] and lon≥92, sample ERA5 wind 24h prior
    к event date at cluster centroid. If dominant direction easterly
    (wind_dir ∈ [45°, 135°] FROM convention), add qa_flag
    'transboundary_easterly_transport_suspected'.

    NOT full HYSPLIT trajectory — that's deferred к Phase 6.

    Args:
        events_fc: FeatureCollection of clusters с centroid_lat/lon and orbit_date_millis
        era5_collection: ee.ImageCollection("ECMWF/ERA5/HOURLY")
        wind_level_hpa: ERA5 wind level (default 850, matches TD-0031)

    Returns: FC с qa_flags potentially augmented для at-risk events.
    """
    band_u = f"u_component_of_wind_{wind_level_hpa}hPa"
    band_v = f"v_component_of_wind_{wind_level_hpa}hPa"

    def _check(feat: ee.Feature) -> ee.Feature:
        centroid_lat = ee.Number(feat.get("centroid_lat"))
        centroid_lon = ee.Number(feat.get("centroid_lon"))
        # In risk zone?
        in_lat = centroid_lat.gte(TRANSBOUNDARY_LAT_RANGE[0]).And(
            centroid_lat.lte(TRANSBOUNDARY_LAT_RANGE[1])
        )
        in_lon = centroid_lon.gte(TRANSBOUNDARY_LON_MIN)
        in_zone = in_lat.And(in_lon)

        # Sample ERA5 24h prior
        event_date = ee.Date(feat.get("orbit_date_millis"))
        sample_date = event_date.advance(-TRANSBOUNDARY_BACK_HOURS, "hour")
        # ±1 hour window around target time
        wind_window = era5_collection.filterDate(
            sample_date.advance(-1, "hour"), sample_date.advance(1, "hour")
        ).select([band_u, band_v])

        # GPT review #3 H-5 fix: ERA5 archive may have hour-level gaps (rare,
        # но real). If window is empty, mean() returns masked image → reduceRegion
        # returns null sample → wind_dir undefined → easterly check breaks. Guard
        # via ee.Algorithms.If: skip annotation gracefully когда window empty.
        window_has_data = wind_window.size().gt(0)

        # Provide fallback constants для empty-window case (unused but keeps graph valid)
        u_fallback = ee.Number(0)
        v_fallback = ee.Number(0)

        # Compute wind only когда window non-empty AND in_zone
        # (else branches return safe defaults to keep graph type-stable)
        mean_wind = wind_window.mean()
        centroid_geom = ee.Geometry.Point([centroid_lon, centroid_lat])
        sample = ee.Dictionary(
            ee.Algorithms.If(
                window_has_data,
                mean_wind.reduceRegion(
                    reducer=ee.Reducer.first(), geometry=centroid_geom, scale=27830
                ),
                ee.Dictionary({band_u: u_fallback, band_v: v_fallback}),
            )
        )
        u = ee.Number(ee.Algorithms.If(sample.get(band_u), sample.get(band_u), u_fallback))
        v = ee.Number(ee.Algorithms.If(sample.get(band_v), sample.get(band_v), v_fallback))
        # Wind FROM-direction (atmospheric convention; same formula as validate_wind)
        wind_to_deg = u.atan2(v).multiply(180.0 / math.pi).add(360).mod(360)
        wind_dir = wind_to_deg.add(180).mod(360)

        easterly = wind_dir.gte(EASTERLY_RANGE_DEG[0]).And(wind_dir.lte(EASTERLY_RANGE_DEG[1]))
        # H-5: only flag когда in_zone AND wind data was actually available
        flag_applies = in_zone.And(easterly).And(window_has_data)

        existing_flags = ee.List(feat.get("qa_flags"))
        new_flag = "transboundary_easterly_transport_suspected"
        new_flags = ee.Algorithms.If(flag_applies, existing_flags.add(new_flag), existing_flags)
        return feat.set("qa_flags", new_flags).set(
            "transboundary_back_wind_dir_deg",
            ee.Algorithms.If(in_zone.And(window_has_data), wind_dir, None),
        )

    # Initialize qa_flags as empty list если absent (defensive — orchestrator should set)
    initialized = events_fc.map(
        lambda f: f.set(
            "qa_flags", ee.List(ee.Algorithms.If(f.get("qa_flags"), f.get("qa_flags"), []))
        )
    )
    return initialized.map(_check)


# ---------------------------------------------------------------------------
# Helper 3: TD-0021 zone-boundary step inflation
# ---------------------------------------------------------------------------


def zone_boundary_step_ppb(centroid_lat: float) -> float | None:
    """
    Return step_inflation_ppb для cluster near TD-0021 zone boundary.

    Boundaries: 57.5°N (Kuznetsky → Yugansky), 62.0°N (Yugansky → Verkhne-Tazovsky).
    Tolerance: ±100 km (approximation 0.9° latitude).

    Returns: step_ppb (35 для 57.5°N, 16 для 62°N) или None если cluster
    NOT near any boundary.

    Phase 2A v1 implementation: returns step value; orchestrator decides
    whether to inflate consistency_tolerance_ppb at event level (set
    qa_flag 'zone_boundary_adjustment_applied').
    """
    tolerance_deg = ZONE_BOUNDARY_TOLERANCE_KM / KM_PER_DEG_LAT  # ≈ 0.9°
    for boundary_lat in ZONE_BOUNDARIES_LAT:
        if abs(centroid_lat - boundary_lat) <= tolerance_deg:
            return ZONE_BOUNDARY_STEP_PPB[boundary_lat]
    return None


def annotate_zone_boundary_qa(events_fc: ee.FeatureCollection) -> ee.FeatureCollection:
    """
    TD-0021 zone-boundary adjustment annotation.

    For events с centroid_lat near 57.5°N or 62.0°N (±100 km), add qa_flag
    'zone_boundary_adjustment_applied' + property 'zone_boundary_step_ppb'.
    Reference asset stays unchanged (RFC v2 Option B); event metadata
    captures the inflation factor для downstream classification adjustment.

    Server-side ee.Filter chain — boundaries hardcoded.
    """

    def _check(feat: ee.Feature) -> ee.Feature:
        centroid_lat = ee.Number(feat.get("centroid_lat"))
        tolerance_deg = ZONE_BOUNDARY_TOLERANCE_KM / KM_PER_DEG_LAT

        near_57_5 = centroid_lat.subtract(57.5).abs().lte(tolerance_deg)
        near_62_0 = centroid_lat.subtract(62.0).abs().lte(tolerance_deg)

        # Step value: prioritize 57.5°N if both apply (impossible с 100km tolerance,
        # но defensive)
        step_ppb = ee.Number(
            ee.Algorithms.If(
                near_57_5,
                ZONE_BOUNDARY_STEP_PPB[57.5],
                ee.Algorithms.If(near_62_0, ZONE_BOUNDARY_STEP_PPB[62.0], 0),
            )
        )

        applies = near_57_5.Or(near_62_0)
        existing_flags = ee.List(feat.get("qa_flags"))
        new_flag = "zone_boundary_adjustment_applied"
        new_flags = ee.Algorithms.If(applies, existing_flags.add(new_flag), existing_flags)

        return feat.set(
            {
                "qa_flags": new_flags,
                "zone_boundary_step_ppb": ee.Algorithms.If(applies, step_ppb, None),
            }
        )

    initialized = events_fc.map(
        lambda f: f.set(
            "qa_flags", ee.List(ee.Algorithms.If(f.get("qa_flags"), f.get("qa_flags"), []))
        )
    )
    return initialized.map(_check)


# ---------------------------------------------------------------------------
# Helper 4: reference zone membership (Algorithm v3.0.1 §3.7.1, Шаг 4b P-02.0c)
# Replaces v2.x build_hybrid_background's matched_inside_reference_zone band.
# DNA v2.3 §1.5 Reference Clean Zone preserved as annotation step (cascade Priority 1).
# ---------------------------------------------------------------------------


def annotate_reference_zone_membership(
    cluster_fc: ee.FeatureCollection,
    zapovedniks_geom: ee.Geometry,
    schuit_hull_geom: ee.Geometry | None = None,
) -> ee.FeatureCollection:
    """
    Algorithm v3.0.1 §3.7.1 + v3.1.5 §3.7.1 Schuit hull annotation (Šаг 7).

    Annotate cluster centroid с two reference zone memberships:
    1. **Reference Clean Zone (zapovedniks)** — DNA v2.3 §1.5 cascade Priority 1
       federal-protected zones override. Industrial activity legally prohibited.
       Detected event inside zapovednik → automatic false-positive flag.

    2. **Schuit 2023 validation zone (convex hull of AOI events)** — NEW v3.1.5.
       Phase 4 Comparison Engine annotation: cluster centroid inside Schuit's
       documented validation coverage area means external reference exists для
       cross-source validation. Outside hull — Schuit didn't validate there.
       Soft annotation, NOT cascade trigger.

    Adds properties:
        * inside_reference_clean_zone: ee.Number (0 or 1) — cluster centroid ∈
          zapovedniks_geom (cascade Priority 1)
        * inside_schuit_validation_zone: ee.Number (0 or 1) — cluster centroid ∈
          schuit_hull_geom (annotation only, Phase 4 Comparison Engine use).
          Only added если schuit_hull_geom provided; else absent.

    Used by `classify_event` cascade Priority 1 (federal-protected zones override).
    Backward-compat: `classify_event` reads BOTH `matched_inside_reference_zone`
    (P-02.0a alias) AND `inside_reference_clean_zone` (v3.0 name) — either
    triggers Priority 1.

    Args:
        cluster_fc: output `compute_cluster_attributes` (must have geometry)
        zapovedniks_geom: union of zapovednik polygons (Юганский ∪
            Верхнетазовский ∪ Кузнецкий Алатау), loaded from
            `RuPlumeScan/reference/protected_areas` FeatureCollection
        schuit_hull_geom: optional Schuit 2023 AOI convex hull Geometry
            (v3.1.5 Šаг 7). If None, `inside_schuit_validation_zone` property
            not added (backward compat для Stage 1/2 catalog generation pre-Šаг 7).

    Returns:
        ee.FeatureCollection с added properties.
    """

    def _annotate(feat: ee.Feature) -> ee.Feature:
        # maxError=1 required (Šаг 6b2 P-02.0c bug fix 2026-05-10):
        # complex cluster geometries spanning EPSG:6931 reprojection edges trigger
        # «Geometry.centroid: Unable to perform this geometry operation. Please
        # specify a non-zero error margin.» — surfaced при 7/7 monthly chunks FAIL.
        # Probe-scale narrow AOI (Šаг 6b1) had simpler geometries hence не triggered.
        centroid = feat.geometry().centroid(maxError=1)
        # Defensive maxError=1 на contains too — zapovedniks_geom union of multi-polygon
        # federal-protected zones may have non-trivial complexity. Cheap insurance.
        inside_zap = zapovedniks_geom.contains(centroid, maxError=1)
        feat = feat.set(
            "inside_reference_clean_zone",
            ee.Number(ee.Algorithms.If(inside_zap, 1, 0)),
        )
        # Schuit hull annotation (Algorithm v3.1.5 §3.7.1, Šаг 7)
        if schuit_hull_geom is not None:
            inside_schuit = schuit_hull_geom.contains(centroid, maxError=1)
            feat = feat.set(
                "inside_schuit_validation_zone",
                ee.Number(ee.Algorithms.If(inside_schuit, 1, 0)),
            )
        return feat

    return cluster_fc.map(_annotate)


# ---------------------------------------------------------------------------
# Helper 5: artifact diagnostics (Algorithm v3.1.1 §3.7.2, Шаг 5c P-02.0c)
# Per-cluster correlation Z × MODIS SWIR albedo + snow cover overlap.
# Annotation only — NOT hard mask, NOT cascade trigger (Finding 3 scope).
# ---------------------------------------------------------------------------

# MODIS data sources (Шаг 5c choices)
MODIS_ALBEDO_COLLECTION = "MODIS/061/MCD43A4"  # 8-day BRDF-adjusted reflectance
MODIS_ALBEDO_BAND = "Nadir_Reflectance_Band6"  # SWIR-1 (1628-1652 nm) — closest к TROPOMI SWIR
MODIS_SNOW_COLLECTION = "MODIS/061/MOD10A1"  # Daily snow cover Terra
MODIS_SNOW_BAND = "NDSI_Snow_Cover"  # 0-100 percent

# Default thresholds (empirical calibration → Шаг 6 ablation)
ARTIFACT_ALBEDO_CORR_THRESHOLD = 0.5  # |corr_albedo| > threshold → suspect
ARTIFACT_SNOW_FRACTION_THRESHOLD = 0.5  # snow > 50% of cluster → suspect
ARTIFACT_SNOW_NDSI_THRESHOLD = 50  # MODIS NDSI > 50 → snow pixel (binary)

# Temporal windows for MODIS sampling
ALBEDO_TEMPORAL_WINDOW_DAYS = 8  # MCD43A4 native 8-day composite
SNOW_TEMPORAL_WINDOW_DAYS = 1  # MOD10A1 daily

# Sampling scales
ALBEDO_SAMPLING_SCALE_M = 5500  # match TROPOMI L3 reprojected scale
SNOW_SAMPLING_SCALE_M = 500  # MODIS native


def annotate_artifact_diagnostics(
    cluster_fc: ee.FeatureCollection,
    z_image: ee.Image,
    orbit_time_millis: int | ee.Date,
    z_band: str = "Z_local",
    albedo_corr_threshold: float = ARTIFACT_ALBEDO_CORR_THRESHOLD,
    snow_fraction_threshold: float = ARTIFACT_SNOW_FRACTION_THRESHOLD,
    snow_ndsi_threshold: int = ARTIFACT_SNOW_NDSI_THRESHOLD,
) -> ee.FeatureCollection:
    """
    Algorithm v3.1.4 §3.7.2 (Шаг 5c P-02.0c, refined Шаг 6b2-closure TD-0044
    2026-05-14): retrieval-covariate artifact diagnostics с DIRECTIONAL
    corr_albedo logic (Lorente 2021 physical asymmetry).

    **Annotation only**, не hard mask. But artifact_likely IS used downstream
    в production catalog filtering — directional logic critical для not
    falsely excluding dark-surface (wet tundra) real industrial events.

    Implementation choices (CC, documented Algorithm §3.7.2):
        * Albedo source: MCD43A4 (8-day BRDF-adjusted) — preferred over MOD09GA
          daily (BRDF-corrected, more stable; albedo varies slowly enough
          для 8-day window к match orbit date)
        * SWIR Band 6 (1628-1652 nm) — closest к TROPOMI SWIR retrieval per
          Lorente 2021 documented bias correlation
        * Snow source: MOD10A1 daily NDSI snow cover (orbit-specific match)
        * Snow application universal (летом snow_fraction ≈ 0 в большинстве
          AOI; no harm; simpler than season-gating)

    TD-0044 directional albedo logic (Algorithm v3.1.4, GPT review #3 2026-05-14):

        Physics asymmetric:
        - **Positive** corr_albedo (high Z + high albedo) = bright-surface SWIR
          retrieval bias (snow/ice/desert) → CORRECT hard artifact pathway
        - **Negative** corr_albedo (high Z + low albedo) = dark/wet surface
          confound (e.g. wet tundra Yamal) → annotation only, NOT hard artifact
          (could falsely exclude real industrial events over dark surfaces)

        Previous v3.1.3 symmetric `abs(corr_albedo) > 0.5` was incorrect —
        treated both regimes as equivalent.

    Per-cluster annotations added:
        * corr_albedo (float, [-1, 1]): Pearson correlation of cluster Z values
          с MCD43A4 SWIR Band 6 albedo within cluster geometry
        * cluster_overlap_snow_fraction (float, [0, 1]): fraction of cluster
          pixels с MODIS NDSI > snow_ndsi_threshold
        * artifact_likely_albedo_positive (Number 0/1): NEW v3.1.4 — TRUE если
          corr_albedo >= +threshold (bright-surface SWIR artifact)
        * surface_confounded_dark (Number 0/1): NEW v3.1.4 — TRUE если
          corr_albedo <= -threshold (dark/wet surface confound — annotation only,
          NOT hard artifact)
        * artifact_likely (Number 0/1): hard artifact flag — fires только on
          artifact_likely_albedo_positive OR (snow_fraction > snow_threshold).
          surface_confounded_dark NOT included.

    Trigger conditions для downstream (deferred к Phase 4 Comparison Engine
    или Шаг 6 ablation):
        * Empirical threshold calibration via real-orbit catalog vs Schuit
          reference (corr_albedo distribution analysis)
        * Combined-with-other-flags filtering

    Deferred к v1.1 (per Шаг 5c scope):
        * corr_sensor_zenith — TROPOMI metadata band exploration (TD-0040)
        * cluster_overlap_water_fraction — JRC GSW occurrence (TD-0041,
          partially redundant с TROPOMI native QA)

    Args:
        cluster_fc: FC after compute_cluster_attributes (clusters с geometry)
        z_image: ee.Image с band `z_band`
        orbit_time_millis: orbit timestamp (millis or ee.Date)
        z_band: Z-score band name в z_image (default "Z_local")
        albedo_corr_threshold: |threshold| (signed comparison applied internally:
            corr_albedo >= +threshold → artifact_likely_albedo_positive;
            corr_albedo <= -threshold → surface_confounded_dark)
        snow_fraction_threshold: snow fraction above this → artifact_likely flag
        snow_ndsi_threshold: MODIS NDSI > this → snow pixel (binary)

    Returns:
        ee.FeatureCollection с 5 added properties (v3.1.4):
            corr_albedo (Number, may be 0)
            cluster_overlap_snow_fraction (Number, [0, 1])
            artifact_likely_albedo_positive (Number, 0 or 1) — NEW v3.1.4
            surface_confounded_dark (Number, 0 or 1) — NEW v3.1.4
            artifact_likely (Number, 0 or 1) — TD-0044 directional rule

    DNA compliance:
        * §2.1.4 unmask(0): not used (mean reducer для snow returns fraction).
        * §2.1.5 ee.Kernel arithmetic: not applicable (no kernels).
        * CLAUDE.md §3.2 bestEffort:true: not used.
    """
    orbit_date = ee.Date(orbit_time_millis)

    # MCD43A4 8-day composite — average over ±8 days
    albedo_image = (
        ee.ImageCollection(MODIS_ALBEDO_COLLECTION)
        .filterDate(
            orbit_date.advance(-ALBEDO_TEMPORAL_WINDOW_DAYS, "day"),
            orbit_date.advance(ALBEDO_TEMPORAL_WINDOW_DAYS, "day"),
        )
        .select(MODIS_ALBEDO_BAND)
        .mean()
    )

    # MOD10A1 daily snow — average over ±1 day
    snow_image = (
        ee.ImageCollection(MODIS_SNOW_COLLECTION)
        .filterDate(
            orbit_date.advance(-SNOW_TEMPORAL_WINDOW_DAYS, "day"),
            orbit_date.advance(SNOW_TEMPORAL_WINDOW_DAYS, "day"),
        )
        .select(MODIS_SNOW_BAND)
        .mean()
    )
    snow_binary = snow_image.gt(snow_ndsi_threshold)

    # Stack Z + albedo для correlation reduction
    z_albedo_stack = z_image.select(z_band).addBands(albedo_image)

    def _annotate(feat: ee.Feature) -> ee.Feature:
        geom = feat.geometry()

        # Correlation Z × albedo within cluster
        # ee.Reducer.pearsonsCorrelation returns dict с 'correlation' + 'p-value' keys
        corr_dict = z_albedo_stack.reduceRegion(
            reducer=ee.Reducer.pearsonsCorrelation(),
            geometry=geom,
            scale=ALBEDO_SAMPLING_SCALE_M,
            maxPixels=int(1e8),
        )
        corr_albedo = ee.Number(
            ee.Algorithms.If(
                corr_dict.get("correlation"),
                corr_dict.get("correlation"),
                0,
            )
        )

        # Snow fraction within cluster — mean of binary mask = fraction
        snow_dict = snow_binary.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geom,
            scale=SNOW_SAMPLING_SCALE_M,
            maxPixels=int(1e8),
        )
        snow_frac = ee.Number(
            ee.Algorithms.If(
                snow_dict.get(MODIS_SNOW_BAND),
                snow_dict.get(MODIS_SNOW_BAND),
                0,
            )
        )

        # TD-0044 directional artifact_likely rule (Algorithm v3.1.4):
        # Positive corr → bright-surface SWIR retrieval bias (snow/ice/desert)
        # Negative corr → dark/wet surface confound (wet tundra) — annotation only
        artifact_albedo_positive = corr_albedo.gte(albedo_corr_threshold)  # >= +0.5
        surface_dark = corr_albedo.lte(ee.Number(albedo_corr_threshold).multiply(-1))  # <= -0.5
        high_snow = snow_frac.gt(snow_fraction_threshold)

        # artifact_likely fires только на positive albedo OR snow
        # surface_confounded_dark exposed separately, NOT included
        artifact_likely = ee.Number(
            ee.Algorithms.If(artifact_albedo_positive.Or(high_snow), 1, 0)
        )
        artifact_likely_albedo_positive = ee.Number(
            ee.Algorithms.If(artifact_albedo_positive, 1, 0)
        )
        surface_confounded_dark = ee.Number(
            ee.Algorithms.If(surface_dark, 1, 0)
        )

        return feat.set({
            "corr_albedo": corr_albedo,
            "cluster_overlap_snow_fraction": snow_frac,
            "artifact_likely": artifact_likely,
            "artifact_likely_albedo_positive": artifact_likely_albedo_positive,
            "surface_confounded_dark": surface_confounded_dark,
        })

    return cluster_fc.map(_annotate)


# ---------------------------------------------------------------------------
# Helper 6: manual event overrides (Algorithm §6, event_overrides.json)
# ---------------------------------------------------------------------------


def load_event_overrides(overrides_path: str | Path) -> list[dict[str, Any]]:
    """
    Load manual override entries from JSON file.

    Schema per entry:
        {
          "centroid_lat": <float>,
          "centroid_lon": <float>,
          "event_date": "YYYY-MM-DD",
          "tolerance_km": <float, default 20>,
          "tolerance_days": <int, default 2>,
          "manual_source_id": <str>,
          "manual_source_type": <str>,
          "rationale": <str — short note for audit>
        }

    Returns: list of override dicts. Empty list если file absent/empty.
    """
    p = Path(overrides_path)
    if not p.exists():
        return []
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return data


def apply_event_overrides(
    events_fc: ee.FeatureCollection, overrides: list[dict[str, Any]]
) -> ee.FeatureCollection:
    """
    Apply manual attribution overrides к matching events.

    For each override entry, find event(s) с centroid within tolerance_km
    of override coords AND orbit_date within tolerance_days of override
    event_date. Set manual_source_id/type + qa_flag
    'manual_attribution_override'.

    Server-side per-feature filter; iterate overrides client-side
    (overrides count typically < 50 — manual review artifact).

    Args:
        events_fc: FC with centroid_lat, centroid_lon, orbit_date_millis,
            qa_flags properties
        overrides: list of override dicts (from load_event_overrides)

    Returns: FC with overrides applied (or original FC если overrides empty).
    """
    if not overrides:
        return events_fc

    # Initialize qa_flags если absent
    fc = events_fc.map(
        lambda f: f.set(
            "qa_flags", ee.List(ee.Algorithms.If(f.get("qa_flags"), f.get("qa_flags"), []))
        )
    )

    for entry in overrides:
        try:
            ovr_lat = float(entry["centroid_lat"])
            ovr_lon = float(entry["centroid_lon"])
            ovr_date_str = str(entry["event_date"])
            tol_km = float(entry.get("tolerance_km", 20))
            tol_days = int(entry.get("tolerance_days", 2))
            manual_id = entry.get("manual_source_id")
            manual_type = entry.get("manual_source_type")
        except (KeyError, ValueError, TypeError):
            continue  # malformed entry — skip

        ovr_date = ee.Date(ovr_date_str)
        # GPT review #3 H-4 fix: ±tol_days inclusive window = (2*tol+1) calendar days.
        # Example: ovr_date=2022-09-20, tol=2 → window [2022-09-18T00:00, 2022-09-23T00:00),
        # captures 09-18, 09-19, 09-20, 09-21, 09-22 (5 calendar days).
        # date_min: midnight of (event - tol_days) — inclusive lower bound
        # date_max: midnight of (event + tol_days + 1) — exclusive upper bound (use ts.lt)
        date_min = ovr_date.advance(-tol_days, "day").millis()
        date_max = ovr_date.advance(tol_days + 1, "day").millis()
        # Spatial tolerance в degrees (rough — orchestrator-side filter; precise
        # filtering would require geometry distance, deferred к Шаг 6 если needed)
        tol_lat_deg = tol_km / KM_PER_DEG_LAT
        tol_lon_deg = tol_km / (KM_PER_DEG_LAT * math.cos(math.radians(ovr_lat)))

        def _apply(
            feat: ee.Feature,
            _ovr_lat: float = ovr_lat,
            _ovr_lon: float = ovr_lon,
            _tol_lat: float = tol_lat_deg,
            _tol_lon: float = tol_lon_deg,
            _date_min: ee.Number = date_min,
            _date_max: ee.Number = date_max,
            _manual_id: Any = manual_id,
            _manual_type: Any = manual_type,
        ) -> ee.Feature:
            lat = ee.Number(feat.get("centroid_lat"))
            lon = ee.Number(feat.get("centroid_lon"))
            ts = ee.Number(feat.get("orbit_date_millis"))
            lat_match = lat.subtract(_ovr_lat).abs().lte(_tol_lat)
            lon_match = lon.subtract(_ovr_lon).abs().lte(_tol_lon)
            # H-4: exclusive upper bound (ts.lt) — see date_max construction above
            date_match = ts.gte(_date_min).And(ts.lt(_date_max))
            matches = lat_match.And(lon_match).And(date_match)

            existing = ee.List(feat.get("qa_flags"))
            new_flag = "manual_attribution_override"
            new_flags = ee.Algorithms.If(matches, existing.add(new_flag), existing)

            return feat.set(
                {
                    "qa_flags": new_flags,
                    "manual_source_id": ee.Algorithms.If(
                        matches, _manual_id, feat.get("manual_source_id")
                    ),
                    "manual_source_type": ee.Algorithms.If(
                        matches, _manual_type, feat.get("manual_source_type")
                    ),
                }
            )

        fc = fc.map(_apply)

    return fc


# ---------------------------------------------------------------------------
# Helper 5: build_event_config for compute_provenance
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Helper 7: qa_flags export encoding (GEE Export.table.toAsset compatibility)
# ---------------------------------------------------------------------------

# Separator используемый при join-encoding qa_flags для export
QA_FLAGS_SEPARATOR = ";"


def encode_qa_flags_for_export(fc: ee.FeatureCollection) -> ee.FeatureCollection:
    """
    Convert qa_flags list property к semicolon-separated string before Export.

    GEE Export.table.toAsset rejects List<Object> properties (initialized
    via ee.List([]) — empty list has untyped Object element type which GEE
    cannot serialize). Failure observed Шаг 5 first launch attempt:
        "Unable to encode value 'qa_flags' of feature ...: invalid type
         List<Object>. (Error code: 3)"

    Solution: convert list к string at last orchestrator stage (just before
    submit_export). Downstream consumers split на QA_FLAGS_SEPARATOR (";") к
    recover original list. Schema documents encoded format.

    Empty list → empty string "".
    Single flag → "flag_name".
    Multiple flags → "flag1;flag2;flag3".

    Args:
        fc: FeatureCollection с qa_flags property as ee.List

    Returns: FC с qa_flags property converted к string.
    """

    def _encode(feat: ee.Feature) -> ee.Feature:
        flags_list = ee.List(ee.Algorithms.If(feat.get("qa_flags"), feat.get("qa_flags"), []))
        flags_str = ee.Algorithms.If(
            flags_list.size().gt(0),
            flags_list.join(QA_FLAGS_SEPARATOR),
            "",
        )
        return feat.set("qa_flags", flags_str)

    return fc.map(_encode)


def decode_qa_flags(qa_flags_str: str) -> list[str]:
    """Split semicolon-encoded qa_flags string back к list (downstream consumer).

    Empty string → empty list. Used when reading produced catalog asset.
    """
    if not qa_flags_str:
        return []
    return qa_flags_str.split(QA_FLAGS_SEPARATOR)


# ---------------------------------------------------------------------------
# Helper 6: server-side source_type_category classifier
# ---------------------------------------------------------------------------


def prepare_source_points_categories(
    source_points_fc: ee.FeatureCollection,
    viirs_radiance_threshold: float = VIIRS_RADIANCE_THRESHOLD_HIGH,
) -> ee.FeatureCollection:
    """
    Add `source_type_category` property к source_points FC server-side.

    Maps (source_type, source_subtype, viirs_radiance_mean) → category per
    Algorithm §3.10 + classify_source_types.py logic. Drops hydro/nuclear
    power_plant entries.

    Mapping:
      * oil_gas + production_field         → gas_field           (priority 1)
      * oil_gas + viirs_flare_proxy + r≥100 → viirs_flare_high    (priority 2)
      * oil_gas + viirs_flare_proxy + r<100 → viirs_flare_low     (priority 5)
      * power_plant + coal/gas/tpp_gas      → tpp_gres            (priority 4)
      * power_plant + hydro/nuclear         → DROPPED
      * coal_mine                           → coal_mine           (priority 3)
      * metallurgy                          → smelter             (priority 6)
      * (anything else)                     → unknown (default priority 999)

    Server-side via ee.Algorithms.If chain. Required by attribute_source которая
    expects `source_type_category` property.

    Args:
        source_points_fc: FC с source_type, source_subtype, viirs_radiance_mean
        viirs_radiance_threshold: ≥ → high, < → low (default 100 nW/cm²/sr)

    Returns: FC с source_type_category property added; hydro/nuclear filtered out.
    """

    def _classify(feat: ee.Feature) -> ee.Feature:
        st = ee.String(feat.get("source_type"))
        sst = ee.String(feat.get("source_subtype"))
        radiance = ee.Number(
            ee.Algorithms.If(feat.get("viirs_radiance_mean"), feat.get("viirs_radiance_mean"), 0)
        )

        # oil_gas branches
        is_production_field = sst.compareTo("production_field").eq(0)
        is_viirs_proxy = sst.compareTo("viirs_flare_proxy").eq(0)
        viirs_high = radiance.gte(viirs_radiance_threshold)
        category_oil_gas = ee.Algorithms.If(
            is_production_field,
            "gas_field",
            ee.Algorithms.If(
                is_viirs_proxy,
                ee.Algorithms.If(viirs_high, "viirs_flare_high", "viirs_flare_low"),
                "unknown",
            ),
        )

        # power_plant branches: hydro/nuclear → dropped
        is_hydro = sst.compareTo("hydro").eq(0)
        is_nuclear = sst.compareTo("nuclear").eq(0)
        category_pp = ee.Algorithms.If(is_hydro.Or(is_nuclear), "dropped", "tpp_gres")

        # Type dispatch
        is_oil_gas = st.compareTo("oil_gas").eq(0)
        is_pp = st.compareTo("power_plant").eq(0)
        is_coal = st.compareTo("coal_mine").eq(0)
        is_metal = st.compareTo("metallurgy").eq(0)

        category = ee.Algorithms.If(
            is_oil_gas,
            category_oil_gas,
            ee.Algorithms.If(
                is_pp,
                category_pp,
                ee.Algorithms.If(
                    is_coal,
                    "coal_mine",
                    ee.Algorithms.If(is_metal, "smelter", "unknown"),
                ),
            ),
        )

        return feat.set("source_type_category", category)

    classified = source_points_fc.map(_classify)
    # Drop hydro/nuclear (category='dropped')
    return classified.filter(ee.Filter.neq("source_type_category", "dropped"))


# ---------------------------------------------------------------------------
# Helper 5: build_event_config for compute_provenance
# ---------------------------------------------------------------------------


def build_event_config(target_year: int, *, config_preset: str = "default") -> dict[str, Any]:
    """
    Construct config dict для CH4 event catalog Run.

    Per Algorithm §2.4 Configuration Preset structure. Used as input к
    `compute_provenance(config) → Provenance` at orchestrator process start.

    Pin all algorithmic parameters here — provenance hash captures them
    for reproducibility (DNA §2.1 запрет 12).
    """
    return {
        "config_preset": config_preset,
        "phase": "P-02.0a",
        "gas": "CH4",
        "history_year_min": 2019,
        "history_year_max": 2025,
        "target_year": target_year,
        "operation": "ch4_event_catalog_build",
        # Detection thresholds (Algorithm §3.5-§3.6)
        "anomaly": {
            "z_min_default": DEFAULT_Z_MIN,
            "z_min_kuzbass": KUZBASS_Z_MIN,
            "delta_min_ppb": 30.0,
            "relative_min_ppb": 15.0,
            "annulus_outer_km": 150,
        },
        # Background mode (Algorithm §3.4.3 / §3.5)
        "background": {
            "primary": "reference",
            "mode": "reference_only",  # TD-0032 — Phase 2A v1 simplification
            "consistency_tolerance_ppb": 30.0,
            "sigma_floor_ppb": 15.0,
        },
        # Cluster extraction (Algorithm §3.7)
        "object": {
            "min_pixels": 5,
            "max_size": 256,
            "connectedness": 8,
        },
        # Wind validation (Algorithm §3.9, TD-0031)
        "wind": {
            "level_hpa": 850,
            "alignment_threshold_deg": 30.0,
            "min_wind_speed_ms": 2.0,
            "temporal_window_hours": 3,
        },
        # Source attribution (Algorithm §3.10)
        "source_attribution": {
            "search_radius_km": 50.0,
            "type_priorities": "SOURCE_TYPE_PRIORITIES_CH4",
        },
        # TD-0017 transboundary
        "transboundary": {
            "lat_range": list(TRANSBOUNDARY_LAT_RANGE),
            "lon_min": TRANSBOUNDARY_LON_MIN,
            "back_trajectory_hours": TRANSBOUNDARY_BACK_HOURS,
            "easterly_range_deg": list(EASTERLY_RANGE_DEG),
        },
        # TD-0021 zone-boundary
        "zone_boundary": {
            "boundaries_lat": ZONE_BOUNDARIES_LAT,
            "step_inflation_ppb": {str(k): v for k, v in ZONE_BOUNDARY_STEP_PPB.items()},
            "tolerance_km": ZONE_BOUNDARY_TOLERANCE_KM,
        },
        # TD-0034 — reference baseline limitation
        "available_months": REFERENCE_AVAILABLE_MONTHS,
        "build_pipeline": "src/py/setup/build_ch4_event_catalog.py",
    }


# ---------------------------------------------------------------------------
# Module exports
# ---------------------------------------------------------------------------

__all__ = [
    "DEFAULT_Z_MIN",
    "KUZBASS_Z_MIN",
    "KUZBASS_LAT_RANGE",
    "KUZBASS_LON_RANGE",
    "TRANSBOUNDARY_LAT_RANGE",
    "TRANSBOUNDARY_LON_MIN",
    "TRANSBOUNDARY_BACK_HOURS",
    "EASTERLY_RANGE_DEG",
    "ZONE_BOUNDARIES_LAT",
    "ZONE_BOUNDARY_STEP_PPB",
    "ZONE_BOUNDARY_TOLERANCE_KM",
    "REFERENCE_AVAILABLE_MONTHS",
    "VIIRS_RADIANCE_THRESHOLD_HIGH",
    "QA_FLAGS_SEPARATOR",
    "get_zmin",
    "build_zmin_filter",
    "is_transboundary_candidate",
    "annotate_transboundary_qa",
    "zone_boundary_step_ppb",
    "annotate_zone_boundary_qa",
    "annotate_reference_zone_membership",
    "annotate_artifact_diagnostics",
    # Шаг 5c artifact diagnostics constants
    "MODIS_ALBEDO_COLLECTION",
    "MODIS_ALBEDO_BAND",
    "MODIS_SNOW_COLLECTION",
    "MODIS_SNOW_BAND",
    "ARTIFACT_ALBEDO_CORR_THRESHOLD",
    "ARTIFACT_SNOW_FRACTION_THRESHOLD",
    "ARTIFACT_SNOW_NDSI_THRESHOLD",
    "load_event_overrides",
    "apply_event_overrides",
    "prepare_source_points_categories",
    "encode_qa_flags_for_export",
    "decode_qa_flags",
    "build_event_config",
]
