# RU-PlumeScan — supplementary material

**Catalogue of methane anomalies over the West Siberian Plain from TROPOMI/Sentinel-5P, 2019–2025.**

[Русская версия](README.ru.md)

This repository holds the data, source code and methodology description accompanying the paper. It is self-contained: the event catalogue is provided in machine-readable form, every processing parameter is documented, and the computations are reproducible.

---

## Contents

| Section | What it holds |
|---|---|
| [`data/`](data/) | The 122-event catalogue — CSV and GeoJSON, plus a dictionary of all 59 fields |
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
| Nearest source: flares (VIIRS) | 96 events |
| Nearest source: gas fields | 25 events |
| Nearest source: thermal power plant | 1 event |

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
| VIIRS Nightfire | NOAA open data | flare attribution |

⚠️ The UNEP IMEO MARS licence forbids commercial use and requires derivatives to carry the same terms. The raw MARS data is therefore **not included** in this repository — it is retrieved from the original source, see [`REPRODUCE.en.md`](REPRODUCE.en.md). The catalogue carries only the outcome of the cross-check, a binary match flag.

---

## Material caveats

These limitations matter for reading the results correctly.

**1. The independent catalogues are not ground truth.** Schuit et al. (2023) and UNEP IMEO MARS target large gas-field sources and systematically omit flaring. A disagreement with them reflects a difference in coverage, not a detection error. Of the 62 unmatched events, 44 are attributed to flares.

**2. The z ≥ 3.0 threshold is an operating threshold set empirically.** It is not a significance level and carries no probabilistic interpretation.

**3. No mass flow rates are reported.** The catalogue contains anomaly characteristics only (z-score, enhancement in ppb, area). The nominal detection limit of ~3–5 t/h is derived theoretically and is not measurement-confirmed.

**4. The catalogue was assembled under two algorithm versions** — 83 records at version 2.3.2 and 39 at version 3.1.4. The difference affects only artefact-classification rules; detection itself is identical.

**5. Winter months are absent.** XCH₄ retrieval is unavailable at high latitudes under low sun and snow cover, so the catalogue spans March through October.

**6. One record carries a known defect.** For event `CH4-WSP-017` (2020-07-01), `max_z` and `mean_z` are zero — a sentinel meaning "statistic not computed", not a measured value; the same record has disagreeing pixel counters (`count` = 18, `n_pixels` = 13). The defect originates at the detection stage and is traceable to the intermediate asset. The record is retained for consistency with the published counts; it should be excluded when computing z-score statistics.

**7. Provenance of the area-of-interest boundary.** The West Siberian Plain outline was ingested as a ready-made vector layer; the project records do not preserve which cartographic source it was digitised from. This limits traceability but not reproducibility: the layer itself is published alongside the catalogue.
