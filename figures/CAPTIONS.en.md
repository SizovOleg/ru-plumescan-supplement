# Figure captions

[Русская версия](CAPTIONS.ru.md)

All raster figures are 300 dpi. Files suffixed `_2100w` are sized for full page width, `_1015w` for a single column. Vector versions (`.svg`) are available where the figure is drawn entirely in matplotlib.

The terrain backdrop is MERIT DEM. The outline marks the physico-geographic boundary of the West Siberian Plain, manually digitised by the author from a digital elevation model, guided by boundaries in the Atlas of Tyumen Oblast (1971) and other cartographic atlases.

Note: figure files are named with Cyrillic-transliterated prefixes `R1`–`R3` for the supporting figures and `F5`–`F9` for the main-text figures, matching the paper's numbering.

---

## Figure 1 (R1) — Study area

**File:** `R1_study_area_300dpi_2100w.png`

The West Siberian Plain within its physico-geographic boundary over terrain. The inset shows the position of the region in northern Eurasia. The area covers 2.90 million km². The boundary was manually digitised by the author from a digital elevation model, guided by the Atlas of Tyumen Oblast (1971) and other cartographic atlases; the vector layer is published as `data/zapsib_boundary.geojson`.

---

## Figure 2 (R2) — Processing pipeline

**Files:** `R2_pipeline_300dpi.png`, `R2_pipeline_300dpi.svg`

The processing sequence: from the TROPOMI L3 XCH₄ product filtered at `qa_value ≥ 0.5`, through reprojection to an equal-area 5.5 km grid, annulus z-scoring using the median and MAD, clustering at z ≥ 3.0 with at least 5 pixels, two-condition masking, wind checking against ERA5 and the artefact-classification cascade — to the final catalogue of 122 events carrying match flags against the independent catalogues.

---

## Figure 3 (R3) — Match curves and median distances

**Files:** `R3_match_curves_300dpi.png`, `R3_match_curves_300dpi.svg`

The fraction of events with a same-year match as a function of matching radius from 25 to 300 km, shown separately against Schuit et al. (2023) and UNEP IMEO MARS. The vertical line marks the adopted 150 km radius. Median distances to the nearest record of the respective catalogue are given: 86.3 km for Tier 1, 76.5 km for Tier 2, 77.5 km overall.

---

## Figure 5 (F5) — Spatial distribution of the catalogue

**Files:** `F5_spatial_map_300dpi_2100w.png`, `F5_spatial_map_300dpi_1015w.png`

All 122 catalogue events. Marker size scales with the logarithm of the maximum z-score; colour encodes the type of the nearest source. Records of the independent catalogues are shown in grey. The maximum z-score in the catalogue is 85.5.

---

## Figure 6 (F6) — Distribution by year

**Files:** `F6_per_year_counts_300dpi.png`, `F6_per_year_counts_300dpi.svg`

Event counts by year, split into valid events and likely artefacts, with events at z > 5 marked separately. The rise toward 2024 reflects a combination of factors, including expanding coverage of the independent catalogues and changing observing conditions, and should not be read as a direct measure of an emission trend.

---

## Figure 7 (F7) — Regional insets

**Files:** `F7_combined_zoom_300dpi_2100w.png` (both panels), `F7A_KhMAO_zoom_300dpi_1015w.png`, `F7B_Bovanenkovo_zoom_300dpi_1015w.png`

Panel A — Khanty-Mansi Autonomous Okrug, an area dominated by flaring. Panel B — Bovanenkovo, a gas-production area on the Yamal Peninsula. The insets show the relative positions of catalogue events and independent-catalogue records in characteristic industrial districts.

---

## Figure 9 (F9) — Complementary coverage of flares

**Files:** `F9_flare_complement_300dpi_2100w.png`, `F9_flare_complement_300dpi_1015w.png`

The 44 events attributed to flares from VIIRS Nightfire that have no match in either Schuit et al. (2023) or UNEP IMEO MARS within 150 km of the same year. The figure illustrates that non-matching against the independent catalogues is in large part a difference in coverage: both target large gas-field sources and systematically omit flaring.
