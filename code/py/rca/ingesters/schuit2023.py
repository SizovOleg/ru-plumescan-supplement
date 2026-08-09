"""Šаг 7 P-02.0c — Schuit 2023 catalog ingester (RuPlumeScan refs).

Per architect 2026-05-14 GO closure:
* Source: Schuit et al. 2023 ACP, «Automated detection and monitoring of
  methane super-emitters using satellite data»
* DOI: 10.5194/acp-23-9071-2023
* Data: TROPOMI XCH4 plume events 2021 global (2974 events)
* License: CC BY 4.0

Asset architecture (per Algorithm v3.1.5 §3.7.1):
* `RuPlumeScan/refs/schuit2023_v1` — FeatureCollection с 123 events в AOI
  (60-95°E × 50-75°N) + Common Plume Schema properties + provenance
* `RuPlumeScan/refs/schuit2023_v1/aoi_convex_hull` — Geometry asset (separate)
  для Phase 4 Comparison Engine «inside_schuit_validation_zone» annotation

Usage:
    from rca.ingesters.schuit2023 import SchuitIngester

    ingester = SchuitIngester(csv_path=Path("data/refs/schuit2023/..."))
    raw = ingester.fetch()
    metrics = ingester.validate(raw)
    common = ingester.to_common_schema(raw)
    # upload via dataframe_to_gee_asset OR setup/ingest_schuit2023.py
"""

from __future__ import annotations

from datetime import date as date_type, datetime, time as time_type
from pathlib import Path
from typing import ClassVar

import pandas as pd

from rca.base_ingester import BaseIngester, ValidationError

# AOI bounds (Western Siberia, matches build_ch4_event_catalog AOI_BBOX)
AOI_LON_MIN: float = 60.0
AOI_LON_MAX: float = 95.0
AOI_LAT_MIN: float = 50.0
AOI_LAT_MAX: float = 75.0

# Schuit estimated_source_type → Common Schema SOURCE_TYPES mapping
SOURCE_TYPE_MAP: dict[str, str] = {
    "Coal": "coal_mine",
    "Oil": "oil_gas",
    "Gas": "oil_gas",
    "Landfill/Urban": "urban",
    "Unclassified": "other",
}


