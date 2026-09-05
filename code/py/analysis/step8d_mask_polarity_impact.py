"""Замер влияния полярности индустриальной маски на оценку фона.

См. docs/FINDING_mask_polarity.md. Ассет `proxy_mask_buffered_per_type` кодирует
единицей ЧИСТЫЕ пиксели, а `apply_two_condition_mask` трактует единицу как
промышленный пиксель и берёт `.eq(0)`. В результате медиана и MAD фонового
кольца считались по промышленно-буферизованным пикселям.

Скрипт считает z-поле дважды на одном и том же входе — как в производственном
конвейере и как задумано — и сравнивает медиану, MAD и саму z-оценку в одних и
тех же точках. Ничего не пересобирает и не пишет в ассеты.

Выход: docs/p_02_0e_mask_polarity_impact.json

Использование:
    python src/py/analysis/step8d_mask_polarity_impact.py [--points 200]
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT / "src" / "py") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src" / "py"))

import ee

ee.Initialize(project="nodal-thunder-481307-u1")

from rca import detection_ch4
from setup.build_ch4_event_catalog import INDUSTRIAL_MASK_ASSET

BAND = "CH4_column_volume_mixing_ratio_dry_air_bias_corrected"

# Две площадки: газодобыча Ямала (эталонное событие 8 июля 2021) и плотно
# освоенный нефтяной пояс, где доля промышленного буфера максимальна
REGIONS = [
    ("Бованенково", 68.79, 70.45, "2021-07-05", "2021-07-12"),
    ("Сургут — Нижневартовск", 74.5, 61.0, "2021-07-05", "2021-07-12"),
]
ROI_KM = 200.0


def z_field(mosaic: ee.Image, mask: ee.Image, kernels: tuple) -> ee.Image:
    annulus, count_kernel = kernels
    return detection_ch4.compute_z_local(
        mosaic, annulus, mask, annulus_count_kernel=count_kernel, annulus_only=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--points", type=int, default=200)
    ap.add_argument("--out", default=str(_REPO_ROOT / "docs" / "p_02_0e_mask_polarity_impact.json"))
    args = ap.parse_args()

    industrial = ee.Image(INDUSTRIAL_MASK_ASSET)
    kernels = (detection_ch4.build_annulus_kernel(),
               detection_ch4.build_annulus_count_kernel())

    out = []
    for name, lon, lat, d0, d1 in REGIONS:
        dlat = ROI_KM / 111.0
        dlon = ROI_KM / (111.0 * abs(__import__("math").cos(__import__("math").radians(lat))))
        aoi = ee.Geometry.Rectangle([lon - dlon, lat - dlat, lon + dlon, lat + dlat])
        coll = (ee.ImageCollection("COPERNICUS/S5P/OFFL/L3_CH4")
                .filterDate(d0, d1).filterBounds(aoi).select(BAND))
        mosaic = ee.Image(coll.mosaic())

        valid = mosaic.select(BAND).mask()
        # как считает конвейер сейчас: eq(0) на ассете, где 0 = промышленный
        mask_now = valid.And(industrial.eq(0)).rename("m")
        # как задумано в Algorithm §3.6: фон по чистым пикселям
        mask_fix = valid.And(industrial.eq(1)).rename("m")

        z_now, z_fix = z_field(mosaic, mask_now, kernels), z_field(mosaic, mask_fix, kernels)
        stack = (z_now.select(["Z_local", f"{BAND}_median_local", f"{BAND}_mad_local"],
                              ["z_now", "med_now", "mad_now"])
                 .addBands(z_fix.select(["Z_local", f"{BAND}_median_local", f"{BAND}_mad_local"],
                                        ["z_fix", "med_fix", "mad_fix"])))

        # sample() на перепроецированном изображении возвращает пусто, поэтому
        # точки задаются регулярной сеткой и снимаются через reduceRegions
        import math as _m
        side = int(_m.sqrt(args.points))
        step_lat, step_lon = 2 * dlat / (side + 1), 2 * dlon / (side + 1)
        grid = ee.FeatureCollection([
            ee.Feature(ee.Geometry.Point([lon - dlon + step_lon * (i + 1),
                                          lat - dlat + step_lat * (j + 1)]))
            for i in range(side) for j in range(side)])
        pts = stack.reduceRegions(collection=grid, reducer=ee.Reducer.first(), scale=5500)
        rows = [f["properties"] for f in pts.getInfo().get("features", [])]
        rows = [r for r in rows if all(r.get(k) is not None for k in
                                       ("med_now", "med_fix", "mad_now", "mad_fix", "z_now", "z_fix"))]
        if not rows:
            print(f"{name}: точек с обеими оценками нет")
            continue

        d_med = [r["med_fix"] - r["med_now"] for r in rows]
        d_mad = [r["mad_fix"] - r["mad_now"] for r in rows]
        d_z = [r["z_fix"] - r["z_now"] for r in rows]
        rec = {
            "region": name, "n_points": len(rows),
            "median_local": {"now": round(st.median([r["med_now"] for r in rows]), 2),
                             "fixed": round(st.median([r["med_fix"] for r in rows]), 2),
                             "delta_median_ppb": round(st.median(d_med), 2)},
            "mad_local": {"now": round(st.median([r["mad_now"] for r in rows]), 2),
                          "fixed": round(st.median([r["mad_fix"] for r in rows]), 2),
                          "delta_median_ppb": round(st.median(d_mad), 2)},
            "z": {"now": round(st.median([r["z_now"] for r in rows]), 2),
                  "fixed": round(st.median([r["z_fix"] for r in rows]), 2),
                  "delta_median": round(st.median(d_z), 2),
                  "delta_p90": round(sorted(d_z)[int(0.9 * (len(d_z) - 1))], 2)},
            "crossing_threshold": {
                "now_above_3": sum(1 for r in rows if r["z_now"] >= 3.0),
                "fixed_above_3": sum(1 for r in rows if r["z_fix"] >= 3.0),
            },
        }
        out.append(rec)
        print(f"\n=== {name} ({len(rows)} точек) ===")
        print(f"  медиана кольца: сейчас {rec['median_local']['now']} -> "
              f"исправленная {rec['median_local']['fixed']} ppb "
              f"(сдвиг {rec['median_local']['delta_median_ppb']:+})")
        print(f"  MAD кольца:     сейчас {rec['mad_local']['now']} -> "
              f"{rec['mad_local']['fixed']} ppb "
              f"(сдвиг {rec['mad_local']['delta_median_ppb']:+})")
        print(f"  z-оценка:       медианный сдвиг {rec['z']['delta_median']:+}, "
              f"90-й процентиль {rec['z']['delta_p90']:+}")
        print(f"  пикселей выше порога z=3: сейчас "
              f"{rec['crossing_threshold']['now_above_3']}, "
              f"после правки {rec['crossing_threshold']['fixed_above_3']}")

    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nзаписано -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
