"""Нулевая модель случайных совпадений для кривых сопоставления (рис. Р3).

Отвечает на замечание внешнего рецензента: доля совпадений при радиусе R
сама по себе не доказывает содержательность сопоставления, поскольку часть
совпадений возникла бы и при случайном размещении событий. Нулевая модель —
доля площади равнины, лежащая в пределах R хотя бы от одной референсной
детекции соответствующего года: именно такую долю совпадений дало бы
равномерное случайное размещение событий.

Для уровня 2 (MARS) доля вычисляется отдельно по годам и взвешивается числом
событий каталога соответствующего года, поскольку сопоставление год-к-году.

Выход: docs/p_02_0d_null_model.json — используется bake_figures.py (Р3).

Оговорка, обязательная при интерпретации: события каталога тяготеют к
промышленным районам, где сосредоточены и референсные детекции, поэтому
площадная модель занижает случайное ожидание. Она исключает грубую
случайность, но не заменяет событийного сопоставления.
"""

from __future__ import annotations

import json
from pathlib import Path

import ee

PID = "nodal-thunder-481307-u1"
ROOT = f"projects/{PID}/assets/RuPlumeScan"
REPO = Path(__file__).resolve().parents[3]

RADII_KM = list(range(25, 301, 25))

# Число событий каталога по годам в границах равнины (замороженный каталог)
TIER2_EVENTS_PER_YEAR = {"2023": 21, "2024": 39, "2025": 14}
TIER1_YEAR = "2021"


def area_fraction_curve(points: ee.FeatureCollection, aoi: ee.Geometry,
                        aoi_area: ee.Number) -> list[float]:
    """Доля площади aoi в пределах R км от точек — для каждого R из RADII_KM.

    Считается одним запросом: серверный map по списку радиусов.
    """
    geom = points.geometry()

    def one(r_km):
        r = ee.Number(r_km).multiply(1000)
        buf = geom.buffer(r, 1000).intersection(aoi, 1000)
        return buf.area(1000).divide(aoi_area)

    return ee.List(RADII_KM).map(one).getInfo()


def main() -> None:
    ee.Initialize(project=PID)

    aoi = ee.FeatureCollection(f"{ROOT}/zapsib_boundary").geometry()
    aoi_area = aoi.area(1000)

    schuit = ee.FeatureCollection(f"{ROOT}/refs/schuit2023_v1").filterBounds(aoi)
    mars = ee.FeatureCollection(f"{ROOT}/refs/imeo_mars_v1").filterBounds(aoi)

    print("Нулевая модель: доля площади равнины в пределах R от референсов")

    print(f"  уровень 1 — Schuit {TIER1_YEAR} (n={schuit.size().getInfo()})")
    tier1 = area_fraction_curve(schuit, aoi, aoi_area)

    tier2_by_year: dict[str, list[float]] = {}
    for year in TIER2_EVENTS_PER_YEAR:
        refs = mars.filter(ee.Filter.stringStartsWith("date_utc", year))
        n = refs.size().getInfo()
        print(f"  уровень 2 — MARS {year} (n={n})")
        tier2_by_year[year] = area_fraction_curve(refs, aoi, aoi_area)

    # Взвешивание по числу событий каталога соответствующего года
    total = sum(TIER2_EVENTS_PER_YEAR.values())
    tier2 = [
        sum(TIER2_EVENTS_PER_YEAR[y] * tier2_by_year[y][i] for y in TIER2_EVENTS_PER_YEAR) / total
        for i in range(len(RADII_KM))
    ]

    out = {
        "radius_km": RADII_KM,
        "tier1_null_pct": [round(100 * v, 1) for v in tier1],
        "tier2_null_pct": [round(100 * v, 1) for v in tier2],
        "tier2_null_pct_by_year": {
            y: [round(100 * v, 1) for v in c] for y, c in tier2_by_year.items()
        },
        "tier2_weights_events_per_year": TIER2_EVENTS_PER_YEAR,
        "method": (
            "Доля площади равнины в пределах R км хотя бы от одной референсной "
            "детекции того же года — ожидаемая доля совпадений при равномерном "
            "случайном размещении событий. Уровень 2 взвешен числом событий "
            "каталога по годам (21/39/14)."
        ),
        "caveat": (
            "Занижает случайное ожидание: события каталога и референсные детекции "
            "совместно тяготеют к промышленным районам. Исключает грубую "
            "случайность, не заменяет событийного сопоставления."
        ),
    }

    path = REPO / "docs" / "p_02_0d_null_model.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)
    print(f"\nWROTE {path}")
    for i, r in enumerate(RADII_KM):
        if r in (50, 150, 300):
            print(f"  R={r:3d} км: уровень 1 {out['tier1_null_pct'][i]:4.1f}%, "
                  f"уровень 2 {out['tier2_null_pct'][i]:4.1f}%")


if __name__ == "__main__":
    main()
