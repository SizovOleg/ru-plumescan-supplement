"""Оценка вероятности обнаружения по парному синтетическому тесту.

Переделка Шага 8a. В прежней схеме восстановлением считался любой кластер в
радиусе 50 км от точки инъекции, а контрольного прогона без инъекции не было —
поэтому детекция, которая существовала бы и без добавки, засчитывалась как
успех. Кроме того, инъекция выполнялась поверх `unmask(1880)` по всей сцене:
в областях постоянного значения MAD в кольце обращается в ноль и z-оценка
уходит в тысячи, порождая ложные кластеры (в прежнем прогоне 10–14 на сцену
против 1–2 в норме).

Здесь обе причины сняты:

* прогон выполняется дважды на одном и том же входе — с инъекцией и без неё;
  восстановлением считается кластер, появившийся только в прогоне с инъекцией;
* глобальный unmask не применяется, маскирование совпадает с промышленным
  конвейером. Наличие валидного восстановления XCH4 в точке инъекции
  фиксируется отдельно, поэтому пропуск из-за отсутствия данных отделим от
  пропуска из-за слабости сигнала.

Выход: docs/p_02_0e_synthetic_pod.json — по одной записи на инъекцию плюс
сводка с доверительными интервалами Уилсона.

Использование:
    python src/py/analysis/step8b_synthetic_pod.py [--n 40] [--out FILE]
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import random
import sys
import time
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT / "src" / "py") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src" / "py"))

import ee

ee.Initialize(project="nodal-thunder-481307-u1")

from rca import detection_ch4
from rca.detection_helpers import prepare_source_points_categories
from setup.build_ch4_event_catalog import INDUSTRIAL_MASK_ASSET, SOURCE_POINTS_ASSET

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("step8b_pod")

BAND = "CH4_column_volume_mixing_ratio_dry_air_bias_corrected"

# Параметры теста сохранены от Шага 8a, чтобы результаты были сопоставимы
FLUX_MIN_T_H, FLUX_MAX_T_H = 1.0, 10.0
PPB_PER_T_PER_H_TEST_SCALE = 8.0   # тестовый масштаб, не физическая калибровка
GAUSSIAN_RADIUS_KM = 15.0
RECOVERY_RADIUS_KM = 50.0
DATE_START, DATE_END = "2024-07-10", "2024-07-20"
AOI_BBOX = (60.0, 50.0, 95.0, 75.0)
Z_MIN, MIN_CLUSTER_PX = 3.0, 5
ROI_BUFFER_KM = 200.0
RANDOM_SEED = 20260514

# Кластер прогона с инъекцией считается новым, если ни один контрольный кластер
# не лежит ближе этого расстояния: разброс центроида между прогонами мал,
# поэтому порог намеренно жёсткий.
CONTROL_MATCH_KM = 10.0


def wilson(k: int, n: int, z: float = 1.96) -> tuple:
    """Доверительный интервал Уилсона для доли."""
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, max(0.0, centre - half), min(1.0, centre + half))


def sample_sites(n: int, source_points: ee.FeatureCollection) -> list:
    aoi = ee.Geometry.Rectangle(list(AOI_BBOX))
    pool = source_points.filterBounds(aoi)
    total = pool.size().getInfo()
    logger.info("источников в AOI: %d", total)
    if total < n:
        raise ValueError(f"источников меньше запрошенного ({total} < {n})")
    feats = pool.toList(total).getInfo()
    rand = random.Random(RANDOM_SEED)
    return [tuple(f["geometry"]["coordinates"]) for f in rand.sample(feats, n)]


def inject(image: ee.Image, lon: float, lat: float, amplitude_ppb: float) -> ee.Image:
    """Добавить дисковую аномалию, не снимая штатную маску.

    Диск задаётся как 0 вне буфера, поэтому сложение не меняет остальную сцену,
    а замаскированные пиксели остаются замаскированными: пропуск из-за
    отсутствия восстановления фиксируется как пропуск, а не маскируется
    заполнением фона.
    """
    pt = ee.Geometry.Point([lon, lat])
    disk = (ee.Image.constant(amplitude_ppb)
            .clip(pt.buffer(GAUSSIAN_RADIUS_KM * 1000))
            .unmask(0, sameFootprint=False)
            .rename(BAND))
    return ee.Image(image.add(disk).copyProperties(image, ["system:time_start"]))


def detect(image: ee.Image, aoi: ee.Geometry, kernels: tuple,
           industrial_mask: ee.Image) -> list:
    """Прогнать Path E и вернуть кластеры плюс z-изображение."""
    annulus_kernel, annulus_count_kernel = kernels
    proxy_mask = detection_ch4.apply_two_condition_mask(image, industrial_mask)
    z_image = detection_ch4.compute_z_local(
        image, annulus_kernel, proxy_mask,
        annulus_count_kernel=annulus_count_kernel)

    mask = z_image.select("Z_local").gte(Z_MIN).selfMask()
    clusters = detection_ch4.extract_clusters(
        mask, min_cluster_px=MIN_CLUSTER_PX, max_size=256, connectedness=8)

    median_band = z_image.select(f"{BAND}_median_local")
    attrs_input = (z_image.select("Z_local").rename("z")
                   .addBands(median_band)
                   .addBands(z_image.select(f"{BAND}_mad_local")))
    fc = detection_ch4.compute_cluster_attributes(
        clusters, image, median_band, attrs_input, aoi, scale_m=7000)

    out = []
    for f in fc.getInfo().get("features", []):
        p = f.get("properties", {}) or {}
        out.append({"lon": p.get("centroid_lon"), "lat": p.get("centroid_lat"),
                    "max_z": p.get("max_z"), "n_pixels": p.get("n_pixels")})
    return out, z_image


def km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def run_site(lon: float, lat: float, flux: float, kernels: tuple,
             industrial_mask: ee.Image) -> dict:
    t0 = time.time()
    amplitude = flux * PPB_PER_T_PER_H_TEST_SCALE
    dlat = ROI_BUFFER_KM / 111.0
    dlon = ROI_BUFFER_KM / (111.0 * abs(math.cos(math.radians(lat))))
    aoi = ee.Geometry.Rectangle([lon - dlon, lat - dlat, lon + dlon, lat + dlat])

    coll = (ee.ImageCollection("COPERNICUS/S5P/OFFL/L3_CH4")
            .filterDate(DATE_START, DATE_END).filterBounds(aoi).select(BAND))
    n_orbits = coll.size().getInfo()
    base = {"lon": lon, "lat": lat, "flux_t_h": flux, "amplitude_ppb": amplitude,
            "n_orbits": n_orbits}
    if n_orbits == 0:
        return {**base, "recovered": False, "reason": "нет орбит", "elapsed_s": 0.0}

    first = ee.Image(coll.first())
    mosaic = ee.Image(ee.Image(coll.mosaic()).copyProperties(first, ["system:time_start"]))

    # Есть ли валидное восстановление в точке инъекции — отделяет пропуск
    # из-за отсутствия данных от пропуска из-за слабости сигнала
    at_point = mosaic.reduceRegion(
        reducer=ee.Reducer.count(),
        geometry=ee.Geometry.Point([lon, lat]).buffer(GAUSSIAN_RADIUS_KM * 1000),
        scale=7000, maxPixels=1e7).get(BAND).getInfo()
    has_data = bool(at_point and at_point > 0)

    # Диагностика пропуска: числа валидных пикселей в диске на исходном
    # разрешении и разброса в фоновом кольце достаточно, чтобы отличить
    # «сигнал слишком слаб» от «данных под инъекцией почти нет»
    disk = ee.Geometry.Point([lon, lat]).buffer(GAUSSIAN_RADIUS_KM * 1000)
    n_valid_disk = mosaic.reduceRegion(
        reducer=ee.Reducer.count(), geometry=disk, scale=1113,
        maxPixels=1e8).get(BAND).getInfo()

    control, z_control = detect(mosaic, aoi, kernels, industrial_mask)
    treated, _ = detect(inject(mosaic, lon, lat, amplitude), aoi, kernels, industrial_mask)

    mad = z_control.select(f"{BAND}_mad_local").reduceRegion(
        reducer=ee.Reducer.median(), geometry=disk, scale=1113,
        maxPixels=1e8).get(f"{BAND}_mad_local").getInfo()
    expected_z = (amplitude / (1.4826 * mad)) if mad else None

    near = [c for c in treated
            if c["lon"] is not None and km(lon, lat, c["lon"], c["lat"]) <= RECOVERY_RADIUS_KM]
    new = [c for c in near
           if all(km(c["lon"], c["lat"], d["lon"], d["lat"]) > CONTROL_MATCH_KM
                  for d in control if d["lon"] is not None)]
    ctrl_near = [c for c in control
                 if c["lon"] is not None and km(lon, lat, c["lon"], c["lat"]) <= RECOVERY_RADIUS_KM]

    return {**base,
            "valid_retrieval_at_point": has_data,
            "n_valid_px_disk": n_valid_disk,
            "annulus_mad_ppb": round(mad, 2) if mad else None,
            "expected_z": round(expected_z, 2) if expected_z else None,
            "n_clusters_control": len(control),
            "n_clusters_treated": len(treated),
            "n_near_control": len(ctrl_near),
            "n_near_treated": len(near),
            "n_new_near": len(new),
            "max_z_new": max((c["max_z"] for c in new if c["max_z"] is not None),
                             default=None),
            "recovered": len(new) >= 1,
            "elapsed_s": round(time.time() - t0, 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--resume", action="store_true",
                    help="продолжить с точки, на которой прогон прервался")
    ap.add_argument("--out", default=str(_REPO_ROOT / "docs" / "p_02_0e_synthetic_pod.json"))
    args = ap.parse_args()

    industrial_mask = ee.Image(INDUSTRIAL_MASK_ASSET)
    source_points = prepare_source_points_categories(
        ee.FeatureCollection(SOURCE_POINTS_ASSET))
    kernels = (detection_ch4.build_annulus_kernel(),
               detection_ch4.build_annulus_count_kernel())

    sites = sample_sites(args.n, source_points)
    rand = random.Random(RANDOM_SEED)
    fluxes = [rand.uniform(FLUX_MIN_T_H, FLUX_MAX_T_H) for _ in sites]

    # Точки и потоки детерминированы зерном, поэтому i-я запись всегда
    # соответствует i-й точке: продолжение сводится к пропуску готовых
    results: list = []
    if args.resume and Path(args.out).exists():
        results = json.loads(Path(args.out).read_text(encoding="utf-8"))["results"]
        logger.info("продолжаю: готово %d из %d", len(results), len(sites))
    for i, ((lon, lat), flux) in enumerate(zip(sites, fluxes), 1):
        if i <= len(results):
            continue
        r = run_site(lon, lat, flux, kernels, industrial_mask)
        results.append(r)
        logger.info("%2d/%d  %.2f т/ч  %s  (контроль %d, с инъекцией %d, новых %d, %.0f с)",
                    i, len(sites), flux,
                    "ОБНАРУЖЕН" if r.get("recovered") else "пропуск",
                    r.get("n_near_control", 0), r.get("n_near_treated", 0),
                    r.get("n_new_near", 0), r.get("elapsed_s", 0))
        # Промежуточная запись: прогон длится десятки минут, обрыв не должен
        # стоить всех посчитанных точек
        save(args, results, partial=True)

    save(args, results, partial=False)
    return 0


def save(args, results: list, partial: bool) -> dict:
    """Собрать сводку и записать файл. Вызывается и по ходу прогона."""
    usable = [r for r in results if r.get("valid_retrieval_at_point")]
    k, n = sum(1 for r in usable if r["recovered"]), len(usable)
    p, lo, hi = wilson(k, n)
    ka, na = sum(1 for r in results if r.get("recovered")), len(results)
    pa, loa, hia = wilson(ka, na)

    summary = {
        "n_injections": na,
        "n_with_valid_retrieval": n,
        "pod_conditional": {"k": k, "n": n, "p": round(p, 3),
                            "ci95": [round(lo, 3), round(hi, 3)]},
        "pod_unconditional": {"k": ka, "n": na, "p": round(pa, 3),
                              "ci95": [round(loa, 3), round(hia, 3)]},
        "miss_rate_conditional": round(1 - p, 3),
        "min_recovered_flux_t_h": round(
            min((r["flux_t_h"] for r in results if r.get("recovered")), default=float("nan")), 2),
    }
    payload = {
        "test": "парный синтетический тест: вероятность обнаружения",
        "configuration": {
            "n": args.n, "flux_range_t_h": [FLUX_MIN_T_H, FLUX_MAX_T_H],
            "ppb_per_t_h_test_scale": PPB_PER_T_PER_H_TEST_SCALE,
            "gaussian_radius_km": GAUSSIAN_RADIUS_KM,
            "recovery_radius_km": RECOVERY_RADIUS_KM,
            "control_match_km": CONTROL_MATCH_KM,
            "z_threshold": Z_MIN, "min_cluster_px": MIN_CLUSTER_PX,
            "window": [DATE_START, DATE_END], "random_seed": RANDOM_SEED,
        },
        "summary": summary,
        "results": results,
    }
    payload["partial"] = partial
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    if not partial:
        print("")
        print(f"обнаружено {k} из {n} (с валидными данными в точке): "
              f"{p:.2f} [{lo:.2f}; {hi:.2f}]")
        print(f"без учёта доступности данных: {ka} из {na} = {pa:.2f} [{loa:.2f}; {hia:.2f}]")
        print(f"записано -> {args.out}")
    return payload


if __name__ == "__main__":
    sys.exit(main())
