# Detection methodology

[Русская версия](METHODS.ru.md)

This document describes how the 122-event catalogue was produced: source data, anomaly computation, thresholds, classification and cross-checking against independent sources. Every numeric parameter is given with the value used to build the published catalogue.

---

## 1. Source data

| Purpose | Dataset | Selection |
|---|---|---|
| Methane concentration | `COPERNICUS/S5P/OFFL/L3_CH4` (TROPOMI/Sentinel-5P) | `qa_value ≥ 0.5` |
| Wind fields | ERA5 hourly reanalysis | 10 m level; cross-checked at 850 hPa |
| Flare attribution | VIIRS Nightfire | — |
| Industrial objects | gas fields, thermal power plants, flares | project registry |

The L3 product grid has a 1113.2 m step; all analysis is performed on an equal-area grid at **5.5 km in EPSG:6931** (Lambert azimuthal equal-area, northern hemisphere). Moving to an equal-area projection is necessary because the region spans 54–72°N, where area distortion in geographic coordinates is substantial.

⚠️ Caveat from the data provider's catalogue: filtering on `qa_value` does not remove all problematic pixels; some pixels with too low methane concentrations remain.

---

## 2. Area and period

**Area of interest** — the West Siberian Plain within its physico-geographic boundary: a composite polygon of 8 parts, 45,386 vertices, covering 2.90 million km². This is 58.5% of the 60–95°E × 50–75°N bounding box used at earlier stages of the work.

The outline was digitised manually by the author from a digital elevation model, guided by the boundaries given in the *Atlas of Tyumen Oblast* (1971) and other cartographic atlases. The vector layer is published alongside the catalogue (`data/zapsib_boundary.geojson`), so the area is reproducible exactly, without re-digitisation.

**Period** — 2019–2025, March through October. Winter months are excluded by an objective constraint: XCH₄ retrieval is unavailable at high latitudes under low sun and persistent snow cover.

---

## 3. Anomaly computation

The governing principle: **an anomaly is defined relative to the local background within the same orbital overpass**, not by an absolute concentration threshold and not from multi-month composites. Composites smooth away the short-lived enhancements the search targets, and a single absolute threshold ignores the latitudinal and seasonal march of the background.

### 3.1. Local annulus

For each pixel the background is estimated over an annular neighbourhood, using the pixels that lie inside infrastructure buffer zones (the `industrial_buffers` reference, see §3.2):

| Parameter | Value |
|---|---|
| Inner radius | 50 km |
| Outer radius | 150 km |
| Minimum pixels in the annulus | 50 |

The 50 km inner radius keeps the plume itself out of its own background. If fewer than 50 valid pixels fall in the annulus, the z-score for that pixel is masked — the background estimate is treated as unreliable.

### 3.2. Robust z-score

Background level and spread are estimated with robust statistics — the **median and the median absolute deviation (MAD)** rather than the mean and standard deviation. Robust estimators are not dragged by a plume that falls inside the neighbourhood.

```
Δ = XCH4(pixel) − median(annulus)
z = Δ / (1.4826 · MAD(annulus))
```

The factor 1.4826 scales MAD to standard-deviation units for a normal distribution.

### 3.3. Thresholds

| Parameter | Value | Meaning |
|---|---|---|
| `z_min` | **3.0** | minimum pixel z-score |
| `min_cluster_px` | **5** | minimum connected-cluster size |

⚠️ The z ≥ 3.0 threshold is an **operating threshold set empirically**. It is not a significance level: the residual distribution was not tested for normality, and no probabilistic interpretation applies.

### 3.4. Masking

Two conditions are applied. The first is retrieval validity at the orbit level. The second sets the **background reference** and, with it, the search area: both the annulus sample and the candidates are confined to infrastructure buffer zones by type — gas fields 50 km, high-confidence flares 30 km, low-confidence flares 15 km, thermal power plants and other objects 30 km. This is the configuration parameter `background.annulus_reference = industrial_buffers` (Algorithm §3.6.2); the alternative reference `regional_clean` — the annulus over clean pixels with an explicit buffer filter on candidates — is kept for comparisons and for other gases. The industrial reference is a measured choice: in summer the clean surroundings of the fields are wetlands with systematically higher methane (the clean-ring median sits 4–9 ppb above the industrial-ring median at the published events), and with the regional reference the detector fires over the nature reserves on 7.7% of overpasses.

No separate wetland or water masks are applied: wetlands are kept out of the background by the choice of reference itself (they do not fall inside infrastructure buffers), and water is already removed by the product's native quality control.

---

## 4. Event characteristics

Connected clusters of pixels passing the thresholds form events. For each, the following are computed:

- **Geometry** — centroid, equal-area area, pixel count, major-axis orientation (eigen-decomposition with a cosine-latitude correction)
- **Signal strength** — maximum and mean z-score, maximum and mean enhancement over background in ppb
- **Wind conditions** — 10 m direction and speed, agreement with the 850 hPa level, and a measure of how well the plume axis matches wind direction
- **Nearest source** — type, distance, registry identifier

