"""
Per-source-type classification + buffer mapping (TD-0027 P-01.0d).

Pure function — testable, deterministic, no GEE dependency. Maps existing
`(source_type, source_subtype, viirs_radiance_mean)` к
`(category, buffer_km)` для downstream per-feature buffering в
`build_industrial_buffered_mask_per_type.py`.

Classification table (researcher decision 2026-05-04):

| source_type  | source_subtype       | category          | buffer_km | drop |
|--------------|----------------------|-------------------|-----------|------|
| oil_gas      | production_field     | gas_field         | 50        |   no |
| oil_gas      | viirs_flare_proxy    | viirs_flare_high  | 30 (≥100) |   no |
| oil_gas      | viirs_flare_proxy    | viirs_flare_low   | 15 (<100) |   no |
| power_plant  | coal/gas/tpp_gas     | tpp_gres          | 30        |   no |
| power_plant  | hydro                | (dropped)         | -         |  yes |
| power_plant  | nuclear              | (dropped)         | -         |  yes |
| coal_mine    | open_pit/deep_mine   | coal_mine         | 30        |   no |
| metallurgy   | smelter/ore/agg      | smelter           | 30        |   no |

VIIRS radiance threshold = 100 nW/cm²/sr (researcher Flag 3 decision; per
inspection 2026-05-04 splits 168 high / 306 low — ~35/65).
"""

from __future__ import annotations

from dataclasses import dataclass

VIIRS_RADIANCE_THRESHOLD_HIGH = 100.0  # nW/cm²/sr

# Buffer mapping per category
BUFFER_KM = {
    "gas_field": 50,
    "viirs_flare_high": 30,
    "viirs_flare_low": 15,
    "tpp_gres": 30,
    "coal_mine": 30,
    "smelter": 30,
}


@dataclass(frozen=True)
class Classification:
    """Result of classifying one source feature."""

    category: str  # one of BUFFER_KM keys, или "dropped"
    buffer_km: int  # 0 if dropped
    drop: bool  # True if feature should be excluded from final inventory
    rationale: str  # human-readable why


def classify_source(
    source_type: str | None,
    source_subtype: str | None,
    viirs_radiance_mean: float | None = None,
) -> Classification:
    """
    Classify one source feature по taxonomy outlined в module docstring.

    Args:
        source_type: e.g. "oil_gas", "power_plant", "coal_mine", "metallurgy"
        source_subtype: e.g. "production_field", "viirs_flare_proxy", "coal", ...
        viirs_radiance_mean: nW/cm²/sr; required для viirs_flare_proxy split

    Returns:
        Classification object (frozen).
    """
    st = (source_type or "").strip()
    sst = (source_subtype or "").strip()

    if st == "oil_gas":
        if sst == "production_field":
            return Classification(
                category="gas_field",
                buffer_km=BUFFER_KM["gas_field"],
                drop=False,
                rationale="major gas extraction field; 50 km buffer per TD-0027",
            )
        if sst == "viirs_flare_proxy":
            radiance = viirs_radiance_mean if viirs_radiance_mean is not None else 0.0
            if radiance >= VIIRS_RADIANCE_THRESHOLD_HIGH:
                return Classification(
                    category="viirs_flare_high",
                    buffer_km=BUFFER_KM["viirs_flare_high"],
                    drop=False,
                    rationale=f"VIIRS flare radiance={radiance:.1f} ≥ {VIIRS_RADIANCE_THRESHOLD_HIGH} → high-confidence",
                )
            return Classification(
                category="viirs_flare_low",
                buffer_km=BUFFER_KM["viirs_flare_low"],
                drop=False,
                rationale=f"VIIRS flare radiance={radiance:.1f} < {VIIRS_RADIANCE_THRESHOLD_HIGH} → localized",
            )

    if st == "power_plant":
        if sst in ("coal", "gas", "tpp_gas"):
            return Classification(
                category="tpp_gres",
                buffer_km=BUFFER_KM["tpp_gres"],
                drop=False,
                rationale=f"thermal power plant ({sst}); standard 30 km buffer",
            )
        if sst == "hydro":
            return Classification(
                category="dropped",
                buffer_km=0,
                drop=True,
                rationale="hydroelectric не emits CH₄/NO₂/SO₂ at industrial-detection scale",
            )
        if sst == "nuclear":
            return Classification(
                category="dropped",
                buffer_km=0,
                drop=True,
                rationale="nuclear не emits CH₄/NO₂/SO₂ at industrial-detection scale",
            )

    if st == "coal_mine":
        return Classification(
            category="coal_mine",
            buffer_km=BUFFER_KM["coal_mine"],
            drop=False,
            rationale=f"coal mine ({sst}); standard 30 km buffer",
        )

    if st == "metallurgy":
        return Classification(
            category="smelter",
            buffer_km=BUFFER_KM["smelter"],
            drop=False,
            rationale=f"metallurgical facility ({sst}); standard 30 km buffer",
        )

    # Fallback — should not happen для current 531-feature inventory but defensive
    return Classification(
        category="unknown",
        buffer_km=30,
        drop=False,
        rationale=f"unmatched source_type={st!r} subtype={sst!r}; default 30 km buffer",
    )
