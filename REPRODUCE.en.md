# Reproducing the results

[Русская версия](REPRODUCE.ru.md)

The catalogue is published ready to use — nothing needs to be run to work with it. The instructions below are for those who want to rebuild the data or verify intermediate steps.

---

## 1. Using the published catalogue

No installation required.

| File | Format | Opens with |
|---|---|---|
| [`data/catalog_ch4_west_siberia.csv`](data/catalog_ch4_west_siberia.csv) | table | any spreadsheet, pandas, R |
| [`data/catalog_ch4_west_siberia.geojson`](data/catalog_ch4_west_siberia.geojson) | event outlines, CRS84 | QGIS, ArcGIS, geopandas, leaflet |
| [`data/zapsib_boundary.geojson`](data/zapsib_boundary.geojson) | area-of-interest boundary | same |

All 59 fields are described in the [data dictionary](data/DATA_DICTIONARY.en.md).

```python
import pandas as pd
df = pd.read_csv("data/catalog_ch4_west_siberia.csv")
valid = df[df.artifact_likely == 0]          # 88 valid events
valid = valid[valid.max_z > 0]               # drop the record with an uncomputed z-score
print(valid.max_z.describe())
```

**Interactive map** (no sign-in required): https://nodal-thunder-481307-u1.projects.earthengine.app/view/plumech4westsib

---

## 2. Requirements for rebuilding

| Requirement | Note |
|---|---|
| Google Earth Engine account | free for research use, application must be approved |
| Google Cloud project with the Earth Engine API enabled | supplied at initialisation |
| Python 3.10 or newer | |
| `earthengine-api` package | `pip install earthengine-api` |

Authenticate once:

```bash
earthengine authenticate
```

⚠️ A full rebuild of the seven-year catalogue costs **on the order of 400 EECU-hours**. It is not an instant operation and consumes the project's compute quota. Steps 3 and 4 below are incomparably cheaper — they read data that already exists.

---

## 3. Re-exporting the catalogue from Earth Engine

The annual collections are published with public read access. Paths:

```
projects/nodal-thunder-481307-u1/assets/RuPlumeScan/catalog/CH4/events_2019
                                                            … events_2025
projects/nodal-thunder-481307-u1/assets/RuPlumeScan/zapsib_boundary
projects/nodal-thunder-481307-u1/assets/RuPlumeScan/refs/schuit2023_v1
projects/nodal-thunder-481307-u1/assets/RuPlumeScan/refs/imeo_mars_v1
```

Regenerate the published CSV, GeoJSON and schema snapshot:

```bash
python code/py/supplement/export_catalog.py --out data
```

The script is read-only: the source collections are never modified. Record order is deterministic (by overpass time, then longitude), so a repeat run yields a **byte-identical result** — provided the source collections have not changed.

Rebuild the data dictionary from the actual data:

```bash
python code/py/supplement/build_data_dictionary.py --data data --out data
```

The script exits with an error if the dictionary and the data disagree on even one field.

---

## 4. Generating the figures

```bash
pip install matplotlib numpy
python code/py/figures/bake_figures.py
```

Figures are rendered server-side by Earth Engine and saved at 300 dpi. Captions are in [`figures/CAPTIONS.en.md`](figures/CAPTIONS.en.md).

---

## 5. UNEP IMEO MARS data

The raw MARS data is distributed under **CC BY-NC-SA 4.0**, which forbids commercial use and requires derivatives to carry the same terms. It is therefore **not included** in this repository.

To obtain it yourself:

1. Go to https://methanedata.unep.org
2. Data download section → CSV bundle
3. Verify the SHA-256 checksums against [`data/MARS_MANIFEST.json`](data/MARS_MANIFEST.json)

The version used in this work was retrieved on **2026-05-15**. The event catalogue carries only the outcome of the cross-check — the binary `matched_mars_150km` flag — which does not constitute redistribution of the source data.

---

## 6. Earth Engine application

The source code of the interactive map is in [`code/js/app/`](code/js/app/). The application is read-only: it never modifies the catalogue.

To run your own copy, copy the modules into your own Earth Engine repository and replace the repository identifier in the `require()` paths with yours. The entry point is `main.js`.

---

## 7. Integrity check

A full check in one command — 20 assertions covering the reported numbers, uniform application of the artefact rule across all years, adherence to the detection thresholds, and the bounded reach of the known defect.

```bash
python code/py/supplement/verify_catalog.py --data data
```

No Earth Engine access is needed — it checks the published CSV. Exit code 0 means no disagreements.

A minimal manual check:

```python
import pandas as pd
df = pd.read_csv("data/catalog_ch4_west_siberia.csv")

assert len(df) == 122
assert df.event_id.nunique() == 122
assert (df.artifact_likely == 0).sum() == 88
assert (df.artifact_likely == 1).sum() == 34
assert df.matched_schuit_150km.sum() == 7
assert df.matched_mars_150km.sum() == 53
assert round(df.max_z.max(), 2) == 85.47
assert df.nearest_source_type.str.startswith("viirs_flare").sum() == 96
print("All checks passed")
```
