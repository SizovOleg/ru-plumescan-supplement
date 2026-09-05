"""Частота ложных срабатываний детектора аномалий на чистом фоне — по-честному.

Оценка «0 из 1064 испытаний» (step8c) недействительна: детектор в обеих
версиях не может выдать кандидата вне промышленных буферов, а заповедники лежат
в буферах на 15 % (Юганский) и 0 % (Верхне-Тазовский). Здесь детектор
прогоняется над заповедниками **до** буферного фильтра — измеряется свойство
самого выделения аномалий, а не конструкции конвейера.

Испытание, как в step8c: пара «заповедник × орбита» с не менее чем пятью
валидными восстановлениями внутри зоны (сезон март–октябрь, 2019–2025). Для
каждого испытания воспроизводится производственный расчёт v3.2.0 (широтная
коррекция, кольцо из чистых пикселей, порог z ≥ 3, кластер ≥ 5 пикселей,
восьмисвязность) и считается число кластеров, задевающих зону.

Отличие от производства: широтная коррекция считается над окрестностью зоны
(±200 км), а не над всем AOI — иначе стоимость 1064 прогонов непомерна.
Медиана полосы по меньшей ширине отличается на второй порядок.

Измеряется частота на стадии кандидатов: каскад диагностики артефактов
(снег, альбедо) здесь не применяется, так что оценка — верхняя.

Выход: docs/p_02_0e_clean_zone_false_alarms.json

Использование:
    python src/py/analysis/step8f_clean_zone_false_alarms.py [--resume]
        [--zones yugansky,verkhnetazovsky] [--years 2019-2025] [--months 3-10]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT / "src" / "py") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src" / "py"))

import ee

ee.Initialize(project="nodal-thunder-481307-u1")

from rca import detection_ch4
from setup.build_ch4_event_catalog import INDUSTRIAL_MASK_ASSET

BAND = "CH4_column_volume_mixing_ratio_dry_air_bias_corrected"
PROTECTED = ("projects/nodal-thunder-481307-u1/assets/"
             "RuPlumeScan/reference/protected_areas")
MIN_VALID_PX = 5          # критерий испытания, как в step8c
TRIAL_SCALE_M = 7000
Z_MIN, MIN_CLUSTER_PX = 3.0, 5
OUT = _REPO_ROOT / "docs" / "p_02_0e_clean_zone_false_alarms.json"


def wilson(k: int, n: int, z: float = 1.96) -> tuple:
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, max(0.0, c - h), min(1.0, c + h))


def month_range(year: int, month: int) -> tuple:
    nm, ny = (month + 1, year) if month < 12 else (1, year + 1)
    return f"{year}-{month:02d}-01", f"{ny}-{nm:02d}-01"


def build_chunk(zone: ee.Geometry, aoi: ee.Geometry, year: int, month: int,
                ind: ee.Image, kernels: tuple) -> ee.FeatureCollection:
    """Испытания месяца и их детекции — целиком на сервере."""
    d0, d1 = month_range(year, month)
    coll = (ee.ImageCollection("COPERNICUS/S5P/OFFL/L3_CH4")
            .filterDate(d0, d1).filterBounds(zone).select(BAND))

    def with_count(img):
        n = img.reduceRegion(ee.Reducer.count(), zone, TRIAL_SCALE_M, maxPixels=int(1e8)).get(BAND)
        return img.set("n_valid_zone", n)

    trials = coll.map(with_count).filter(ee.Filter.gte("n_valid_zone", MIN_VALID_PX))
    annulus, count_kernel = kernels

    def detect(img):
        img = ee.Image(img)
        corrected = detection_ch4.apply_latitude_band_correction(img, aoi)
        ofz = ee.Image(corrected.select(f"{BAND}_lat_corrected").rename(BAND)
                       .copyProperties(img, ["system:time_start"]))
        valid = ofz.select(BAND).mask()
        z = detection_ch4.compute_z_local(
            ofz, annulus, valid.And(ind.eq(1)).rename("m"), annulus_count_kernel=count_kernel, annulus_only=True)
        labels = detection_ch4.extract_clusters(
            z.select("Z_local").gte(Z_MIN).selfMask(),
            min_cluster_px=MIN_CLUSTER_PX, max_size=256, connectedness=8)
        # countDistinct на полностью маскированной области возвращал 1 —
        # считаем через список значений незамаскированных пикселей: toList
        # берёт только их, пустая область даёт пустой список
        kw = dict(geometry=zone, scale=5500, maxPixels=int(1e8))
        label_list = ee.List(labels.reduceRegion(ee.Reducer.toList(), **kw).get("labels"))
        n_cl = label_list.distinct().size()
        # число пикселей значимых кластеров внутри зоны — независимый критерий
        sig_px = labels.mask().rename("sig").reduceRegion(
            ee.Reducer.sum().unweighted(), **kw).get("sig")
        mz = z.select("Z_local").reduceRegion(ee.Reducer.max(), **kw).get("Z_local")
        return ee.Feature(None, {
            "orbit": img.get("system:index"), "t": img.get("system:time_start"),
            "n_valid_zone": img.get("n_valid_zone"),
            "n_clusters": n_cl, "n_cluster_px_in_zone": sig_px, "max_z": mz,
        })

    return trials.map(detect)


def run_chunk(zone, aoi, year, month, ind, kernels) -> list:
    """Сначала одним запросом; при отказе — поорбитно."""
    fc = build_chunk(zone, aoi, year, month, ind, kernels)
    try:
        return [f["properties"] for f in fc.getInfo().get("features", [])]
    except Exception as exc:  # таймаут или квота на пакет — дробим
        msg = str(exc)
        if "quota" in msg.lower():
            raise
        print(f"    пакет не прошёл ({msg[:80]}), поорбитно…", flush=True)
        n = fc.size().getInfo()
        lst = fc.toList(n)
        out = []
        for i in range(n):
            out.append(ee.Feature(lst.get(i)).getInfo()["properties"])
        return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zones", default="yugansky,verkhnetazovsky")
    ap.add_argument("--years", default="2019-2025")
    ap.add_argument("--months", default="3-10")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    y0, y1 = (int(x) for x in args.years.split("-"))
    m0, m1 = (int(x) for x in args.months.split("-"))

    store = {"chunks": {}, "summary": {}}
    if args.resume and Path(args.out).exists():
        store = json.loads(Path(args.out).read_text(encoding="utf-8"))

    fc = ee.FeatureCollection(PROTECTED)
    ind = ee.Image(INDUSTRIAL_MASK_ASSET)
    kernels = (detection_ch4.build_annulus_kernel(), detection_ch4.build_annulus_count_kernel())

    zones = {}
    for zid in args.zones.split(","):
        g = ee.Feature(fc.filter(ee.Filter.eq("zone_id", zid)).first()).geometry()
        zones[zid] = (g, g.bounds().buffer(200000).bounds())

    todo = [(z, y, m) for z in zones for y in range(y0, y1 + 1) for m in range(m0, m1 + 1)]
    for zid, year, month in todo:
        key = f"{zid}_{year}_{month:02d}"
        if key in store["chunks"]:
            continue
        t0 = time.time()
        zone, aoi = zones[zid]
        rows = run_chunk(zone, aoi, year, month, ind, kernels)
        n_tr = len(rows)
        n_fa = sum(1 for r in rows if (r.get("n_cluster_px_in_zone") or 0) >= 1)
        n_cl = sum(int(r.get("n_clusters") or 0) for r in rows)
        store["chunks"][key] = {"zone": zid, "year": year, "month": month,
                                "trials": n_tr, "trials_with_cluster": n_fa,
                                "clusters": n_cl, "rows": rows}
        # сводка пересчитывается после каждого куска — обрыв не обнуляет
        tr = sum(c["trials"] for c in store["chunks"].values())
        fa = sum(c["trials_with_cluster"] for c in store["chunks"].values())
        cl = sum(c["clusters"] for c in store["chunks"].values())
        p, lo, hi = wilson(fa, tr)
        store["summary"] = {"trials": tr, "trials_with_cluster": fa, "clusters": cl,
                            "rate_per_trial": round(p, 5), "ci95": [round(lo, 5), round(hi, 5)],
                            "chunks_done": len(store["chunks"]), "chunks_total": len(todo)}
        Path(args.out).write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{key}: испытаний {n_tr:3d}, с кластером {n_fa:2d}, кластеров {n_cl:2d}  "
              f"[всего {tr}, срабатываний {fa}]  {time.time()-t0:.0f} с", flush=True)

    s = store["summary"]
    print(f"\nИТОГ: испытаний {s.get('trials')}, испытаний с кластером {s.get('trials_with_cluster')}, "
          f"частота {s.get('rate_per_trial')} {s.get('ci95')}")
    print("DONE" if s.get("chunks_done") == s.get("chunks_total") else "не завершено")
    return 0


if __name__ == "__main__":
    sys.exit(main())
