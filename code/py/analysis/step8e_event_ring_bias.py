"""Влияние состава фонового кольца на 122 опубликованных события.

См. docs/FINDING_mask_polarity.md. Опубликованный каталог (v3.1.4) оценивал фон
по промышленно-буферизованным пикселям кольца; v3.2.0 — по чистым. Вопрос,
который решает этот скрипт: сколько опубликованных событий изменится, если
поменять только состав кольца, ничего больше не трогая.

Для каждого события воспроизводится производственный расчёт на той же орбите
(точный `system:time_start`), с той же широтной коррекцией и тем же AOI, и z
считается дважды на одних и тех же пикселях полигона события:

    z_old — кольцо из промышленных пикселей (как в опубликованном каталоге)
    z_new — кольцо из чистых пикселей (v3.2.0)

Совпадение max(z_old) с опубликованным max_z — встроенная проверка того, что
воспроизведение точное. Пересборка не выполняется, ассеты не пишутся.

Выход: docs/p_02_0e_event_ring_bias.json — запись на событие плюс сводка.

Использование:
    python src/py/analysis/step8e_event_ring_bias.py [--only ID,ID] [--resume]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT / "src" / "py") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src" / "py"))

import ee

ee.Initialize(project="nodal-thunder-481307-u1")

from rca import detection_ch4
from setup.build_ch4_event_catalog import AOI_BBOX, ANALYSIS_SCALE_M, INDUSTRIAL_MASK_ASSET

BAND = "CH4_column_volume_mixing_ratio_dry_air_bias_corrected"
Z_MIN = 3.0
CATALOG = _REPO_ROOT / "supplement" / "data" / "catalog_ch4_west_siberia.geojson"
OUT = _REPO_ROOT / "docs" / "p_02_0e_event_ring_bias.json"


def load_events() -> list:
    gj = json.loads(CATALOG.read_text(encoding="utf-8"))
    out = []
    for f in gj["features"]:
        p = f["properties"]
        out.append({
            "event_id": p["event_id"], "year": p.get("year"),
            "orbit_date_millis": int(p["orbit_date_millis"]),
            "max_z_published": p.get("max_z"), "n_pixels_published": p.get("n_pixels"),
            "artifact_likely": p.get("artifact_likely"),
            "geometry": f["geometry"],
        })
    return out


def measure(ev: dict, ind: ee.Image, kernels: tuple, aoi: ee.Geometry) -> dict:
    t0 = time.time()
    orbit = ee.Image(
        ee.ImageCollection("COPERNICUS/S5P/OFFL/L3_CH4")
        .filter(ee.Filter.eq("system:time_start", ev["orbit_date_millis"]))
        .first())
    # Производственная подготовка: широтная коррекция над тем же AOI
    corrected = detection_ch4.apply_latitude_band_correction(orbit, aoi)
    orbit_for_z = ee.Image(corrected.select(f"{BAND}_lat_corrected").rename(BAND)
                           .copyProperties(orbit, ["system:time_start"]))
    valid = orbit_for_z.select(BAND).mask()
    annulus, count_kernel = kernels
    z_old = detection_ch4.compute_z_local(
        orbit_for_z, annulus, valid.And(ind.eq(0)).rename("m"), annulus_count_kernel=count_kernel, annulus_only=True)
    z_new = detection_ch4.compute_z_local(
        orbit_for_z, annulus, valid.And(ind.eq(1)).rename("m"), annulus_count_kernel=count_kernel, annulus_only=True)

    poly = ee.Geometry(ev["geometry"])
    stack = (z_old.select("Z_local").rename("z_old")
             .addBands(z_new.select("Z_local").rename("z_new"))
             .addBands(z_old.select("Z_local").gte(Z_MIN).rename("px_old"))
             .addBands(z_new.select("Z_local").gte(Z_MIN).rename("px_new"))
             .addBands(z_new.select(f"{BAND}_n_local").rename("n_local_new"))
             .addBands(z_old.select(f"{BAND}_median_local").rename("med_old"))
             .addBands(z_new.select(f"{BAND}_median_local").rename("med_new")))
    # Разные редьюсеры нельзя объединить (веса), поэтому четыре reduceRegion
    # склеиваются на сервере в один словарь — один запрос на событие
    kw = dict(geometry=poly, scale=ANALYSIS_SCALE_M, maxPixels=int(1e8))
    r = (stack.select(["z_old", "z_new"]).reduceRegion(ee.Reducer.max(), **kw)
         .combine(stack.select(["px_old", "px_new"]).reduceRegion(ee.Reducer.sum().unweighted(), **kw))
         .combine(stack.select(["n_local_new"]).reduceRegion(ee.Reducer.min(), **kw))
         .combine(stack.select(["med_old", "med_new"]).reduceRegion(ee.Reducer.median(), **kw))
         ).getInfo()
    pick = r.get
    rec = {k: ev[k] for k in ("event_id", "year", "orbit_date_millis",
                              "max_z_published", "n_pixels_published", "artifact_likely")}
    rec.update({
        "max_z_old": pick("z_old"), "max_z_new": pick("z_new"),
        "n_px_ge3_old": pick("px_old"), "n_px_ge3_new": pick("px_new"),
        "min_n_local_new": pick("n_local_new"),
        "median_ring_old": pick("med_old"), "median_ring_new": pick("med_new"),
        "elapsed_s": round(time.time() - t0, 1),
    })
    zo, zn = rec["max_z_old"], rec["max_z_new"]
    rec["reproduction_ok"] = (zo is not None and rec["max_z_published"] is not None
                              and abs(zo - rec["max_z_published"]) < 0.5)
    rec["survives_new"] = bool(zn is not None and zn >= Z_MIN
                               and (rec["n_px_ge3_new"] or 0) >= 5)
    return rec


def summarize(results: list) -> dict:
    done = [r for r in results if r.get("max_z_old") is not None]
    repro = [r for r in done if r.get("reproduction_ok")]
    lost = [r for r in done if not r.get("survives_new")]
    dz = sorted((r["max_z_new"] - r["max_z_old"]) for r in done if r.get("max_z_new") is not None)
    q = lambda p: dz[int(p * (len(dz) - 1))] if dz else None
    return {
        "n_measured": len(done), "n_reproduced_within_0_5": len(repro),
        "n_lost_under_new_ring": len(lost), "lost_ids": [r["event_id"] for r in lost],
        "delta_max_z": {"median": q(0.5), "p10": q(0.1), "p90": q(0.9)} if dz else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="список event_id через запятую")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    events = load_events()
    if args.only:
        keep = set(args.only.split(","))
        events = [e for e in events if e["event_id"] in keep]

    results: list = []
    if args.resume and Path(args.out).exists():
        results = json.loads(Path(args.out).read_text(encoding="utf-8"))["results"]
    done_ids = {r["event_id"] for r in results}

    ind = ee.Image(INDUSTRIAL_MASK_ASSET)
    kernels = (detection_ch4.build_annulus_kernel(), detection_ch4.build_annulus_count_kernel())
    aoi = ee.Geometry.Rectangle(list(AOI_BBOX))

    for i, ev in enumerate(events, 1):
        if ev["event_id"] in done_ids:
            continue
        rec = measure(ev, ind, kernels, aoi)
        results.append(rec)
        print(f"{i:3d}/{len(events)} {rec['event_id']}  опубл. {rec['max_z_published']:.2f} | "
              f"воспр. {rec['max_z_old'] if rec['max_z_old'] is None else round(rec['max_z_old'],2)} | "
              f"новое кольцо {rec['max_z_new'] if rec['max_z_new'] is None else round(rec['max_z_new'],2)} | "
              f"px≥3 {rec['n_px_ge3_old']}→{rec['n_px_ge3_new']} | "
              f"{'СОХРАНЯЕТСЯ' if rec['survives_new'] else 'ТЕРЯЕТСЯ'} | {rec['elapsed_s']} с", flush=True)
        Path(args.out).write_text(json.dumps(
            {"summary": summarize(results), "results": results}, ensure_ascii=False, indent=2),
            encoding="utf-8")

    s = summarize(results)
    print("\nСВОДКА:", json.dumps(s, ensure_ascii=False))
    print("DONE" if len(results) >= len(events) else f"осталось {len(events) - len(results)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