class SchuitIngester(BaseIngester):
    """Schuit et al. 2023 ACP TROPOMI methane plume catalog ingester.

    Implements BaseIngester contract:
        fetch() → raw CSV DataFrame
        validate(raw) → metrics dict; raises ValidationError if > 5% deviation
        to_common_schema(raw) → DataFrame ready for GEE FeatureCollection
    """

    SOURCE_NAME: ClassVar[str] = "schuit2023"

    DECLARED_STATS: ClassVar[dict] = {
        "n_events_global_2021": 2974,
        "n_events_russia_aoi_2021": 123,
        "doi": "10.5194/acp-23-9071-2023",
        "citation": (
            "Schuit, B.J., Maasakkers, J.D., Bijl, P., Mahapatra, G., van den Berg, "
            "A.-W., Pandey, S., Lorente, A., Borsdorff, T., Houweling, S., Varon, "
            "D.J., McKeever, J., Jervis, D., Girard, M., Irakulis-Loitxate, I., "
            "Gorroño, J., Guanter, L., Cusworth, D.H., and Aben, I.: Automated "
            "detection and monitoring of methane super-emitters using satellite "
            "data, Atmos. Chem. Phys., 23, 9071-9098, 2023."
        ),
        "data_url": "https://acp.copernicus.org/articles/23/9071/2023/",
        "license": "CC BY 4.0",
        "version": "v1_2021_subset",
        "ingestion_method": "manual_csv_download",
    }

    # Tolerance for n_events validation per DNA §2.2 / CLAUDE.md §5.5
    VALIDATION_TOLERANCE_PCT: float = 5.0

    def __init__(self, csv_path: Path):
        """
        Args:
            csv_path: path к Schuit CSV file
                (data/refs/schuit2023/Schuit_etal2023_TROPOMI_all_plume_detections_2021.csv)
        """
        self.csv_path = Path(csv_path)
        if not self.csv_path.exists():
            raise FileNotFoundError(f"Schuit CSV not found: {csv_path}")

    def fetch(self) -> pd.DataFrame:
        """Read Schuit 2021 catalog CSV. Returns raw DataFrame as-is."""
        df = pd.read_csv(self.csv_path)
        required_cols = {"date", "time_UTC", "lat", "lon", "source_rate_t/h",
                         "uncertainty_t/h", "estimated_source_type"}
        missing = required_cols - set(df.columns)
        if missing:
            raise ValueError(f"Schuit CSV missing required columns: {missing}")
        return df

    def validate(self, raw: pd.DataFrame) -> dict:
        """Verify count + coordinate ranges against DECLARED_STATS.

        Raises ValidationError if deviation > 5%.
        """
        n_actual = len(raw)
        n_declared = self.DECLARED_STATS["n_events_global_2021"]
        deviation_pct = abs(n_actual - n_declared) / n_declared * 100

        if deviation_pct > self.VALIDATION_TOLERANCE_PCT:
            raise ValidationError(
                f"Global event count {n_actual} deviates {deviation_pct:.1f}% от "
                f"declared {n_declared} (tolerance {self.VALIDATION_TOLERANCE_PCT}%)"
            )

        # AOI subset count
        aoi_mask = (
            (raw["lat"] >= AOI_LAT_MIN) & (raw["lat"] <= AOI_LAT_MAX)
            & (raw["lon"] >= AOI_LON_MIN) & (raw["lon"] <= AOI_LON_MAX)
        )
        n_aoi_actual = int(aoi_mask.sum())
        n_aoi_declared = self.DECLARED_STATS["n_events_russia_aoi_2021"]
        aoi_deviation_pct = abs(n_aoi_actual - n_aoi_declared) / n_aoi_declared * 100

        if aoi_deviation_pct > self.VALIDATION_TOLERANCE_PCT:
            raise ValidationError(
                f"AOI event count {n_aoi_actual} deviates {aoi_deviation_pct:.1f}% от "
                f"declared {n_aoi_declared}"
            )

        # Coordinate range sanity
        if raw["lat"].min() < -90 or raw["lat"].max() > 90:
            raise ValidationError(f"lat range invalid: [{raw['lat'].min()}, {raw['lat'].max()}]")
        if raw["lon"].min() < -180 or raw["lon"].max() > 180:
            raise ValidationError(f"lon range invalid: [{raw['lon'].min()}, {raw['lon'].max()}]")

        # Source type vocabulary check
        unknown_types = set(raw["estimated_source_type"].unique()) - set(SOURCE_TYPE_MAP.keys())
        if unknown_types:
            raise ValidationError(f"Unknown source types в Schuit CSV: {unknown_types}")

        return {
            "n_global_actual": n_actual,
            "n_global_declared": n_declared,
            "n_global_deviation_pct": deviation_pct,
            "n_aoi_actual": n_aoi_actual,
            "n_aoi_declared": n_aoi_declared,
            "n_aoi_deviation_pct": aoi_deviation_pct,
            "source_types_seen": sorted(raw["estimated_source_type"].unique().tolist()),
        }

    def to_common_schema(self, raw: pd.DataFrame, aoi_only: bool = True) -> pd.DataFrame:
        """Convert Schuit raw CSV к Common Plume Schema DataFrame.

        Args:
            raw: output of fetch()
            aoi_only: filter к Western Siberia AOI before conversion (default True
                — production ingest scope). False для testing / global subset.

        Returns:
            DataFrame с columns matching PlumeEvent fields (Common Schema v1.1).
            Each row passes PlumeEvent.model_validate(row.to_dict()).
        """
        if aoi_only:
            mask = (
                (raw["lat"] >= AOI_LAT_MIN) & (raw["lat"] <= AOI_LAT_MAX)
                & (raw["lon"] >= AOI_LON_MIN) & (raw["lon"] <= AOI_LON_MAX)
            )
            df = raw[mask].copy().reset_index(drop=True)
        else:
            df = raw.copy().reset_index(drop=True)

        # Build Common Schema columns — initialize с df.index for scalar broadcast
        out = pd.DataFrame(index=df.index)

        # Identification
        out["source_catalog"] = "schuit2023"
        out["schema_version"] = "1.1"
        out["ingestion_date"] = date_type.today().isoformat()

        # event_id format: <source>_<gas>_<YYYYMMDD>_<lat6>_<lon6>
        date_str = df["date"].astype(str)
        out["source_event_id"] = (
            "schuit2023_" + date_str + "_" + df.index.astype(str)
        )
        out["event_id"] = (
            "schuit2023_CH4_" + date_str + "_"
            + df["lat"].round(2).astype(str) + "_"
            + df["lon"].round(2).astype(str)
        )

        # Base attributes
        out["gas"] = "CH4"
        # Parse YYYYMMDD к date
        out["date_utc"] = pd.to_datetime(df["date"], format="%Y%m%d").dt.date.astype(str)
        # Parse HH:MM:SS к time
        out["time_utc"] = df["time_UTC"]
        out["orbit"] = None

        # Geometry (point centroids, no polygon)
        out["lon"] = df["lon"].astype(float)
        out["lat"] = df["lat"].astype(float)
        out["geometry"] = None  # point-only — GEE built from lon/lat at upload
        out["area_km2"] = None
        out["n_pixels"] = None

        # Detection metrics — N/A for external reference
        out["max_z"] = None
        out["mean_z"] = None
        out["max_delta"] = None
        out["mean_delta"] = None
        out["detection_method"] = "external_reference"

        # Wind context — not provided by Schuit catalog
        for col in ("wind_u", "wind_v", "wind_speed", "wind_dir_deg",
                    "plume_axis_deg", "wind_alignment_score", "wind_source"):
            out[col] = None

        # Source attribution — Schuit's estimated source type maps к our SOURCE_TYPES
        out["nearest_source_id"] = None
        out["nearest_source_distance_km"] = None
        out["nearest_source_type"] = df["estimated_source_type"].map(SOURCE_TYPE_MAP)

        # Magnitude proxy = Schuit's source_rate_t/h
        out["magnitude_proxy"] = df["source_rate_t/h"].astype(float)
        out["magnitude_proxy_unit"] = "t/h"

        # Quantification: Schuit provides flux estimate + uncertainty
        # Convert t/h к kg/h: × 1000
        out["q_kg_h_experimental"] = (df["source_rate_t/h"] * 1000.0).astype(float)
        # Uncertainty factor: uncertainty / rate (e.g. 16/32 = 0.5 → multiplicative factor 1.5)
        # Pydantic requires >= 1.0; compute as 1.0 + relative_uncertainty
        rel_unc = df["uncertainty_t/h"].astype(float) / df["source_rate_t/h"].astype(float)
        out["q_uncertainty_factor"] = (1.0 + rel_unc).clip(lower=1.0)
        out["quantification_method"] = "schuit2023_ime_pbl"
        out["quantification_disclaimer"] = (
            "Schuit 2023 IME-PBL quantification per Varon et al. 2018 framework. "
            "Uncertainty factor 1+(unc_t/h / rate_t/h). External reference."
        )
        out["ime_kg"] = None

        # Classification — not provided by Schuit catalog
        out["class"] = None  # use alias, NOT class_
        out["confidence"] = None
        out["confidence_score"] = None
        out["qa_flags"] = None

        # Dual baseline anomaly fields — not applicable for reference catalog
        for col in ("delta_vs_regional_climatology", "delta_vs_reference_baseline",
                    "baseline_consistency_flag", "matched_inside_reference_zone",
                    "nearest_reference_zone"):
            out[col] = None

        # Cross-source agreement (filled by Comparison Engine later)
        for col in ("matched_schuit2023", "schuit_event_id",
                    "matched_imeo_mars", "imeo_event_id",
                    "matched_cams", "cams_event_id",
                    "agreement_score", "last_comparison_date"):
            out[col] = None

        # Configuration provenance — N/A for reference (only required для source_catalog="ours")
        for col in ("algorithm_version", "config_id", "params_hash", "run_id", "run_date"):
            out[col] = None

        # ML-readiness slots
        for col in ("expert_label", "label_source", "label_date",
                    "label_confidence", "feature_vector"):
            out[col] = None

        return out

    def compute_convex_hull_coords(self, common: pd.DataFrame) -> list[list[float]]:
        """Compute convex hull of AOI Schuit events для Phase 4 «validation zone».

        Returns: list of [lon, lat] coordinate pairs forming convex hull polygon
        (closed — last point == first). Use for GEE Geometry.Polygon construction.

        Algorithm: scipy.spatial.ConvexHull on (lon, lat) point cloud.
        """
        try:
            from scipy.spatial import ConvexHull
        except ImportError as exc:
            raise NotImplementedError(
                "scipy required для convex hull computation. pip install scipy."
            ) from exc

        import numpy as np

        points = common[["lon", "lat"]].to_numpy()
        if len(points) < 3:
            raise ValueError(f"Need >=3 points для convex hull, got {len(points)}")

        hull = ConvexHull(points)
        hull_points = points[hull.vertices]
        # Close polygon
        hull_closed = np.vstack([hull_points, hull_points[:1]])
        return hull_closed.tolist()
