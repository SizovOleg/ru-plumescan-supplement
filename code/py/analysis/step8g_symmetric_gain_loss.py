"""Симметричный замер: что каталог потеряет и что приобретёт при смене кольца.

Тест по событиям (step8e) видит только потери: опубликованные события отобраны
по старой z, поэтому под любым другим оценщиком часть из них уйдёт ниже порога
уже из-за регрессии к среднему. Чтобы сравнение было честным, нужно на тех же
орбитах посчитать и кластеры, которых старое кольцо не давало, а чистое даёт.

Для каждой орбиты, на которой есть опубликованное событие, выполняется полный
производственный расчёт v3.2.0 дважды — с промышленным кольцом (как в v3.1.4)
и с чистым — и после буферного фильтра кластеры сопоставляются по центроидам:

    сохранённые — есть в обоих прогонах (ближе CONTROL_MATCH_KM)
    потерянные  — только в старом
    новые       — только в новом

Орбита берётся по точному `system:time_start`, широтная коррекция — над тем же
AOI, что в производстве. Расчёт по всему AOI, поэтому дорог: см. --roi-km для
ограничения окрестностью событий.

Выход: docs/p_02_0e_symmetric_gain_loss.json

Использование:
    python src/py/analysis/step8g_symmetric_gain_loss.py [--resume] [--limit N]
        [--roi-km 0]   # 0 = весь AOI; иначе прямоугольник ±roi-km вокруг событий орбиты
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
from setup.build_ch4_event_catalog import AOI_BBOX, ANALYSIS_SCALE_M, INDUSTRIAL_MASK_ASSET

BAND = "CH4_column_volume_mixing_ratio_dry_air_bias_corrected"
Z_MIN, MIN_CLUSTER_PX = 3.0, 5
CONTROL_MATCH_KM = 10.0
CATALOG = _REPO_ROOT / "supplement" / "data" / "catalog_ch4_west_siberia.geojson"
OUT = _REPO_ROOT / "docs" / "p_02_0e_symmetric_gain_loss.json"


def km(lon1, lat1, lon2, lat2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def orbits_with_events() -> list:
    gj = json.loads(CATALOG.read_text(encoding="utf-8"))
    by_orbit: dict = {}
    for f in gj["features"]:
        p = f["properties"]
        by_orbit.setdefault(int(p["orbit_date_millis"]), []).append(
            {"event_id": p["event_id"], "lon": p["centroid_lon"], "lat": p["centroid_lat"],
             "max_z": p.get("max_z")})
    return [{"orbit_date_millis": t, "events": evs} for t, evs in sorted(by_orbit.items())]


def clusters(orbit_for_z: ee.Image, ring_mask: ee.Image, ind: ee.Image,
             kernels: tuple, aoi: ee.Geometry) -> list:
    """Полный производственный расчёт до атрибуции: z → порог → кластеры → буферный фильтр."""
    annulus, count_kernel = kernels
    z = detection_ch4.compute_z_local(orbit_for_z, annulus, ring_mask,
                                      annulus_count_kernel=count_kernel, annulus_only=True)
    labels = detection_ch4.extract_clusters(
        z.select("Z_local").gte(Z_MIN).selfMask(),
        min_cluster_px=MIN_CLUSTER_PX, max_size=256, connectedness=8)
    median_band = z.select(f"{BAND}_median_local")
    attrs_in = (z.select("Z_local").rename("z").addBands(median_band)
                .addBands(z.select(f"{BAND}_mad_local")))
    fc = detection_ch4.compute_cluster_attributes(
        labels, orbit_for_z, median_band, attrs_in, aoi, scale_m=ANALYSIS_SCALE_M)
    fc = detection_ch4.filter_candidates_to_buffers(fc, ind)
    out = []
    for f in fc.getInfo().get("features", []):
        p = f.get("properties", {}) or {}
        if p.get("centroid_lon") is None:
            continue
        out.append({"lon": p["centroid_lon"], "lat": p["centroid_lat"],
                    "max_z": p.get("max_z"), "n_pixels": p.get("n_pixels")})
    return out


def run_orbit(rec: dict, ind: ee.Image, kernels: tuple, aoi_full: ee.Geometry,
              roi_km: float) -> dict:
    t0 = time.time()
    orbit = ee.Image(ee.ImageCollection("COPERNICUS/S5P/OFFL/L3_CH4")
                     .filter(ee.Filter.eq("system:time_start", rec["orbit_date_millis"])).first())
    corrected = detection_ch4.apply_latitude_band_correction(orbit, aoi_full)
    orbit_for_z = ee.Image(corrected.select(f"{BAND}_lat_corrected").rename(BAND)
                           .copyProperties(orbit, ["system:time_start"]))
    valid = orbit_for_z.select(BAND).mask()

    if roi_km > 0:
        lons = [e["lon"] for e in rec["events"]]; lats = [e["lat"] for e in rec["events"]]
        dlat = roi_km / 111.0
        dlon = roi_km / (111.0 * abs(math.cos(math.radians(sum(lats) / len(lats)))))
        aoi = ee.Geometry.Rectangle([min(lons) - dlon, min(lats) - dlat,
                                     max(lons) + dlon, max(lats) + dlat])
    else:
        aoi = aoi_full

    old = clusters(orbit_for_z, valid.And(ind.eq(0)).rename("m"), ind, kernels, aoi)
    new = clusters(orbit_for_z, valid.And(ind.eq(1)).rename("m"), ind, kernels, aoi)

    def near(c, pool):
        return any(km(c["lon"], c["lat"], d["lon"], d["lat"]) <= CONTROL_MATCH_KM for d in pool)
    kept = [c for c in old if near(c, new)]
    lost = [c for c in old if not near(c, new)]
    gained = [c for c in new if not near(c, old)]
    return {**rec, "n_old": len(old), "n_new": len(new),
            "kept": len(kept), "lost": len(lost), "gained": len(gained),
            "lost_clusters": lost, "gained_clusters": gained,
            "elapsed_s": round(time.time() - t0, 1)}


def summarize(results: list) -> dict:
    return {
        "orbits": len(results),
        "clusters_old_ring": sum(r["n_old"] for r in results),
        "clusters_clean_ring": sum(r["n_new"] for r in results),
        "kept": sum(r["kept"] for r in results),
        "lost": sum(r["lost"] for r in results),
        "gained": sum(r["gained"] for r in results),
        "published_events_on_these_orbits": sum(len(r["events"]) for r in results),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--roi-km", type=float, default=0.0)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    todo = orbits_with_events()
    if args.limit:
        todo = todo[:args.limit]
    results: list = []
    if args.resume and Path(args.out).exists():
        results = json.loads(Path(args.out).read_text(encoding="utf-8"))["results"]
    done = {r["orbit_date_millis"] for r in results}

    ind = ee.Image(INDUSTRIAL_MASK_ASSET)
    kernels = (detection_ch4.build_annulus_kernel(), detection_ch4.build_annulus_count_kernel())
    aoi_full = ee.Geometry.Rectangle(list(AOI_BBOX))

    for i, rec in enumerate(todo, 1):
        if rec["orbit_date_millis"] in done:
            continue
        r = run_orbit(rec, ind, kernels, aoi_full, args.roi_km)
        results.append(r)
        print(f"{i:3d}/{len(todo)} орбита {rec['orbit_date_millis']}: старое кольцо {r['n_old']}, "
              f"чистое {r['n_new']} | сохранено {r['kept']}, потеряно {r['lost']}, "
              f"новых {r['gained']} | событий на орбите {len(rec['events'])} | {r['elapsed_s']} с",
              flush=True)
        Path(args.out).write_text(json.dumps(
            {"config": {"roi_km": args.roi_km, "match_km": CONTROL_MATCH_KM},
             "summary": summarize(results), "results": results},
            ensure_ascii=False, indent=2), encoding="utf-8")

    print("\nСВОДКА:", json.dumps(summarize(results), ensure_ascii=False))
    print("DONE" if len(results) >= len(todo) else f"осталось {len(todo) - len(results)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