---

## 5. Artefact classification

Some XCH₄ anomalies arise not from emissions but from retrieval behaviour over bright or dark surfaces. The rule is:

```
artifact_likely = (corr_albedo ≥ +0.5) OR (snow fraction in cluster > 0.5)
```

where `corr_albedo` is the correlation between the XCH₄ enhancement and albedo within the cluster. A positive correlation indicates a bright-surface artefact.

The converse case, `corr_albedo ≤ −0.5`, is flagged as `surface_confounded_dark` — an **annotation, not a rejection**: the event stays in the catalogue.

Result: **88 valid, 34 likely artefacts** out of 122.

The rule was applied uniformly across all years. Some records carry a stale algorithm-version label, but a per-event check confirms the processing is uniform: the earlier, symmetric form of the rule (`|corr_albedo| ≥ 0.5`) would have produced 47 artefacts, whereas 34 are observed — exactly what the directional form yields.

---

## 6. Event category

A five-level priority cascade:

| Priority | Condition | Category |
|---|---|---|
| 1 | inside a zone free of known sources | `diffuse_CH4` |
| 2 | wetland heuristic: ≥ 3 of 4 conditions met¹ | `diffuse_CH4` |
| 3 | wind levels disagree | `wind_ambiguous` |
| 4 | a nearest industrial source is found | `CH4_only` |
| 5 | otherwise | `wind_ambiguous` |

¹ The four conditions are: area above 1000 km²; low cluster compactness; months June–September; no industrial source within 100 km. The compactness threshold has not been calibrated empirically, so in the applied configuration that condition is always false and the remaining three must all hold — making the diffuse classification deliberately conservative.

Observed distribution: `wind_ambiguous` — 78, `CH4_only` — 43, `diffuse_CH4` — 1.

---

## 7. Cross-check against independent catalogues

An event counts as matched if an independent catalogue reports a detection **from the same year** within **150 km**. The condition is simultaneously spatial and temporal — a coordinate match without a year match does not count.

Both catalogues are first clipped by the same physico-geographic boundary so the comparison is symmetric:

| Catalogue | Total in bounding box | Inside the plain |
|---|---|---|
| Schuit et al. (2023) | 123 | 32 |
| UNEP IMEO MARS | 446 | 163 |

### Results

**Tier 1 — Schuit et al. (2023)**

| Metric | Value |
|---|---|
| Precision | 43.8% (7 of 16) |
| Recall | 46.9% (15 of 32) |

**Tier 2 — UNEP IMEO MARS**, for years with non-empty coverage:

| Year | Precision |
|---|---|
| 2023 | 57.1% (12 of 21) |
| 2024 | 82.1% (32 of 39) |
| 2025 | 64.3% (9 of 14) |
| **2023–2025** | **71.6% (53 of 74)** |

2022 is excluded entirely: no MARS record falls inside the plain that year, so the seven 2022 catalogue events are excluded from the combined denominator as well (21 + 39 + 14 = 74). Correction of 2026-08-27: the previously published figure of 65.4% (53 of 81) counted the 2022 events in the denominator despite the declared exclusion.

### How to read this

⚠️ **The independent catalogues are not ground truth.** Both target large gas-field sources and systematically omit flaring.

Of the 122 events, **62 have no match** in either catalogue. Of those:

| Class | Count | Reason |
|---|---|---|
| Outside temporal coverage | 32 | 2019, 2020, 2022 — no records of the matching year inside the plain |
| No spatial match | 30 | records exist, but none within 150 km |

**44 of the 62 unmatched events are attributed to flares** from VIIRS Nightfire at the detection stage. The unmatched fraction therefore reflects **complementary coverage**, not a false-positive rate.

The median distance to the nearest independent-catalogue record is **77.5 km** (Tier 1: 86.3 km, Tier 2: 76.5 km).

**Methodological note on active-fire products.** Active-fire products (VNP14A1, FIRMS) are wildfire thermal-anomaly detectors that systematically miss steady gas flaring — the very reason VIIRS Nightfire was developed. Post-hoc matching against active-fire products yielded corroboration rates anywhere from 17% to 73% depending purely on buffer and time-window choice, which reflects a product–task mismatch rather than the reality of flaring. Flare attribution rests on VIIRS Nightfire at the detection stage.

---

## 8. Computational cost

Building the seven-year catalogue required **approximately 400 EECU-hours** in Google Earth Engine. This is an order-of-magnitude estimate: per-task accounting was not maintained.

---

## 9. What the methodology does not include

- **Mass flow rate estimates** (t/h, kg/h) are not computed
- **Machine learning** is not used at any stage
- **Composites** (monthly or annual medians with a threshold) are not used for detection
- **A single absolute concentration threshold** is not applied — only enhancement over the local background
