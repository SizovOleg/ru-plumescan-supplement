# The paper's tables in machine-readable form

[Русская версия](README.ru.md)

The three tables of the paper as CSV (UTF-8, comma-separated, decimal point). Every number is recomputable from the files of this repository; the one exception is the number of MARS detections per year, which requires the original MARS export (not redistributed, see below).

All confidence intervals are 95% Wilson intervals with z = 1.96 (the same computation as in `code/py/analysis/step8b_synthetic_pod.py` and `step8f_clean_zone_false_alarms.py`):

```python
import math

def wilson(k, n, z=1.96):
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, c - h), min(1.0, c + h)
```

Run the commands below from the repository root.

---

## `table1_events_by_year.csv` — Table 1 of the paper

Catalogue events by year.

| Column | Meaning |
|---|---|
| `year` | year; the `2019-2025` row is the total |
| `events` | number of events |
| `reliable` | valid events: `artifact_likely = 0` |
| `likely_artefacts` | likely artefacts: `artifact_likely = 1` |
| `z_gt_5` | events with `max_z > 5` |

Source: [`../catalog_ch4_west_siberia.csv`](../catalog_ch4_west_siberia.csv). All values match Table 1 of the paper. Record CH4-WSP-017, whose `max_z = 0` is a sentinel ([README](../../README.md), caveat 6), counts in the 2020 `events` and `reliable` but not in `z_gt_5`.

```python
import pandas as pd

df = pd.read_csv("data/catalog_ch4_west_siberia.csv")
t1 = df.groupby("year").agg(events=("event_id", "size"),
                            reliable=("artifact_likely", lambda s: int((s == 0).sum())),
                            likely_artefacts=("artifact_likely", "sum"),
                            z_gt_5=("max_z", lambda s: int((s > 5).sum())))
print(t1)
print(t1.sum())
```

---

## `table2_mars_precision_by_year.csv` — Table 2 of the paper

Comparison with the UNEP IMEO MARS catalogue by year.

| Column | Meaning |
|---|---|
| `year` | year; the `2023-2025` row is the combined estimate |
| `matched_events` | catalogue events with `matched_mars_150km = 1` |
| `catalogue_events` | all catalogue events of the year |
| `precision_pct` | precision, % = `matched_events / catalogue_events` |
| `ci95_low_pct`, `ci95_high_pct` | 95% Wilson interval, % |
| `mars_detections_inside_plain` | MARS detections of the year located inside [`../zapsib_boundary.geojson`](../zapsib_boundary.geojson) |

Precision and intervals match Table 2 of the paper. There is no MARS detection inside the plain in 2022, so precision is undefined (empty cells) and 2022 is left out of the combined row.

The MARS counts are aggregates only: the original MARS records are distributed under CC BY-NC-SA 4.0 and are not included in this repository ([README](../../README.md), "Data availability"). All records of the export (`unep_methanedata_detected_plumes.csv`, retrieved 2026-05-15, SHA-256 in [`../MARS_MANIFEST.json`](../MARS_MANIFEST.json)) are counted without filtering by satellite; the year comes from the `tile_date` field. In total 163 detections fall inside the plain: 17 in 2023, 53 in 2024, 82 in 2025 and 11 in 2026 (outside the catalogue period); none in 2022.

```python
for years in ([2023], [2024], [2025], [2023, 2024, 2025]):
    s = df[df.year.isin(years)]
    print(years, wilson(int(s.matched_mars_150km.sum()), len(s)))

# MARS detections inside the plain (needs the MARS export, see REPRODUCE.en.md, section 5)
import json
from shapely.geometry import Point, shape

plain = shape(json.load(open("data/zapsib_boundary.geojson", encoding="utf-8"))["features"][0]["geometry"])
mars = pd.read_csv("unep_methanedata_detected_plumes.csv")
inside = mars[[plain.contains(Point(x, y)) for x, y in zip(mars.lon, mars.lat)]]
print(pd.to_datetime(inside.tile_date, errors="coerce").dt.year.value_counts().sort_index())
```

---

## `table3_detection_probabilities.csv` — Table 3 of the paper

Detection, miss and false-alarm probabilities. The checks are described in [METHODS, section 8](../../METHODS.en.md).

| `row_id` | Row of Table 3 | k / n |
|---|---|---|
| `detection_all` | detection probability, all synthetic injections of 1–10 t/h | 10 / 30 |
| `detection_coverage_ge_200` | same with sufficient coverage: ≥ 200 valid L3 pixels in the 15 km disc | 10 / 17 |
| `detection_coverage_ge_200_flux_gt_6` | same with flux above 6 t/h | 8 / 8 |
| `miss_all` | miss probability | 20 / 30 |
| `false_alarm_all_trials` | detector alarm rate over the nature reserves, all trials | 84 / 1064 |
| `false_alarm_excluding_degenerate` | same without the two degenerate annuli | 82 / 1062 |

Columns: `k`, `n` — numerator and denominator; `estimate` — the rate k/n; `ci95_low`, `ci95_high` — Wilson interval; `article_value` — the value in Table 3 of the paper; `source_file` — the file in `data/` that gives k and n.

**False-alarm rate.** The paper gives 0.077 with the basis "84 of 1064 overpasses". However, 84/1064 = 0.0789 [0.0642; 0.0967], whereas 0.077 corresponds to 82/1062 = 0.0772 [0.0626; 0.0948] — the same sample without the two trials with a degenerate annulus (MAD ≈ 0). Those two trials have maximum z-scores of 165.8 and 8898.3; the next value is 29.4. The table therefore carries both rows. Both refer to the alternative configuration (annulus of clean pixels, candidates not restricted to buffers) and describe the candidate stage, before artefact diagnostics.

The other rows match the paper. The 200-pixel coverage threshold and the 6 t/h flux threshold were applied when analysing the results; the summary in `p_02_0e_synthetic_pod.json` does not contain them.

```python
pod = json.load(open("data/p_02_0e_synthetic_pod.json", encoding="utf-8"))["results"]
suff = [r for r in pod if (r.get("n_valid_px_disk") or 0) >= 200]
high = [r for r in suff if r["flux_t_h"] > 6]
print(wilson(sum(r["recovered"] for r in pod), len(pod)))        # 10 / 30
print(wilson(sum(r["recovered"] for r in suff), len(suff)))      # 10 / 17
print(wilson(sum(r["recovered"] for r in high), len(high)))      # 8 / 8
print(wilson(sum(not r["recovered"] for r in pod), len(pod)))    # 20 / 30

fa = json.load(open("data/p_02_0e_clean_zone_false_alarms.json", encoding="utf-8"))
trials = [r for c in fa["chunks"].values() for r in c["rows"]]
alarms = [r for r in trials if (r.get("n_cluster_px_in_zone") or 0) >= 1]
degenerate = [r for r in alarms if (r.get("max_z") or 0) > 100]   # two annuli with MAD ≈ 0
print(wilson(len(alarms), len(trials)))                                          # 84 / 1064
print(wilson(len(alarms) - len(degenerate), len(trials) - len(degenerate)))      # 82 / 1062
```
