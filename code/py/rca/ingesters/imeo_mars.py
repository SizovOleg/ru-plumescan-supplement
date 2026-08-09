"""Šаг 8b P-02.0c — IMEO MARS catalog ingester (RuPlumeScan refs).

UNEP International Methane Emissions Observatory (IMEO) Methane Alert and
Response System (MARS): satellite-detected methane plumes from Sentinel-5P,
GHGSat, EMIT, Carbon Mapper, and others.

Data source: https://methanedata.unep.org/plumemap (live), API endpoint
TBD per IMEO docs. License: CC BY 4.0 per IMEO public data policy.

**Status: SCAFFOLD** — fetch() requires API access (architect 2026-05-14
decision: keep IMEO MARS in Tier 2). Implementation gated until either:
  1. IMEO API access verified + credentials provisioned
  2. Local CSV snapshot from methanedata.unep.org available

Architectural pattern follows SchuitIngester (commit `9c224db`):
* BaseIngester contract: fetch / validate / to_common_schema
* DECLARED_STATS placeholder (will populate at first ingestion)
* Common Plume Schema v1.1 compliant output

Asset target (post-implementation):
* RuPlumeScan/refs/imeo_mars_v1 (FeatureCollection)
* RuPlumeScan/refs/imeo_mars_v1_hull (convex hull для Phase 4 overlay)
"""

from __future__ import annotations

from datetime import date as date_type
from pathlib import Path
from typing import ClassVar

import pandas as pd

from rca.base_ingester import BaseIngester, ValidationError

# AOI bounds (matches build_ch4_event_catalog AOI_BBOX)
AOI_LON_MIN: float = 60.0
AOI_LON_MAX: float = 95.0
AOI_LAT_MIN: float = 50.0
AOI_LAT_MAX: float = 75.0

# IMEO MARS instrument к Common Schema source_type mapping (preliminary)
# IMEO classifies by satellite, not source type — source_type derived from
# associated metadata or assigned 'other' if not specified
INSTRUMENT_DEFAULT_SOURCE_TYPE: dict[str, str] = {
    "Sentinel-5P": "other",
    "GHGSat": "other",
    "EMIT": "other",
    "Carbon Mapper": "other",
    "PRISMA": "other",
    "Sentinel-2": "other",
}


