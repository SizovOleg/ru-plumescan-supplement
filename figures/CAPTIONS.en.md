# Figure captions

[Русская версия](CAPTIONS.ru.md)

The four figures of the paper. File numbering matches the numbering in the text. Raster versions are 300 dpi; a vector version (`.svg`) is available for all four.

The physico-geographic boundary of the West Siberian Plain was digitised manually by the author from a digital elevation model, guided by boundaries in the Atlas of Tyumen Oblast (1971) and other cartographic atlases; the vector layer is published as `data/zapsib_boundary.geojson`.

---

## Figure 1 — Structure of the detection method

**Files:** `fig1_pipeline_300dpi.png`, `fig1_pipeline_300dpi.svg`
**Script:** `code/py/figures/bake_pipeline.py`

> Flow chart of the methane plume detection procedure based on TROPOMI data

Eight numbered processing steps are grouped into four stages distinguished by fill and frame style: input data, anomaly extraction, checking and attribution, result. The right-hand column of each step gives the adopted thresholds and parameters; the dashed blocks on the right are the auxiliary datasets drawn in. The sequence runs: TROPOMI L3 XCH₄ filtered at `qa_value ≥ 0.5` → reprojection to an equal-area 5.5 km grid (EPSG:6931) → annulus z-scoring on the median and MAD over 50–150 km with at least 50 valid pixels in the ring → clustering at z ≥ 3.0 with at least 5 pixels → wind checking against ERA5 → the MODIS artefact-diagnostic cascade → source attribution from VIIRS Nightfire.

---

## Figure 2 — Catalogue events and reference catalogues

**Files:** `fig2_catalog_map_300dpi.png`, `fig2_catalog_map_300dpi.svg`
**Script:** `code/py/figures/bake_map_satellite.py`

> Detected anomalous methane emission events over the West Siberian Plain in 2019–2025 compared with the reference catalogues

Three classes of points: the 122 events of the present catalogue, the detections of Schuit et al. (2023) and the detections of UNEP IMEO MARS. The backdrop is the Esri World Imagery mosaic, over which are drawn the boundaries of the federal subjects of the Russian Federation and the oblasts of the Republic of Kazakhstan, major rivers, cities and the physico-geographic boundary of the plain. The scale bar is corrected for the latitude at the centre of the frame.

---

## Figure 3 — Distribution by year

**Files:** `fig3_per_year_counts_300dpi.png`, `fig3_per_year_counts_300dpi.svg`
**Script:** `code/py/figures/bake_figures.py --only F6`

> Annual number of catalogue events divided into reliable events and likely artefacts

The number of events at z > 5 is given above each bar. The rise toward 2024 reflects a combination of factors, including expanding coverage of the independent catalogues and changing observing conditions, and should not be read as a direct measure of an emission trend.

---

## Figure 4 — Match curves

**Files:** `fig4_match_curves_300dpi.png`, `fig4_match_curves_300dpi.svg`
**Script:** `code/py/figures/bake_figures.py --only R3`

> Fraction of matched events as a function of the spatial matching radius: the Schuit catalogue (2021) and the MARS system (2023–2025). Grey curves show the random expectation; the vertical dashed line marks the empirically adopted radius of 150 km

The matching radius runs from 25 to 300 km. Random expectation is the fraction of the plain's area within the given radius of at least one same-year reference detection, i.e. the match rate that uniformly random event placement would produce. The 150 km radius is adopted as the point where the excess of the observed rate over random expectation is greatest for Tier 2 (71.6% vs 32.4%). Median distances to the nearest record of the respective catalogue: 86.3 km for Tier 1, 76.5 km for Tier 2, 77.5 km overall.
