# RU-PlumeScan — supplementary material

**Catalogue of methane anomalies over the West Siberian Plain from TROPOMI/Sentinel-5P, 2019–2025.**

[Русская версия](README.ru.md)

This repository holds the data, source code and methodology description accompanying the paper. It is self-contained: the event catalogue is provided in machine-readable form, every processing parameter is documented, and the computations are reproducible.

---

## Contents

| Section | What it holds |
|---|---|
| [`data/`](data/) | The 122-event catalogue — CSV and GeoJSON, plus a dictionary of all 60 fields; the paper's tables as CSV ([`data/tables/`](data/tables/README.en.md)); outputs of the sensitivity checks |
| [`METHODS.en.md`](METHODS.en.md) | Detection methodology: data, algorithm, thresholds, classification |
| [`REPRODUCE.en.md`](REPRODUCE.en.md) | How to reproduce the results |
| [`figures/`](figures/) | Paper figures at 300 dpi with captions |
| [`code/`](code/) | Source code for detection, analysis and figure generation |

**Interactive catalogue map:** https://nodal-thunder-481307-u1.projects.earthengine.app/view/plumech4westsib

---

## Catalogue at a glance

| Quantity | Value |
|---|---|
| Events | 122 |
| Period | 2019-03-15 – 2025-09-19 (March through October) |
| Area of interest | West Siberian Plain, 2.90 million km² |
| Valid / likely artefacts | 88 / 34 |
| Maximum z-score | 85.47 |
| Assigned source: flares (VIIRS) | 96 events |
| Assigned source: oil and gas fields | 25 events |
| Assigned source: thermal power plant | 1 event |

The source is assigned by a category-priority rule within 50 km ([METHODS, section 4.2](METHODS.en.md)).

The area of interest is defined **physico-geographically** — by the boundary of the West Siberian Plain, not by administrative or rectangular limits.

---

## Citation

When using the catalogue, please cite the paper and this repository. Machine-readable metadata is in [`CITATION.cff`](CITATION.cff).

## Licences

- **Source code** — MIT, see [`LICENSE`](LICENSE)
- **Event catalogue** (`data/`) — CC BY 4.0, see [`LICENSE-DATA`](LICENSE-DATA)

### Third-party sources used

| Source | Licence | Role |
|---|---|---|
| Schuit et al. (2023) methane source catalogue | CC BY 4.0 | independent cross-check |
| UNEP IMEO MARS | **CC BY-NC-SA 4.0** | independent cross-check |
| TROPOMI/Sentinel-5P (Copernicus) | Copernicus Open Licence | source measurements |
| ERA5 (ECMWF/C3S) | Copernicus Open Licence | wind fields |
| VIIRS Day/Night Band monthly composites (`NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG`, Earth Observation Group, Colorado School of Mines) | public domain, no restrictions | flare registry |
| MODIS: MCD43A4, MOD10A1, MCD12Q1 (NASA) | NASA open data | artefact diagnostics; built-up land mask for the flare registry |
| Global Power Plant Database (WRI) | CC BY 4.0 | thermal power plants in the object registry |
| OpenStreetMap | ODbL | individual registry objects |

⚠️ The UNEP IMEO MARS licence forbids commercial use and requires derivatives to carry the same terms. The raw MARS data is therefore **not included** in this repository — it is retrieved from the original source, see [`REPRODUCE.en.md`](REPRODUCE.en.md). The catalogue carries only the outcome of the cross-check, a binary match flag.

---

## Data availability

[`data/`](data/) holds the event catalogue (122 records, CSV and GeoJSON, CC BY 4.0 licence), its field dictionary, the area-of-interest boundary, the paper's tables as CSV ([`data/tables/`](data/tables/README.en.md)) and the outputs of the checks (match curves, null model, synthetic injections, nature-reserve run). The source code for detection, analysis and figure generation (MIT licence) is in [`code/`](code/); the paper figures with captions are in [`figures/`](figures/). The annual catalogue collections in Google Earth Engine are listed in [`REPRODUCE.en.md`](REPRODUCE.en.md), section 3; the interactive map is linked above.

Not redistributed:

- **the original UNEP IMEO MARS records.** Their CC BY-NC-SA 4.0 licence forbids commercial use and requires derivatives to carry the same terms. The export can be obtained from the original source (https://methanedata.unep.org) and checked against the checksums in [`data/MARS_MANIFEST.json`](data/MARS_MANIFEST.json). The package contains only a binary match flag for each event and the number of MARS detections per year;
- **the original records of Schuit et al. (2023)**; the catalogue carries a match flag for each event;
- **the industrial-object registry** used for the mask and source attribution; its composition and open sources are described in [METHODS, section 4.2](METHODS.en.md).

---

## Material caveats

These limitations matter for reading the results correctly.

**1. The independent catalogues are not ground truth.** Schuit et al. (2023) and UNEP IMEO MARS target large gas-field sources and systematically omit flaring. A disagreement with them reflects a difference in coverage, not a detection error. Of the 62 unmatched events, 44 are attributed to flares.

**2. The z ≥ 3.0 threshold is an operating threshold set empirically.** It is not a significance level and carries no probabilistic interpretation.

**3. No mass flow rates are reported.** The catalogue contains anomaly characteristics only (z-score, enhancement in ppb, area). No published detection-limit estimate exists for the L3 product, and the catalogue does not give one. The synthetic test ([METHODS, section 8.1](METHODS.en.md)) runs at a test scale and is not a detection-limit estimate.

**4. The algorithm-version label is unified.** The `algorithm_version` field is 3.1.4 for all 122 records — the version of the detection logic they conform to. The label originally written at export time is preserved in `algorithm_version_recorded`: 83 records carry 2.3.2 and 39 carry 3.1.4. Verification shows this is a **discrepancy in the label, not in the processing**: the artefact-classification rule was applied uniformly to all 122 events in the directional form of version 3.1.4. A per-event check yields zero disagreements across all three derived indicators — `artifact_likely`, `artifact_likely_albedo_positive` and `surface_confounded_dark`; the symmetric rule of the earlier revision would have produced 47 artefacts instead of the observed 34. The check is reproducible via `code/py/supplement/verify_catalog.py`.

The catalogue was built with version 3.1.4; the code in [`code/`](code/) is version 3.2.0, in which the annulus background reference became a named configuration parameter (a preset). The `default` preset with the `industrial_buffers` reference reproduces the published catalogue: for 121 of the 122 events the maximum z-score matches to two decimals, the exception being CH4-WSP-006 (11.82 in the catalogue versus 8.18 when reproduced; the comparison is run by `code/py/analysis/step8e_event_ring_bias.py`). The `params_hash` differs nonetheless — the reference keys enter the parameter snapshot — for example, `71d2a7c0…` for 2021 instead of the published `1d909d3a…`.

**5. Winter months are absent.** XCH₄ retrieval is unavailable at high latitudes under low sun and snow cover, so the catalogue spans March through October.

**6. One record carries a known defect.** For event `CH4-WSP-017` (2020-07-01), `max_z` and `mean_z` are zero — a sentinel meaning "statistic not computed", not a measured value; the same record has disagreeing pixel counters (`count` = 18, `n_pixels` = 13). The defect originates at the detection stage and is traceable to the intermediate asset.

The record is retained for consistency with the published counts. Its reach is bounded: the event falls in 2020 and therefore enters **no cross-check metric** — Tier 1 is computed over 2021, Tier 2 over 2022–2025. It affects neither the catalogue maximum z-score nor the counts of events at z > 5. It enters only the total event count and the valid/artefact split, since artefact classification is driven by albedo and snow cover and does not depend on the z-score. The record should be excluded when computing any z-score statistics.

**7. Provenance of the area-of-interest boundary.** The West Siberian Plain outline was digitised manually by the author (Sizov, 2026) from a digital elevation model, guided by the boundaries given in the *Atlas of Tyumen Oblast* (1971) and other cartographic atlases. The vector layer is published alongside the catalogue; its parameters are in [METHODS, section 2](METHODS.en.md).

Sizov O.S., Geomorphological zoning of the West Siberian Plain based on the AW3D30 digital elevation model, *Geomorfologiya i paleogeografiya*, 2026, V. 57, No. 1, pp. 97–116 (in Russian).
