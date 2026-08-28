"""Подготовка контекстных слоёв для обзорной карты (рис. 2).

Строит три из четырёх слоёв, которые читает bake_map_satellite.py:

    admin1.geojson  границы субъектов РФ и областей Казахстана (FAO GAUL level1)
    rivers.geojson  крупные реки со средним расходом > 250 м³/с (HydroSHEDS)
    schuit.geojson  детекции Schuit et al. (2023) в границах равнины

Четвёртый слой, mars.geojson, готовится пользователем из выгрузки UNEP IMEO
MARS: эти данные распространяются под CC BY-NC-SA 4.0 и в репозиторий не
включены. Формат — точечный GeoJSON в EPSG:4326.

Первые два слоя запрашиваются у Earth Engine и требуют учётной записи;
третий строится из таблицы, приложенной к публикации Schuit et al. (2023).

Состав слоёв зависит от версии наборов данных в каталоге Earth Engine, поэтому
повторный запуск может дать не побитово тот же файл, что использован при
построении опубликованного рисунка.

Использование:
    python src/py/figures/prep_map_layers.py [--out DIR]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import ee
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parents[3]
MAP_DIR = ROOT / "data" / "map_layers"
BOUNDARY = ROOT / "supplement" / "data" / "zapsib_boundary.geojson"
SCHUIT_CSV = (ROOT / "data" / "refs" / "schuit2023" /
              "Schuit_etal2023_TROPOMI_all_plume_detections_2021.csv")

PROJECT = "nodal-thunder-481307-u1"
MIN_DISCHARGE_CMS = 250.0     # порог отбора рек, м³/с


def frame() -> tuple[float, float, float, float]:
    """Рамка запроса — габариты границы равнины с полем 1.5°."""
    b = gpd.read_file(BOUNDARY).to_crs("EPSG:4326").total_bounds
    return b[0] - 1.5, b[1] - 1.5, b[2] + 1.5, b[3] + 1.5


def fetch(fc: ee.FeatureCollection, box: tuple, bands: int = 6) -> list:
    """Выгрузка коллекции по широтным полосам.

    getInfo прерывается на 5000 элементах, а крупных водотоков в рамке больше,
    поэтому запрос дробится по широте и результаты объединяются по id объекта.
    """
    lo0, la0, lo1, la1 = box
    step = (la1 - la0) / bands
    seen, feats = set(), []
    for i in range(bands):
        strip = ee.Geometry.Rectangle(
            [lo0, la0 + i * step, lo1, la0 + (i + 1) * step], None, False)
        for f in fc.filterBounds(strip).getInfo()["features"]:
            if f["id"] not in seen:
                seen.add(f["id"])
                feats.append(f)
    return feats


def dump(feats: list, path: Path) -> None:
    """Запись после полной выгрузки, чтобы отказ GEE не оставлял пустой файл."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": feats}, fh,
                  ensure_ascii=False)
    print(f"  {path.name}: {len(feats)} объектов, {path.stat().st_size // 1024} KB")


def bake_admin(box: tuple, out: Path) -> None:
    fc = (ee.FeatureCollection("FAO/GAUL/2015/level1")
          .filter(ee.Filter.inList("ADM0_NAME", ["Russian Federation", "Kazakhstan"]))
          .select(["ADM1_NAME"]))
    dump(fetch(fc, box, bands=2), out / "admin1.geojson")


def bake_rivers(box: tuple, out: Path) -> None:
    fc = (ee.FeatureCollection("WWF/HydroSHEDS/v1/FreeFlowingRivers")
          .filter(ee.Filter.gt("DIS_AV_CMS", MIN_DISCHARGE_CMS))
          .select(["DIS_AV_CMS"]))
    dump(fetch(fc, box), out / "rivers.geojson")


def bake_schuit(out: Path) -> None:
    """Детекции Schuit et al. (2023), обрезанные границей равнины."""
    if not SCHUIT_CSV.exists():
        raise FileNotFoundError(
            f"нет таблицы {SCHUIT_CSV} — приложение к Schuit et al. (2023), "
            "doi:10.5194/acp-23-9071-2023")
    df = pd.read_csv(SCHUIT_CSV)
    g = gpd.GeoDataFrame(df, crs="EPSG:4326",
                         geometry=[Point(xy) for xy in zip(df.lon, df.lat)])
    plain = gpd.read_file(BOUNDARY).to_crs("EPSG:4326").union_all()
    inside = g[g.within(plain)]
    path = out / "schuit.geojson"
    inside.to_file(path, driver="GeoJSON")
    print(f"  {path.name}: {len(inside)} детекций, {path.stat().st_size // 1024} KB")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(MAP_DIR))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    ee.Initialize(project=PROJECT)
    box = frame()

    print("границы субъектов и областей…")
    bake_admin(box, out)
    print("реки…")
    bake_rivers(box, out)
    print("детекции Schuit et al. (2023)…")
    bake_schuit(out)
    print(f"\nготово -> {out}")
    print("mars.geojson готовится отдельно: выгрузка UNEP IMEO MARS "
          "(CC BY-NC-SA 4.0, в репозиторий не включена)")


if __name__ == "__main__":
    main()
