"""Экспорт каталога CH4-событий в машиночитаемые форматы для supplementary material.

Читает семь годовых FeatureCollection из GEE (2019-2025), объединяет и пишет:
  - catalog_ch4_west_siberia.csv      — плоская таблица, одна строка = одно событие
  - catalog_ch4_west_siberia.geojson  — точечная геометрия центроидов + свойства
  - schema_dump.json                  — фактическая схема полей (тип, покрытие,
                                        диапазон/множество значений) для словаря

Read-only: ассеты не мутируются. Каталог мал (~122 события), поэтому выгрузка
идёт через getInfo() без Export/Drive.

Использование:
    python src/py/supplement/export_catalog.py [--out DIR]
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List

import ee

PID = "nodal-thunder-481307-u1"
ROOT = f"projects/{PID}/assets/RuPlumeScan"
CAT = f"{ROOT}/catalog/CH4"
YEARS = ["2019", "2020", "2021", "2022", "2023", "2024", "2025"]

# Порядок колонок в CSV: идентификация -> геометрия -> сигнал -> источник ->
# валидация -> происхождение. Поля вне списка добавляются в конец по алфавиту.
COLUMN_ORDER = [
    "event_id",
    "datetime_utc",
    "date_utc",
    "year",
    "month",
    "centroid_lon",
    "centroid_lat",
    "area_km2",
    "n_pixels",
    "max_z",
    "mean_z",
    "max_delta",
    "mean_delta",
    "artifact_likely",
    "corr_albedo",
    "nearest_source_type",
    "nearest_source_distance_km",
    "nearest_source_name",
    "matched_schuit_150km",
    "matched_mars_150km",
    "algorithm_version",
    "config_id",
    "params_hash",
    "run_id",
    "run_date",
]


def fetch_year(year: str) -> List[Dict[str, Any]]:
    """Выгрузить события одного года как список GeoJSON-Feature."""
    fc = ee.FeatureCollection(f"{CAT}/events_{year}")
    info = fc.getInfo()
    feats = info.get("features", []) if info else []
    print(f"  {year}: {len(feats)} events")
    return feats


def add_derived_fields(rows: List[Dict[str, Any]]) -> None:
    """Добавить производные поля, отсутствующие в ассете, но нужные читателю.

    В GEE-каталоге время хранится только как `orbit_date_millis` (epoch ms), а
    устойчивого человекочитаемого идентификатора события нет вовсе. Для
    supplementary оба необходимы: на event_id ссылаются текст статьи и рисунки.

    Мутирует rows на месте. Порядок rows должен быть уже стабилизирован.
    """
    for idx, row in enumerate(rows, start=1):
        millis = row.get("orbit_date_millis")
        if isinstance(millis, (int, float)):
            stamp = dt.datetime.fromtimestamp(millis / 1000.0, tz=dt.timezone.utc)
            row["datetime_utc"] = stamp.strftime("%Y-%m-%dT%H:%M:%SZ")
            row["date_utc"] = stamp.strftime("%Y-%m-%d")
        else:
            row["datetime_utc"] = None
            row["date_utc"] = None
        row["event_id"] = "CH4-WSP-{:03d}".format(idx)


def collect_schema(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Собрать фактическую схему: тип, покрытие, диапазон или множество значений."""
    schema: Dict[str, Any] = OrderedDict()
    total = len(rows)
    keys: List[str] = []
    for row in rows:
        for k in row:
            if k not in keys:
                keys.append(k)

    for key in keys:
        values = [r[key] for r in rows if r.get(key) is not None]
        types = sorted({type(v).__name__ for v in values})
        entry: Dict[str, Any] = {
            "python_type": types[0] if len(types) == 1 else types,
            "present": len(values),
            "missing": total - len(values),
        }
        numeric = [v for v in values if isinstance(v, (int, float))
                   and not isinstance(v, bool)]
        if numeric and len(numeric) == len(values):
            entry["min"] = min(numeric)
            entry["max"] = max(numeric)
        else:
            distinct = sorted({str(v) for v in values})
            # Множество значений полезно только если оно короткое (категории)
            if len(distinct) <= 25:
                entry["distinct_values"] = distinct
            else:
                entry["distinct_count"] = len(distinct)
                entry["examples"] = distinct[:3]
        schema[key] = entry
    return schema


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="supplement/data",
                    help="каталог для записи (по умолчанию supplement/data)")
    args = ap.parse_args()

    ee.Initialize(project=PID)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Fetching catalog from GEE (read-only):")
    features: List[Dict[str, Any]] = []
    for year in YEARS:
        features.extend(fetch_year(year))
    print(f"TOTAL: {len(features)} events")

    rows = [f.get("properties", {}) or {} for f in features]

    # Стабильный порядок строк: по времени пролёта, затем по долготе.
    # Порядок фиксирует нумерацию event_id, поэтому должен быть детерминированным.
    order = sorted(
        range(len(rows)),
        key=lambda i: (rows[i].get("orbit_date_millis") or 0,
                       rows[i].get("centroid_lon") or 0.0),
    )
    features = [features[i] for i in order]
    rows = [rows[i] for i in order]

    # rows — те же объекты properties, что и внутри features, поэтому
    # производные поля попадают и в CSV, и в GeoJSON
    add_derived_fields(rows)

    # --- CSV ---------------------------------------------------------------
    present_keys: List[str] = []
    for row in rows:
        for k in row:
            if k not in present_keys:
                present_keys.append(k)
    columns = [c for c in COLUMN_ORDER if c in present_keys]
    columns += sorted(k for k in present_keys if k not in columns)

    csv_path = out_dir / "catalog_ch4_west_siberia.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c) for c in columns})
    print(f"WROTE {csv_path} ({len(rows)} rows x {len(columns)} cols)")

    # --- GeoJSON -----------------------------------------------------------
    geojson = {
        "type": "FeatureCollection",
        "name": "RU-PlumeScan CH4 plume catalogue, West Siberian Plain, 2019-2025",
        "crs": {"type": "name",
                "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": [
            {"type": "Feature", "geometry": f.get("geometry"),
             "properties": {c: (f.get("properties") or {}).get(c) for c in columns}}
            for f in features
        ],
    }
    gj_path = out_dir / "catalog_ch4_west_siberia.geojson"
    with gj_path.open("w", encoding="utf-8") as fh:
        json.dump(geojson, fh, ensure_ascii=False, indent=1)
    print(f"WROTE {gj_path}")

    # --- Schema dump -------------------------------------------------------
    schema = collect_schema(rows)
    geom_types = sorted({(f.get("geometry") or {}).get("type", "None")
                         for f in features})
    schema_path = out_dir / "schema_dump.json"
    with schema_path.open("w", encoding="utf-8") as fh:
        json.dump({
            "n_events": len(rows),
            "years": YEARS,
            "geometry_types": geom_types,
            "columns": columns,
            "fields": schema,
        }, fh, ensure_ascii=False, indent=2)
    print(f"WROTE {schema_path} ({len(schema)} fields, geometry {geom_types})")


if __name__ == "__main__":
    main()
