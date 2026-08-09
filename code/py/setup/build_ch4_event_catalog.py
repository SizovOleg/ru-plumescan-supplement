"""
Build RuPlumeScan/catalog/CH4/events_<year> FeatureCollection — annual CH₄
plume event catalog (Path E v3.1.1, Шаг 6a P-02.0c orchestrator wiring).

Per RFC v2 frozen architecture + DevPrompt P-02.0c §9.

Per-year processing (sequential 2019..2025 при full launch):
  1. Load TROPOMI L3 CH4 collection filtered by year + AOI
  2. Build annulus_kernel ONCE (Algorithm v3.0.4 §3.4.2 ee.Kernel.fixed)
  3. Load industrial_mask + zapovedniks_geom assets
  4. Per-month iteration over orbits → cluster FeatureCollections via Path E primitives:
       apply_latitude_band_correction (Шаг 3, Algorithm §3.5)
       → apply_two_condition_mask (Шаг 5a, §3.6)
       → compute_z_local (Шаг 4a + 5b1 reproject EPSG:6931 + median/MAD, §3.4.3)
       → Z threshold (Algorithm §3.7 prep)
       → extract_clusters → compute_cluster_attributes
       → annotate_reference_zone_membership (Шаг 4b, §3.7.1 cascade Priority 1)
       → validate_wind (Шаг 5b2, 10m primary + 850 hPa consistency, §3.9)
       → attribute_source (§3.10)
       → annotate_artifact_diagnostics (Шаг 5c, §3.7.2)
  5. Per-region adaptive z_min via build_zmin_filter (TD-0018, DNA §2.1.6)
  6. TD-0017 transboundary easterly check (lat∈[53,56], lon≥92)
  7. TD-0021 zone-boundary qa annotation (centroids ±100 km of 57.5°N or 62°N)
  8. Manual override application (config/event_overrides.json)
  9. apply_classification cascade (Algorithm §3.12)
  10. Annual catalog export → RuPlumeScan/catalog/CH4/events_<year>

Canonical Provenance pattern (TD-0024/0025): `compute_provenance(config) →
Provenance` ONCE at process start; pass by reference к все subsequent
operations (STARTED log, asset metadata, SUCCEEDED log).

NOT auto-launching full 7-year compute. Use:
  --year <YYYY>           process single year (default: print plan, no submit)
  --launch-year <YYYY>    actually submit batch task (requires GEE auth)
  --dry-run               print pipeline graph node count + plan, no submit
  --combine-years         merge per-year catalogs → master index after full run

Запуск (single-year test 2024 — Path E v3.1.1 first launch)::

    cd src/py
    python -m setup.build_ch4_event_catalog --launch-year 2024 --dry-run
    python -m setup.build_ch4_event_catalog --launch-year 2024
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import ee

# sys.path adjustment for module-vs-script invocation
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT / "src" / "py") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src" / "py"))

from rca import detection_ch4  # noqa: E402  — sys.path injected above
from rca.classify_events import apply_classification  # noqa: E402
from rca.detection_helpers import (  # noqa: E402
    REFERENCE_AVAILABLE_MONTHS,
    annotate_artifact_diagnostics,  # Шаг 5c
    annotate_reference_zone_membership,  # Шаг 4b
    annotate_transboundary_qa,
    annotate_zone_boundary_qa,
    apply_event_overrides,
    build_event_config,
    build_zmin_filter,
    encode_qa_flags_for_export,
    load_event_overrides,
    prepare_source_points_categories,
)
from rca.provenance import compute_provenance, write_provenance_log  # noqa: E402

# ---------------------------------------------------------------------------
# Constants — Path E v3.1.1 (Шаг 6a P-02.0c orchestrator wiring)
# ---------------------------------------------------------------------------

PROJECT_ID = "nodal-thunder-481307-u1"
ASSETS_ROOT = f"projects/{PROJECT_ID}/assets"

# Path E assets (Algorithm v3.1.1 §3.4-§3.7):
# REMOVED в Шаг 6a (Path E pivot — no multi-year baseline):
#   * REFERENCE_BASELINE_ASSET — multi-year climatology (Шаг 4a removed)
#   * REGIONAL_BASELINE_ASSET — multi-year industrial-buffered (Шаг 4a removed)

# Industrial mask (per-source-type buffer P-01.0d / TD-0027) — used by
# apply_two_condition_mask (Algorithm §3.6 v3.0.3 B2 scope, Шаг 5a)
INDUSTRIAL_MASK_ASSET = f"{ASSETS_ROOT}/RuPlumeScan/industrial/proxy_mask_buffered_per_type"

# Reference zones (zapovedniks) — used by annotate_reference_zone_membership
# (Algorithm §3.7.1 Шаг 4b)
REFERENCE_ZONES_ASSET = f"{ASSETS_ROOT}/RuPlumeScan/reference/protected_areas"
SOURCE_POINTS_ASSET = f"{ASSETS_ROOT}/RuPlumeScan/industrial/source_points"

# Two-stage architecture (Option A, Šаг 5 axis-fix):
#   Stage 1: build_ch4_event_catalog.py → events_{year}_intermediate (no axis,
#            wind_state='axis_unknown' для всех)
#   Stage 2: enrich_plume_axes.py reads intermediate, computes axes client-side,
#            re-runs validate_wind + apply_classification, exports → events_{year}
#
# Per-month chunking (Šаг 6b2 P-02.0c, post-failure 2026-05-09 12h GEE timeout):
# Single-year full-warm-season exceeds 12h batch limit. Per-month sub-tasks
# fit comfortably (~1-2h each). Stage 1 chunked → 7 monthly intermediate
# assets → combine step merges into annual intermediate → Stage 2 unchanged.
INTERMEDIATE_ASSET_TEMPLATE = f"{ASSETS_ROOT}/RuPlumeScan/catalog/CH4/events_{{year}}_intermediate"
INTERMEDIATE_MONTHLY_TEMPLATE = f"{ASSETS_ROOT}/RuPlumeScan/catalog/CH4/events_{{year}}_M{{month:02d}}_intermediate"
FINAL_ASSET_TEMPLATE = f"{ASSETS_ROOT}/RuPlumeScan/catalog/CH4/events_{{year}}"
EVENT_OVERRIDES_PATH = _REPO_ROOT / "config" / "event_overrides.json"

# AOI bbox (Western Siberia + Алтай south extension)
AOI_BBOX = (60.0, 50.0, 95.0, 75.0)
ANALYSIS_SCALE_M = 7000

TROPOMI_CH4_COLLECTION = "COPERNICUS/S5P/OFFL/L3_CH4"
TROPOMI_CH4_BAND = "CH4_column_volume_mixing_ratio_dry_air_bias_corrected"
ERA5_HOURLY_COLLECTION = "ECMWF/ERA5/HOURLY"


# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------


def setup_logger() -> logging.Logger:
    logger = logging.getLogger("build_ch4_event_catalog")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        logger.addHandler(h)
    return logger


# ---------------------------------------------------------------------------
# Per-orbit detection pipeline (Stage 1 — server-side lazy)
# ---------------------------------------------------------------------------


def detect_orbit_clusters(
    orbit_image: ee.Image,
    aoi: ee.Geometry,
    annulus_kernel: ee.Kernel,
    industrial_mask: ee.Image,
    zapovedniks_geom: ee.Geometry,
    era5_collection: ee.ImageCollection,
    source_points_fc: ee.FeatureCollection,
    month: int,
    *,
    annulus_count_kernel: ee.Kernel | None = None,
    z_min: float = 3.0,
    min_cluster_px: int = 5,
    apply_lat_band_correction: bool = True,
    apply_artifact_diag: bool = True,
    wind_level: str = "10m",
    alignment_threshold_deg: float = 30.0,
    min_wind_speed_ms: float = 2.0,
    temporal_window_hours: int = 3,
    search_radius_km: float = 50.0,
) -> ee.FeatureCollection:
    """
    Stage 1 Path E per-orbit detection pipeline (Algorithm v3.1.1 server-side lazy).

    Pipeline (Path E Шаги 3+4a+4b+5a+5b+5c rewired Шаг 6a):
      0. apply_latitude_band_correction (Шаг 3, Algorithm §3.5) — per-pixel
         temporal-median persistent-deviation correction. Optional via flag.
      1. apply_two_condition_mask(corrected_orbit, industrial_mask) — Шаг 5a
         B2 industrial-only proxy mask (Algorithm §3.6).
      2. compute_z_local(corrected_orbit, annulus_kernel, proxy_mask) — Шаг 4a
         + 5b1 reproject EPSG:6931 + median/MAD + min_annulus_count (§3.4.3).
      3. Z threshold gte(z_min) → binary detection mask.
      4. extract_clusters → cluster_image (Algorithm §3.7).
      5. compute_cluster_attributes → FC с max_z, mean_z, area_km2, centroids.
      6. annotate_reference_zone_membership (Шаг 4b §3.7.1) — Reference Clean
         Zone flag for cascade Priority 1 (DNA v2.3 §1.5 invariant).
      7. build_zmin_filter (TD-0018 Kuzbass strict 4.0 vs default 3.0).
      8. validate_wind (Шаг 5b2 §3.9) — 10m primary + 850 hPa consistency.
         wind_state='axis_unknown' для всех (Stage 2 enrichment populates axis).
      9. attribute_source — nearest_source_id/distance/type.
     10. annotate_artifact_diagnostics (Шаг 5c §3.7.2) — corr_albedo +
         cluster_overlap_snow_fraction. Annotation only (NOT cascade trigger).

    Two-stage architecture preserved (Шаг 5 axis-fix Option A):
      Stage 1: this function — server-side .map().flatten()
      Stage 2: setup/enrich_plume_axes.py — client-side axis + re-validate_wind

    Args:
        orbit_image: single TROPOMI L3 CH4 orbit
        aoi: AOI geometry
        annulus_kernel: from detection_ch4.build_annulus_kernel (Шаг 4a)
        industrial_mask: ee.Image binary 1/0 (per-source-type buffer P-01.0d)
        zapovedniks_geom: ee.Geometry union of reference zones (Юганский +
            Верхнетазовский + Кузнецкий Алатау)
        era5_collection: ee.ImageCollection('ECMWF/ERA5/HOURLY')
        source_points_fc: FC after prepare_source_points_categories
        month: orbit month (1-12) — annotation only (cascade not month-dependent)
        z_min: detection threshold (default 3.0; per-region tightening via
            build_zmin_filter post-cluster)
        min_cluster_px: minimum cluster size (default 5 = ~245 km² at 7 km grid)
        apply_lat_band_correction: enable §3.5 latitude-band correction (default True)
        apply_artifact_diag: enable §3.7.2 artifact diagnostics (default True)
        wind_level / alignment_threshold_deg / min_wind_speed_ms /
            temporal_window_hours: validate_wind config
        search_radius_km: attribute_source radius (default 50 km)
    """
    target_band = TROPOMI_CH4_BAND

    # Step 0: Latitude-band correction (Algorithm v3.0.4 §3.5, Шаг 3)
    if apply_lat_band_correction:
        lat_corrected = detection_ch4.apply_latitude_band_correction(
            orbit_image, aoi
        )
        # Replace orbit's CH4 band с corrected version, preserve properties.
        # Wrap в ee.Image — copyProperties returns ee.Element generic.
        orbit_for_z = ee.Image(
            lat_corrected.select(f"{target_band}_lat_corrected")
            .rename(target_band)
            .copyProperties(orbit_image, ["system:time_start"])
        )
    else:
        orbit_for_z = orbit_image

    # Step 1: Two-condition mask (Algorithm v3.0.3 §3.6, Шаг 5a)
    proxy_mask = detection_ch4.apply_two_condition_mask(
        orbit_for_z, industrial_mask, target_band=target_band
    )

    # Step 2: Compute Z_local (Algorithm v3.0.4 §3.4.3, Шаг 4a + 5b1 + 6b1 fix)
    z_image = detection_ch4.compute_z_local(
        ee.Image(orbit_for_z),
        annulus_kernel,
        proxy_mask,
        target_band=target_band,
        annulus_count_kernel=annulus_count_kernel,  # 6b1 fix: raw count via binary kernel
    )

    # Step 3: Threshold к binary detection mask
    z_band = z_image.select("Z_local")
    detection_mask = z_band.gte(z_min).selfMask()

    # Step 4: Extract clusters (Algorithm §3.7, preserved)
    cluster_image = detection_ch4.extract_clusters(
        detection_mask, min_cluster_px=min_cluster_px, max_size=256, connectedness=8
    )

    # Step 5: Compute cluster attributes (Algorithm §3.8)
    # Path E adapter: compute_cluster_attributes expects 'z' band — alias Z_local
    # к 'z'. Use median_local as baseline_value equivalent (was primary_value
    # from compute_z_score в v2.x).
    median_local_band = z_image.select(f"{target_band}_median_local")
    z_image_for_attrs = (
        z_image.select("Z_local")
        .rename("z")
        .addBands(z_image.select(f"{target_band}_median_local"))
        .addBands(z_image.select(f"{target_band}_mad_local"))
    )
    attrs_fc = detection_ch4.compute_cluster_attributes(
        cluster_image,
        ee.Image(orbit_for_z),
        median_local_band,
        z_image_for_attrs,
        aoi,
        target_band=target_band,
        scale_m=ANALYSIS_SCALE_M,
    )

    # Step 6: Annotate reference zone membership (Algorithm §3.7.1, Шаг 4b)
    # Cascade Priority 1 federal-protected zones override (DNA v2.3 §1.5)
    attrs_fc = annotate_reference_zone_membership(attrs_fc, zapovedniks_geom)

    # Annotate orbit timestamp + month + year на every cluster
    orbit_millis = orbit_image.date().millis()
    orbit_year = orbit_image.date().get("year")
    annotated = attrs_fc.map(
        lambda feat: feat.set(
            {
                "orbit_date_millis": orbit_millis,
                "month": month,
                "year": orbit_year,
                "qa_flags": ee.List([]),  # initialize empty для downstream helpers
            }
        )
    )

    # Step 7: Per-region z_min filter (TD-0018, DNA §2.1.6)
    filtered = annotated.filter(build_zmin_filter())

    # Step 8: Wind validation (Algorithm v3.1 §3.9, Шаг 5b2)
    with_wind = detection_ch4.validate_wind(
        filtered,
        era5_collection,
        orbit_millis,
        wind_level=wind_level,
        alignment_threshold_deg=alignment_threshold_deg,
        min_wind_speed_ms=min_wind_speed_ms,
        temporal_window_hours=temporal_window_hours,
    )

    # Step 9: Source attribution (Algorithm §3.10)
    with_source = detection_ch4.attribute_source(
        with_wind, source_points_fc, search_radius_km=search_radius_km
    )

    # Step 10: Artifact diagnostics annotation (Algorithm v3.1.1 §3.7.2, Шаг 5c)
    # Pass z_image (с original 'Z_local' band), not z_image_for_attrs (renamed 'z')
    if apply_artifact_diag:
        with_artifact = annotate_artifact_diagnostics(
            with_source, z_image, orbit_millis
        )
    else:
        with_artifact = with_source

    return with_artifact


# ---------------------------------------------------------------------------
# Per-month / per-year aggregation
# ---------------------------------------------------------------------------


def process_month(
    year: int,
    month: int,
    aoi: ee.Geometry,
    annulus_kernel: ee.Kernel,
    industrial_mask: ee.Image,
    zapovedniks_geom: ee.Geometry,
    era5_collection: ee.ImageCollection,
    source_points_fc: ee.FeatureCollection,
    logger: logging.Logger,
    annulus_count_kernel: ee.Kernel | None = None,
) -> ee.FeatureCollection:
    """
    Process все orbits в given month → merged cluster FC (Path E v3.1.1).

    Server-side .map().flatten() pattern; orbit count typically 30-90 per month
    for Western Siberia AOI.

    Path E args (Шаг 6a refactor):
        annulus_kernel: from detection_ch4.build_annulus_kernel (Шаг 4a)
        industrial_mask: ee.Image binary 1/0 (per-source-type buffer P-01.0d)
        zapovedniks_geom: union zapovednik polygons (для Шаг 4b annotation)
    """
    month_start = f"{year}-{month:02d}-01"
    next_month = month + 1
    next_year = year
    if next_month > 12:
        next_month = 1
        next_year = year + 1
    month_end = f"{next_year}-{next_month:02d}-01"

    collection = (
        ee.ImageCollection(TROPOMI_CH4_COLLECTION)
        .filterDate(month_start, month_end)
        .filterBounds(aoi)
    )

    # Stage 1: server-side .map().flatten() — entire orbit pipeline lazy.
    def _per_orbit(orbit_image: ee.Image) -> ee.FeatureCollection:
        return detect_orbit_clusters(
            ee.Image(orbit_image),
            aoi=aoi,
            annulus_kernel=annulus_kernel,
            industrial_mask=industrial_mask,
            zapovedniks_geom=zapovedniks_geom,
            era5_collection=era5_collection,
            source_points_fc=source_points_fc,
            month=month,
            annulus_count_kernel=annulus_count_kernel,
        )

    orbit_list = collection.toList(collection.size())
    fcs = orbit_list.map(_per_orbit)
    merged = ee.FeatureCollection(fcs).flatten()

    logger.info("  M%02d %s..%s — processed", month, month_start, month_end)
    return merged


def process_year(
    year: int,
    provenance,  # type: ignore[no-untyped-def]
    overrides: list,
    logger: logging.Logger,
    *,
    aoi_bbox: tuple = AOI_BBOX,
    months_subset: list[int] | None = None,
) -> ee.FeatureCollection:
    """
    Build annual CH4 event catalog for given year.

    Returns ee.FeatureCollection (lazy — Export.table.toAsset materializes).

    Args:
        year: target year (2019..2025)
        provenance: Provenance object computed at process start (passed
            by reference; no recomputation downstream)
        overrides: list of manual override dicts (от load_event_overrides)
        logger: configured logger
        aoi_bbox: AOI lat/lon bbox tuple
        months_subset: optional list of months [1..12] для partial processing
            (default — all 12)
    """
    aoi = ee.Geometry.Rectangle(list(aoi_bbox))
    # Path E (v3.1.1): all warm-season months processed; no multi-year baseline
    # restriction (REFERENCE_AVAILABLE_MONTHS was constraint for build_hybrid_background
    # which is removed). Default warm-season list matches REFERENCE_AVAILABLE_MONTHS
    # because TROPOMI L3 winter coverage physical limit (TD-0034) applies regardless.
    available_months = REFERENCE_AVAILABLE_MONTHS
    months = months_subset or available_months
    months = [m for m in months if m in available_months]
    if not months:
        logger.error(
            "No requested months overlap warm-season availability %s — exiting",
            available_months,
        )
        return ee.FeatureCollection([])

    logger.info("=" * 60)
    logger.info("Processing year %d (Path E v3.1.1, %d months: %s)", year, len(months), months)

    # Path E annulus kernels — built ONCE per year (Algorithm v3.0.4 §3.4.2).
    # DNA §2.1.5 compliant: ee.Kernel.fixed с explicit weight matrix.
    # Two kernels needed (Шаг 6b1 P-02.0c fix):
    #   * annulus_kernel — normalized weights (для mean/median/MAD)
    #   * annulus_count_kernel — binary 0/1 weights (для raw sample count)
    annulus_kernel = detection_ch4.build_annulus_kernel(
        inner_km=detection_ch4.ANNULUS_INNER_KM_DEFAULT,
        outer_km=detection_ch4.ANNULUS_OUTER_KM_DEFAULT,
        pixel_size_km=detection_ch4.TROPOMI_L3_PIXEL_SIZE_KM,
    )
    annulus_count_kernel = detection_ch4.build_annulus_count_kernel(
        inner_km=detection_ch4.ANNULUS_INNER_KM_DEFAULT,
        outer_km=detection_ch4.ANNULUS_OUTER_KM_DEFAULT,
        pixel_size_km=detection_ch4.TROPOMI_L3_PIXEL_SIZE_KM,
    )
    logger.info(
        "Built annulus kernels (normalized + binary count): inner=%d km outer=%d km",
        detection_ch4.ANNULUS_INNER_KM_DEFAULT,
        detection_ch4.ANNULUS_OUTER_KM_DEFAULT,
    )

    # Industrial mask (per-source-type buffer P-01.0d / TD-0027) — Algorithm §3.6.4
    industrial_mask = ee.Image(INDUSTRIAL_MASK_ASSET)
    logger.info("Industrial mask loaded: %s", INDUSTRIAL_MASK_ASSET)

    # Reference zones (zapovedniks union) — для annotate_reference_zone_membership (Шаг 4b)
    try:
        reference_zones_fc = ee.FeatureCollection(REFERENCE_ZONES_ASSET)
        n_zones = reference_zones_fc.size().getInfo()
        zapovedniks_geom = reference_zones_fc.geometry()
        logger.info("Reference zones FC loaded: %d zones", n_zones)
    except Exception as exc:  # pragma: no cover — runtime path
        logger.warning("Reference zones FC unavailable (%s) — using empty geometry", exc)
        zapovedniks_geom = ee.Geometry.MultiPolygon([])

    # ERA5 collection (filter happens per-orbit inside validate_wind)
    era5_collection = ee.ImageCollection(ERA5_HOURLY_COLLECTION)

    # Source points FC — preprocess к add source_type_category (Algorithm §3.10)
    raw_source_points = ee.FeatureCollection(SOURCE_POINTS_ASSET)
    source_points_fc = prepare_source_points_categories(raw_source_points)

    # Process each month
    month_fcs = []
    for m in months:
        month_fc = process_month(
            year=year,
            month=m,
            aoi=aoi,
            annulus_kernel=annulus_kernel,
            annulus_count_kernel=annulus_count_kernel,
            industrial_mask=industrial_mask,
            zapovedniks_geom=zapovedniks_geom,
            era5_collection=era5_collection,
            source_points_fc=source_points_fc,
            logger=logger,
        )
        month_fcs.append(month_fc)

    annual_fc = ee.FeatureCollection(month_fcs).flatten()

    # TD-0017 transboundary qa annotation
    annual_fc = annotate_transboundary_qa(annual_fc, era5_collection)

    # TD-0021 zone-boundary qa annotation
    annual_fc = annotate_zone_boundary_qa(annual_fc)

    # Manual overrides (Algorithm §6)
    if overrides:
        logger.info("Applying %d manual overrides", len(overrides))
        annual_fc = apply_event_overrides(annual_fc, overrides)

    # Шаг 6: Algorithm §3.12 5-priority classification cascade
    annual_fc = apply_classification(annual_fc)

    # Attach provenance к each event (DNA §2.1 запрет 12 — every Feature has
    # params_hash, config_id, run_id, algorithm_version, build_date)
    prov_props = provenance.to_asset_properties()
    annual_fc = annual_fc.map(lambda f: f.set(prov_props))

    # Шаг 5 launch fix: convert qa_flags list к string для GEE Export
    # compatibility (Export.table.toAsset rejects List<Object>; см.
    # encode_qa_flags_for_export docstring). Last step before return —
    # all helpers that operate на qa_flags must run BEFORE this point.
    annual_fc = encode_qa_flags_for_export(annual_fc)

    return annual_fc


# ---------------------------------------------------------------------------
# Export task submission
# ---------------------------------------------------------------------------


def submit_export(
    fc: ee.FeatureCollection,
    asset_id: str,
    provenance,  # type: ignore[no-untyped-def]
    logger: logging.Logger,
    *,
    description: str | None = None,
) -> ee.batch.Task:
    """
    Submit Export.table.toAsset для catalog FC.

    Asset metadata gets full Provenance (DNA §2.1 запрет 12). Per-month
    sub-tasks (Šаг 6b2 P-02.0c) — single year exceeds GEE 12h batch limit;
    monthly chunks ~1-2h each fit comfortably.
    """
    description = description or f"ch4_event_catalog_{asset_id.split('/')[-1]}"
    task = ee.batch.Export.table.toAsset(
        collection=fc,
        description=description,
        assetId=asset_id,
        # Note: Export.table.toAsset doesn't accept properties param;
        # asset metadata set post-completion via setAssetProperties OR
        # baked-in via .map(set provenance) at FC level. Latter approach
        # used here — every Feature carries provenance.
    )
    task.start()
    logger.info("Submitted: %s (task_id=%s)", asset_id, task.id)
    return task


# ---------------------------------------------------------------------------
# Per-month chunked submission (Šаг 6b2 P-02.0c)
# ---------------------------------------------------------------------------


def submit_monthly_chunk(
    year: int,
    month: int,
    overrides: list,
    config_preset: str,
    logger: logging.Logger,
    dry_run: bool = False,
) -> ee.batch.Task | None:
    """
    Submit single-month Export task for year/month.

    Asset name: events_<YEAR>_M<NN>_intermediate
    Each task ~1-2h wallclock, fits GEE 12h batch limit.
    """
    config = build_event_config(year, config_preset=config_preset)
    prov = compute_provenance(
        config=config,
        config_id=config_preset,
        period=f"{year}_M{month:02d}",
        algorithm_version="2.3.2",
        rna_version="1.2",
    )
    asset_id = INTERMEDIATE_MONTHLY_TEMPLATE.format(year=year, month=month)
    logger.info("Monthly chunk: year=%d month=%02d asset=%s", year, month, asset_id)
    logger.info("  run_id=%s params_hash=%s", prov.run_id, prov.params_hash[:8])

    # Build single-month FC (months_subset=[month])
    monthly_fc = process_year(
        year=year,
        provenance=prov,
        overrides=overrides,
        logger=logger,
        months_subset=[month],
    )

    if dry_run:
        logger.info("  Dry-run: lazy FC graph constructed (no submit)")
        return None

    # Empty-FC pre-check (Šаг 6b2 round-2 fix 2026-05-10):
    # Without this, empty months waste GEE batch quota — observed M01/M03/M09/M10
    # 2024 produced 0 events each, Export failed «Table is empty» after wasting
    # ~64k EECU-seconds per task. Pre-check timeout is gracefully handled.
    #
    # Šаг 9 resume bypass (2026-05-20): full-AOI .size().getInfo() consistently
    # hangs >20 min on restricted-mode quota state (96%+ monthly used). Setting
    # ORCHESTRATOR_SKIP_PRECHECK=1 bypasses pre-check entirely; empty months will
    # be detected at Export stage с known waste cost (~15-20 EECU-hr each). See
    # TD-0045 в KNOWN_TODOS.md for v1.1 cheaper pre-check refinement.
    import os
    skip_precheck = os.environ.get("ORCHESTRATOR_SKIP_PRECHECK", "0") == "1"
    if skip_precheck:
        logger.info("  Pre-check BYPASSED (ORCHESTRATOR_SKIP_PRECHECK=1)")
        n_events = -1
    else:
        try:
            n_events = monthly_fc.size().getInfo()
            logger.info("  Pre-check FC size: %d events", n_events)
        except Exception as exc:
            logger.warning("  Could not pre-check FC size (%s) — proceeding к submit", exc)
            n_events = -1  # unknown; proceed but log
    if n_events == 0:
        logger.warning(
            "  Year %d M%02d produced 0 events. Skipping Export to avoid empty asset",
            year, month,
        )
        write_provenance_log(
            prov,
            status="SKIPPED_EMPTY",
            gas="CH4",
            period=f"{year}_M{month:02d}",
            asset_id=asset_id,
            extra={
                "reason": "zero_events_after_pipeline",
                "target_year": year,
                "target_month": month,
                "n_overrides": len(overrides),
            },
        )
        return None

    # STARTED log
    write_provenance_log(
        prov,
        status="STARTED",
        gas="CH4",
        period=f"{year}_M{month:02d}",
        asset_id=asset_id,
        extra={
            "phase": config["phase"],
            "operation": "ch4_event_catalog_build_monthly",
            "target_year": year,
            "target_month": month,
            "n_overrides": len(overrides),
            "pre_check_n_events": n_events,
        },
    )

    try:
        task = submit_export(
            monthly_fc, asset_id, prov, logger,
            description=f"ch4_M{month:02d}_{year}_intermediate",
        )
        write_provenance_log(
            prov,
            status="SUBMITTED",
            gas="CH4",
            period=f"{year}_M{month:02d}",
            asset_id=asset_id,
            extra={"task_id": task.id, "n_overrides": len(overrides)},
        )
        return task
    except Exception as exc:
        logger.error("Submit failed for %d-M%02d: %s", year, month, exc)
        write_provenance_log(
            prov,
            status="FAILED",
            gas="CH4",
            period=f"{year}_M{month:02d}",
            asset_id=asset_id,
            extra={"error": str(exc)},
        )
        return None


# ---------------------------------------------------------------------------
# Combine monthly intermediates → annual intermediate (Šаг 6b2 P-02.0c)
# ---------------------------------------------------------------------------


def combine_monthly_intermediates(
    year: int,
    config_preset: str,
    logger: logging.Logger,
    dry_run: bool = False,
) -> ee.batch.Task | None:
    """
    Combine per-month intermediate FCs → annual intermediate.

    Lists existing events_<YEAR>_M<NN>_intermediate assets (skip non-existent
    if some month produced 0 events / was not submitted). Merges via
    ee.FeatureCollection list flatten. Submits Export → events_<YEAR>_intermediate.

    Stage 2 enrich_plume_axes.py reads the annual intermediate as before — no
    Stage 2 changes needed.
    """
    from rca.detection_helpers import REFERENCE_AVAILABLE_MONTHS  # local import OK

    available_intermediates = []
    for m in REFERENCE_AVAILABLE_MONTHS:
        asset_id = INTERMEDIATE_MONTHLY_TEMPLATE.format(year=year, month=m)
        try:
            ee.data.getAsset(asset_id)
            available_intermediates.append((m, asset_id))
            logger.info("  Found: M%02d -> %s", m, asset_id)
        except Exception:
            logger.warning("  MISSING: M%02d -> %s (skipping)", m, asset_id)

    if not available_intermediates:
        logger.error("No monthly intermediates found for year %d — aborting", year)
        return None

    logger.info("Combining %d monthly intermediates -> annual intermediate", len(available_intermediates))

    # Merge FCs via list flatten — preserves all features, no de-duplication
    monthly_fcs = [ee.FeatureCollection(asset_id) for _, asset_id in available_intermediates]
    combined_fc = ee.FeatureCollection(monthly_fcs).flatten()

    annual_asset_id = INTERMEDIATE_ASSET_TEMPLATE.format(year=year)
    logger.info("Target annual asset: %s", annual_asset_id)

    # Reuse provenance approach — combine step records its own provenance
    config = build_event_config(year, config_preset=config_preset)
    prov = compute_provenance(
        config=config,
        config_id=f"{config_preset}_combine",
        period=f"{year}_combined",
        algorithm_version="2.3.2",
        rna_version="1.2",
    )

    # Re-attach combine-step provenance к each feature (overwrites monthly prov)
    prov_props = prov.to_asset_properties()
    combined_fc = combined_fc.map(lambda f: f.set(prov_props))

    if dry_run:
        logger.info("Dry-run: combine graph constructed (no submit)")
        return None

    # STARTED log
    write_provenance_log(
        prov,
        status="STARTED",
        gas="CH4",
        period=f"{year}_combined",
        asset_id=annual_asset_id,
        extra={
            "operation": "ch4_combine_monthly_intermediates",
            "target_year": year,
            "n_monthly_assets": len(available_intermediates),
            "monthly_assets": [a for _, a in available_intermediates],
        },
    )

    try:
        task = submit_export(
            combined_fc, annual_asset_id, prov, logger,
            description=f"ch4_combine_{year}_intermediate",
        )
        write_provenance_log(
            prov,
            status="SUBMITTED",
            gas="CH4",
            period=f"{year}_combined",
            asset_id=annual_asset_id,
            extra={"task_id": task.id, "n_monthly_assets": len(available_intermediates)},
        )
        return task
    except Exception as exc:
        logger.error("Combine submit failed for year %d: %s", year, exc)
        write_provenance_log(
            prov,
            status="FAILED",
            gas="CH4",
            period=f"{year}_combined",
            asset_id=annual_asset_id,
            extra={"error": str(exc)},
        )
        return None


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build annual CH4 plume event catalog (P-02.0a Шаг 5)"
    )
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        help="Single year к plan (no launch); shows pipeline summary",
    )
    parser.add_argument(
        "--launch-year",
        type=int,
        default=None,
        help="Single year к actually submit к GEE batch (requires auth + assets)",
    )
    parser.add_argument(
        "--full-launch",
        action="store_true",
        help="Submit все 7 years (2019..2025); BLOCKED unless --i-know-what-im-doing",
    )
    parser.add_argument(
        "--i-know-what-im-doing",
        action="store_true",
        help="Acknowledge full 7-year launch is expensive (3-5h × 7 years = wall-clock days)",
    )
    parser.add_argument(
        "--months", type=str, default=None, help="Comma-separated months 1-12 (default all)"
    )
    parser.add_argument(
        "--month",
        type=int,
        default=None,
        help="Single-month chunk mode (Šаг 6b2 P-02.0c): submit ONE month as separate "
        "Export task to events_<YEAR>_M<NN>_intermediate. Used to fit GEE 12h batch "
        "limit. Combine via --combine-monthly после all monthly tasks SUCCEEDED.",
    )
    parser.add_argument(
        "--combine-monthly",
        type=int,
        default=None,
        metavar="YYYY",
        help="Combine existing per-month intermediates (events_<YYYY>_M<NN>_intermediate) "
        "→ annual intermediate (events_<YYYY>_intermediate). Run после all monthly "
        "Stage 1 tasks SUCCEEDED. Reads asset list, merges, applies overrides + classification "
        "+ encode_qa_flags, exports.",
    )
    parser.add_argument(
        "--launch-monthly-chunks",
        type=int,
        default=None,
        metavar="YYYY",
        help="Submit ALL warm-season months as separate Export tasks (Option A batching). "
        "Equivalent к 7 invocations с --month flag. Each task ~1-2h, fits 12h limit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build FC graph + print summary, but не submit Export task",
    )
    parser.add_argument(
        "--config-preset", type=str, default="default", help="Configuration preset name"
    )
    parser.add_argument(
        "--ee-project", type=str, default=PROJECT_ID, help="GEE project ID for ee.Initialize"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logger = setup_logger()

    # Validate args
    if args.full_launch and not args.i_know_what_im_doing:
        logger.error("--full-launch requires --i-know-what-im-doing (7 years × 3-5h compute)")
        return 2

    have_action = (
        args.year is not None
        or args.launch_year is not None
        or args.full_launch
        or args.month is not None
        or args.combine_monthly is not None
        or args.launch_monthly_chunks is not None
    )
    if not have_action:
        logger.info("Usage:")
        logger.info("  --year YYYY                  plan single year (no launch)")
        logger.info("  --launch-year YYYY           launch single-year Export.toAsset (DEPRECATED — exceeds 12h)")
        logger.info("  --launch-monthly-chunks YYYY launch 7 monthly Exports for year (Option A, recommended)")
        logger.info("  --month N --launch-year YYYY launch single-month Export (manual chunk)")
        logger.info("  --combine-monthly YYYY       combine monthly intermediates → annual intermediate")
        logger.info("  --full-launch                launch 7 years (BLOCKED unless --i-know-what-im-doing)")
        logger.info("See --help для full options")
        return 0

    # Initialize EE
    try:
        ee.Initialize(project=args.ee_project)
        logger.info("EE initialized: project=%s", args.ee_project)
    except Exception as exc:
        logger.error("ee.Initialize() failed: %s", exc)
        return 1

    # Manual overrides (loaded once, used in all modes)
    overrides = load_event_overrides(EVENT_OVERRIDES_PATH)
    logger.info("Manual overrides loaded: %d entries", len(overrides))

    # ----- Mode: combine monthly intermediates → annual intermediate -----
    if args.combine_monthly is not None:
        year = args.combine_monthly
        logger.info("=" * 60)
        logger.info("Combine monthly intermediates -> annual (year=%d)", year)
        logger.info("=" * 60)
        task = combine_monthly_intermediates(
            year=year,
            config_preset=args.config_preset,
            logger=logger,
            dry_run=args.dry_run,
        )
        if not args.dry_run and task is None:
            return 1
        return 0

    # ----- Mode: launch all warm-season months as separate Exports -----
    if args.launch_monthly_chunks is not None:
        from rca.detection_helpers import REFERENCE_AVAILABLE_MONTHS  # local import OK
        year = args.launch_monthly_chunks
        logger.info("=" * 60)
        logger.info("Launch monthly chunks: year=%d, months=%s", year, REFERENCE_AVAILABLE_MONTHS)
        logger.info("Each task ~1-2h wallclock, fits GEE 12h batch limit")
        logger.info("=" * 60)
        submitted = []
        for m in REFERENCE_AVAILABLE_MONTHS:
            logger.info("\n-- Month M%02d --", m)
            task = submit_monthly_chunk(
                year=year,
                month=m,
                overrides=overrides,
                config_preset=args.config_preset,
                logger=logger,
                dry_run=args.dry_run,
            )
            if task:
                submitted.append((m, task.id))
        logger.info("\n" + "=" * 60)
        logger.info("Submitted %d/%d monthly tasks", len(submitted), len(REFERENCE_AVAILABLE_MONTHS))
        for m, tid in submitted:
            logger.info("  M%02d: %s", m, tid)
        logger.info("\nMonitor tasks; after все SUCCEEDED run: --combine-monthly %d", year)
        return 0

    # ----- Mode: single-month chunk (manual) -----
    if args.month is not None:
        if args.launch_year is None and args.year is None:
            logger.error("--month requires --launch-year YYYY (submit) or --year YYYY (plan)")
            return 2
        year = args.launch_year or args.year
        logger.info("=" * 60)
        logger.info("Single-month chunk: year=%d month=%d", year, args.month)
        logger.info("=" * 60)
        task = submit_monthly_chunk(
            year=year,
            month=args.month,
            overrides=overrides,
            config_preset=args.config_preset,
            logger=logger,
            dry_run=args.dry_run or (args.launch_year is None),
        )
        if not args.dry_run and args.launch_year is not None and task is None:
            return 1
        return 0

    # ----- Mode: single-year (legacy, exceeds 12h GEE limit, deprecated) -----
    if args.full_launch:
        years = list(range(2019, 2026))
    elif args.launch_year is not None:
        years = [args.launch_year]
    else:
        years = [args.year]

    if args.launch_year is not None or args.full_launch:
        logger.warning("=" * 60)
        logger.warning("WARNING: --launch-year submits SINGLE-YEAR full-warm-season task")
        logger.warning("Exceeds GEE 12h batch limit (Šаг 6b2 P-02.0c 2026-05-09 verified)")
        logger.warning("Use --launch-monthly-chunks YYYY instead для production catalog")
        logger.warning("=" * 60)

    months_subset = [int(m.strip()) for m in args.months.split(",")] if args.months else None

    # Process each year sequentially (per-year batch task)
    for year in years:
        logger.info("\n" + "=" * 60)
        logger.info("Year %d", year)
        logger.info("=" * 60)

        # Canonical Provenance — computed ONCE per year run (config differs by year)
        config = build_event_config(year, config_preset=args.config_preset)
        prov = compute_provenance(
            config=config,
            config_id=args.config_preset,
            period=f"2019_{year}",
            algorithm_version="2.3.2",
            rna_version="1.2",
        )
        logger.info(
            "Provenance: run_id=%s params_hash=%s",
            prov.run_id,
            prov.params_hash[:8],
        )

        asset_id = INTERMEDIATE_ASSET_TEMPLATE.format(year=year)
        logger.info("Target asset: %s", asset_id)

        # Build lazy FC (no compute yet — Export materializes)
        annual_fc = process_year(
            year=year,
            provenance=prov,
            overrides=overrides,
            logger=logger,
            months_subset=months_subset,
        )

        if args.dry_run:
            logger.info("Dry-run: Lazy FC graph constructed (not submitted)")
            logger.info("FC summary: lazy graph; getInfo() skipped to avoid full compute")
            continue

        # Submit Export
        if args.launch_year is None and not args.full_launch:
            logger.info("--year mode: plan only (no submit). Use --launch-year к actually run.")
            continue

        # GPT review #3 C-2 fix: empty FC guard — don't waste batch quota on
        # zero-event year (would create empty asset). Happens when months_subset
        # filtered out все available reference months.
        try:
            n_events = annual_fc.size().getInfo()
        except Exception as exc:
            logger.warning("Could not pre-check FC size (%s) — proceeding к submit", exc)
            n_events = -1  # unknown; proceed but log
        if n_events == 0:
            logger.error(
                "Year %d produced 0 events (likely months filtered out OR detection "
                "found nothing). Skipping export to avoid empty asset.",
                year,
            )
            write_provenance_log(
                prov,
                status="SKIPPED_EMPTY",
                gas="CH4",
                period=f"2019_{year}",
                asset_id=asset_id,
                extra={
                    "reason": "zero_events_after_pipeline",
                    "n_overrides": len(overrides),
                },
            )
            continue

        # STARTED log
        write_provenance_log(
            prov,
            status="STARTED",
            gas="CH4",
            period=f"2019_{year}",
            asset_id=asset_id,
            extra={
                "phase": config["phase"],
                "operation": "ch4_event_catalog_build",
                "target_year": year,
                "n_overrides": len(overrides),
            },
        )

        try:
            task = submit_export(annual_fc, asset_id, prov, logger)
            logger.info("Year %d task submitted: %s", year, task.id)
            # SUCCEEDED log при submit success — actual completion polled
            # separately (orchestrator не waits — single-year task can be
            # 30+ min; user runs --combine-only после)
            write_provenance_log(
                prov,
                status="SUBMITTED",
                gas="CH4",
                period=f"2019_{year}",
                asset_id=asset_id,
                extra={
                    "task_id": task.id,
                    "n_overrides": len(overrides),
                },
            )
        except Exception as exc:
            logger.error("Submit failed for year %d: %s", year, exc)
            write_provenance_log(
                prov,
                status="FAILED",
                gas="CH4",
                period=f"2019_{year}",
                asset_id=asset_id,
                extra={"error": str(exc)},
            )
            return 1

    logger.info("\nDone. Use Tasks Manager (https://code.earthengine.google.com/tasks) к monitor.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