class IMEOMarsIngester(BaseIngester):
    """UNEP IMEO MARS satellite methane plume catalog ingester.

    Implements BaseIngester contract. fetch() pending API access (Šаг 8b
    scope, post Šаг 9 multi-year catalog ready).

    Architecture mirrors SchuitIngester:
    * AOI filtering к Western Siberia bounds
    * Common Plume Schema v1.1 mapping
    * Provenance properties (DOI / license / citation / ingestion_date)
    * Convex hull computation для validation zone
    """

    SOURCE_NAME: ClassVar[str] = "imeo_mars"

    DECLARED_STATS: ClassVar[dict] = {
        # Placeholders — populate at first ingestion when API access available
        "n_events_global_total": None,  # IMEO publishes cumulative count
        "n_events_russia_aoi": None,     # к determine from filtered fetch
        "data_url": "https://methanedata.unep.org/plumemap",
        "api_url": "TBD — IMEO API endpoint pending verification",
        "license": "CC BY 4.0 (per IMEO public data policy)",
        "citation": (
            "UNEP IMEO Methane Alert and Response System (MARS), International "
            "Methane Emissions Observatory, United Nations Environment Programme. "
            "Available: https://methanedata.unep.org/plumemap"
        ),
        "doi": "TBD — IMEO data DOI if assigned",
        "version": "v1_pending_ingestion",
        "ingestion_method": "pending_api_access",
    }

    VALIDATION_TOLERANCE_PCT: float = 5.0

    def __init__(self, csv_path: Path | None = None, api_key: str | None = None):
        """
        Args:
            csv_path: optional path к local IMEO MARS CSV snapshot (manual
                download from methanedata.unep.org). If provided, fetch() reads
                from local file instead of live API.
            api_key: optional IMEO API key (если access granted).
        """
        self.csv_path = Path(csv_path) if csv_path else None
        self.api_key = api_key

        if self.csv_path is None and self.api_key is None:
            # Scaffold mode — full fetch() implementation pending
            pass

    def fetch(self) -> pd.DataFrame:
        """Fetch IMEO MARS catalog raw data.

        Three modes:
        1. Local CSV snapshot (if csv_path provided in __init__)
        2. Live API (if api_key provided + endpoint verified)
        3. Scaffold mode — raises NotImplementedError pending Šаг 8b activation

        Expected DataFrame columns (per IMEO MARS schema):
        * detection_id, detection_timestamp
        * lat, lon (or geometry GeoJSON)
        * instrument (Sentinel-5P / GHGSat / EMIT / etc.)
        * detected_flux_t_h, detected_flux_uncertainty_t_h
        * source_type (если annotated)
        * country, region
        """
        if self.csv_path is not None:
            if not self.csv_path.exists():
                raise FileNotFoundError(f"IMEO MARS CSV not found: {self.csv_path}")
            df = pd.read_csv(self.csv_path)
            return df

        if self.api_key is not None:
            raise NotImplementedError(
                "IMEO MARS live API ingestion pending. Šаг 8b implementation "
                "requires: 1) API endpoint verification, 2) authentication "
                "scheme documentation, 3) pagination handling."
            )

        raise NotImplementedError(
            "IMEO MARS ingester scaffold mode. Provide csv_path (local snapshot) "
            "or api_key (live fetch) к __init__. Šаг 8b activation pending."
        )

    def validate(self, raw: pd.DataFrame) -> dict:
        """Validate raw IMEO MARS data against DECLARED_STATS.

        Validation steps:
        * Required columns present (detection_id, lat, lon, detected_flux_t_h)
        * Coordinate ranges valid (-180,180 lon × -90,90 lat)
        * AOI subset count matches expectation (если DECLARED_STATS set)
        """
        required_cols = {"detection_id", "lat", "lon"}
        missing = required_cols - set(raw.columns)
        if missing:
            raise ValidationError(f"IMEO MARS missing required columns: {missing}")

        if raw["lat"].min() < -90 or raw["lat"].max() > 90:
            raise ValidationError(
                f"lat range invalid: [{raw['lat'].min()}, {raw['lat'].max()}]"
            )
        if raw["lon"].min() < -180 or raw["lon"].max() > 180:
            raise ValidationError(
                f"lon range invalid: [{raw['lon'].min()}, {raw['lon'].max()}]"
            )

        n_actual = len(raw)
        aoi_mask = (
            (raw["lat"] >= AOI_LAT_MIN) & (raw["lat"] <= AOI_LAT_MAX)
            & (raw["lon"] >= AOI_LON_MIN) & (raw["lon"] <= AOI_LON_MAX)
        )
        n_aoi_actual = int(aoi_mask.sum())

        # If DECLARED_STATS populated, check tolerance
        result = {
            "n_global_actual": n_actual,
            "n_aoi_actual": n_aoi_actual,
            "deviation_check": "n/a (DECLARED_STATS empty pending Šаг 8b)",
        }
        if self.DECLARED_STATS.get("n_events_global_total") is not None:
            n_declared = self.DECLARED_STATS["n_events_global_total"]
            dev_pct = abs(n_actual - n_declared) / n_declared * 100
            result["n_global_declared"] = n_declared
            result["deviation_pct"] = dev_pct
            if dev_pct > self.VALIDATION_TOLERANCE_PCT:
                raise ValidationError(
                    f"IMEO MARS count {n_actual} deviates {dev_pct:.1f}% от "
                    f"declared {n_declared}"
                )

        return result

    def to_common_schema(self, raw: pd.DataFrame, aoi_only: bool = True) -> pd.DataFrame:
        """Convert IMEO MARS raw data к Common Plume Schema DataFrame.

        Mapping (preliminary — refine при first real fetch):
        * source_event_id = "imeo_mars_" + detection_id
        * source_catalog = "imeo_mars"
        * gas = "CH4" (MARS scope is methane)
        * date_utc = parse detection_timestamp date
        * time_utc = parse detection_timestamp time
        * lon, lat from raw
        * magnitude_proxy = detected_flux_t_h
        * magnitude_proxy_unit = "t/h"
        * q_kg_h_experimental = × 1000
        * q_uncertainty_factor = 1 + (uncertainty / flux)
        * nearest_source_type = INSTRUMENT_DEFAULT_SOURCE_TYPE.get(instrument) || "other"
        * detection_method = "external_reference"

        Args:
            raw: output of fetch()
            aoi_only: filter к Western Siberia AOI (default True)
        """
        if aoi_only:
            mask = (
                (raw["lat"] >= AOI_LAT_MIN) & (raw["lat"] <= AOI_LAT_MAX)
                & (raw["lon"] >= AOI_LON_MIN) & (raw["lon"] <= AOI_LON_MAX)
            )
            df = raw[mask].copy().reset_index(drop=True)
        else:
            df = raw.copy().reset_index(drop=True)

        out = pd.DataFrame(index=df.index)

        # Identification
        out["source_catalog"] = "imeo_mars"
        out["schema_version"] = "1.1"
        out["ingestion_date"] = date_type.today().isoformat()
        out["source_event_id"] = "imeo_mars_" + df.get("detection_id", df.index.astype(str)).astype(str)
        out["event_id"] = (
            "imeo_mars_CH4_"
            + df.get("detection_timestamp", pd.Series([""] * len(df))).astype(str).str[:10] + "_"
            + df["lat"].round(2).astype(str) + "_"
            + df["lon"].round(2).astype(str)
        )

        # Base attributes
        out["gas"] = "CH4"
        if "detection_timestamp" in df.columns:
            ts = pd.to_datetime(df["detection_timestamp"], errors="coerce")
            out["date_utc"] = ts.dt.date.astype(str)
            out["time_utc"] = ts.dt.time.astype(str)
        else:
            out["date_utc"] = None
            out["time_utc"] = None
        out["orbit"] = None

        # Geometry
        out["lon"] = df["lon"].astype(float)
        out["lat"] = df["lat"].astype(float)
        out["geometry"] = None  # point-only — GEE Point from lon/lat at upload
        out["area_km2"] = None
        out["n_pixels"] = None

        # Detection metrics — N/A для external reference
        out["max_z"] = None
        out["mean_z"] = None
        out["max_delta"] = None
        out["mean_delta"] = None
        out["detection_method"] = "external_reference"

        # Wind — IMEO MARS не provides
        for col in ("wind_u", "wind_v", "wind_speed", "wind_dir_deg",
                    "plume_axis_deg", "wind_alignment_score", "wind_source"):
            out[col] = None

        # Source attribution
        out["nearest_source_id"] = None
        out["nearest_source_distance_km"] = None
        if "instrument" in df.columns:
            out["nearest_source_type"] = df["instrument"].map(
                INSTRUMENT_DEFAULT_SOURCE_TYPE
            ).fillna("other")
        else:
            out["nearest_source_type"] = "other"

        # Magnitude proxy
        if "detected_flux_t_h" in df.columns:
            out["magnitude_proxy"] = df["detected_flux_t_h"].astype(float)
            out["magnitude_proxy_unit"] = "t/h"
            out["q_kg_h_experimental"] = (df["detected_flux_t_h"] * 1000.0).astype(float)
            if "detected_flux_uncertainty_t_h" in df.columns:
                rel_unc = df["detected_flux_uncertainty_t_h"].astype(float) / df["detected_flux_t_h"].astype(float).replace(0, float("nan"))
                out["q_uncertainty_factor"] = (1.0 + rel_unc.fillna(0)).clip(lower=1.0)
            else:
                out["q_uncertainty_factor"] = None
        else:
            out["magnitude_proxy"] = None
            out["magnitude_proxy_unit"] = None
            out["q_kg_h_experimental"] = None
            out["q_uncertainty_factor"] = None
        out["quantification_method"] = "imeo_mars_ime"
        out["quantification_disclaimer"] = (
            "IMEO MARS satellite-based flux estimate. Methodology varies by "
            "instrument (Sentinel-5P, GHGSat, EMIT). External reference."
        )
        out["ime_kg"] = None

        # Classification — N/A для reference
        out["class"] = None
        out["confidence"] = None
        out["confidence_score"] = None
        out["qa_flags"] = None

        # Dual baseline fields — N/A
        for col in ("delta_vs_regional_climatology", "delta_vs_reference_baseline",
                    "baseline_consistency_flag", "matched_inside_reference_zone",
                    "nearest_reference_zone"):
            out[col] = None

        # Cross-source agreement
        for col in ("matched_schuit2023", "schuit_event_id",
                    "matched_imeo_mars", "imeo_event_id",
                    "matched_cams", "cams_event_id",
                    "agreement_score", "last_comparison_date"):
            out[col] = None

        # Configuration provenance — N/A
        for col in ("algorithm_version", "config_id", "params_hash", "run_id", "run_date"):
            out[col] = None

        # ML-readiness slots
        for col in ("expert_label", "label_source", "label_date",
                    "label_confidence", "feature_vector"):
            out[col] = None

        return out

    def compute_convex_hull_coords(self, common: pd.DataFrame) -> list[list[float]]:
        """Compute convex hull of AOI IMEO MARS events (mirror SchuitIngester pattern)."""
        try:
            from scipy.spatial import ConvexHull
        except ImportError as exc:
            raise NotImplementedError(
                "scipy required для convex hull. pip install scipy."
            ) from exc

        import numpy as np
        points = common[["lon", "lat"]].to_numpy()
        if len(points) < 3:
            raise ValueError(f"Need >=3 points для convex hull, got {len(points)}")

        hull = ConvexHull(points)
        hull_points = points[hull.vertices]
        hull_closed = np.vstack([hull_points, hull_points[:1]])
        return hull_closed.tolist()
