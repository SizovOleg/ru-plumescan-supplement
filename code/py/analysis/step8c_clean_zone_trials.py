"""Знаменатель для оценки частоты ложных срабатываний по контрольным зонам.

В статье сказано, что нулевое число достоверных событий в заповедниках не
переводится в частоту ложных детекций, поскольку не учитывалось число
наблюдений над этими зонами. Скрипт считает именно это число.

Единица испытания — пара «заповедник × орбита»: орбитальный снимок L3, у
которого внутри границ заповедника есть хотя бы MIN_CLUSTER_PX валидных
восстановлений XCH4, то есть кластер минимального размера в принципе мог бы
быть выделен. Учитываются только заповедники в границах Западно-Сибирской
равнины — Юганский и Верхне-Тазовский; Кузнецкий Алатау и Алтайский лежат за
её пределами и в метрики каталога не входят.

Полученное число — верхняя оценка количества возможностей: требование к
обеспеченности фонового кольца (не менее 50 валидных пикселей в интервале
50-150 км) дополнительно сокращает его, поэтому частота ложных срабатываний
на одно испытание, посчитанная по этому знаменателю, занижена.

Выход: docs/p_02_0e_clean_zone_trials.json

Использование:
    python src/py/analysis/step8c_clean_zone_trials.py [--out FILE]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]

import ee

ee.Initialize(project="nodal-thunder-481307-u1")

BAND = "CH4_column_volume_mixing_ratio_dry_air_bias_corrected"
PROTECTED = ("projects/nodal-thunder-481307-u1/assets/"
             "RuPlumeScan/reference/protected_areas")
ZONES_IN_PLAIN = ("yugansky", "verkhnetazovsky")
YEARS = range(2019, 2026)
MONTHS = range(3, 11)          # сезон обработки: март-октябрь
MIN_CLUSTER_PX = 5
SCALE_M = 7000


def wilson(k: int, n: int, z: float = 1.96) -> tuple:
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, max(0.0, centre - half), min(1.0, centre + half))


def counts_for(zone_geom: ee.Geometry, year: int) -> list:
    """Число валидных пикселей внутри зоны для каждой орбиты сезона."""
    coll = (ee.ImageCollection("COPERNICUS/S5P/OFFL/L3_CH4")
            .filterDate(f"{year}-03-01", f"{year}-11-01")
            .filter(ee.Filter.calendarRange(MONTHS[0], MONTHS[-1], "month"))
            .filterBounds(zone_geom)
            .select(BAND))

    def count(img):
        n = img.reduceRegion(reducer=ee.Reducer.count(), geometry=zone_geom,
                             scale=SCALE_M, maxPixels=1e8).get(BAND)
        return ee.Feature(None, {"n": n})

    # filterBounds на этой коллекции почти не сужает выборку: у снимков L3
    # широкая заявленная рамка. Снимки без перекрытия дают нулевой счёт и
    # отсеиваются порогом, поэтому на число испытаний это не влияет.
    return (coll.map(count).aggregate_array("n")).getInfo()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(_REPO_ROOT / "docs" / "p_02_0e_clean_zone_trials.json"))
    args = ap.parse_args()

    fc = ee.FeatureCollection(PROTECTED)
    per_zone = {}
    total_trials = 0
    for zid in ZONES_IN_PLAIN:
        zone = fc.filter(ee.Filter.eq("zone_id", zid)).first()
        geom = ee.Feature(zone).geometry()
        name = ee.Feature(zone).get("zone_name_ru").getInfo()
        area = geom.area(1000).getInfo() / 1e6
        years = {}
        for y in YEARS:
            counts = counts_for(geom, y)
            trials = sum(1 for c in counts if c is not None and c >= MIN_CLUSTER_PX)
            years[str(y)] = {"images_scanned": len(counts), "trials": trials}
            total_trials += trials
            print(f"  {name} {y}: снимков просмотрено {len(counts):4d}, испытаний {trials:4d}")
        per_zone[zid] = {"name_ru": name, "area_km2": round(area, 0), "by_year": years,
                         "trials": sum(v["trials"] for v in years.values())}

    # Ложные срабатывания в этих зонах по опубликованному каталогу
    import csv
    cat = list(csv.DictReader(
        open(_REPO_ROOT / "supplement" / "data" / "catalog_ch4_west_siberia.csv",
             encoding="utf-8")))
    in_zone = [r for r in cat if r.get("inside_reference_clean_zone") == "1"]
    reliable = [r for r in in_zone if r.get("artifact_likely") == "0"]

    p_any, lo_any, hi_any = wilson(len(in_zone), total_trials)
    p_rel, lo_rel, hi_rel = wilson(len(reliable), total_trials)

    payload = {
        "test": "число испытаний над контрольными зонами и частота ложных срабатываний",
        "definition": ("испытание — пара «заповедник × орбита» с не менее чем "
                       f"{MIN_CLUSTER_PX} валидными восстановлениями XCH4 внутри зоны"),
        "caveat": ("знаменатель завышен: требование обеспеченности фонового кольца "
                   "дополнительно сокращает число возможностей, поэтому частота на "
                   "одно испытание занижена"),
        "season_months": [MONTHS[0], MONTHS[-1]],
        "years": [YEARS[0], YEARS[-1]],
        "zones": per_zone,
        "total_trials": total_trials,
        "detections_in_zones": {
            "any": len(in_zone),
            "reliable": len(reliable),
            "event_ids": [r["event_id"] for r in in_zone],
        },
        "false_alarm_rate_per_trial": {
            "any": {"k": len(in_zone), "n": total_trials, "p": round(p_any, 5),
                    "ci95": [round(lo_any, 5), round(hi_any, 5)]},
            "reliable": {"k": len(reliable), "n": total_trials, "p": round(p_rel, 5),
                         "ci95": [round(lo_rel, 5), round(hi_rel, 5)]},
        },
    }
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print(f"\nвсего испытаний: {total_trials}")
    print(f"детекций в зонах: всего {len(in_zone)}, достоверных {len(reliable)}")
    print(f"частота на испытание (любые):     {p_any:.5f} [{lo_any:.5f}; {hi_any:.5f}]")
    print(f"частота на испытание (достоверные): {p_rel:.5f} [{lo_rel:.5f}; {hi_rel:.5f}]")
    print(f"записано -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
