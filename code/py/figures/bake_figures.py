"""Bake paper figures — P-02.0d v3 (финальный заход, русскоязычный журнал).

v3 (2026-07-06):
  - F5: аннотация укорочена (подпись вплотную, белая подложка), русская легенда
    на рисунке, заголовков на растрах нет (подрисуночные подписи в статье).
  - Русификация текста на всех фигурах (z остаётся латиницей).
  - Р1 (НОВАЯ): карта района — рельеф MERIT + контур zapsib + сетка + масштабная
    линейка + врезка-локатор (север Евразии).
  - Р2 (НОВАЯ): блок-схема конвейера (matplotlib, вертикальный поток, ч/б).
  - Р3 (НОВАЯ): кривые доли совпадений vs радиус (25–300 км) Tier 1 / Tier 2 +
    ПЕРЕСЧЁТ медианного NN-расстояния совпавших пар при 150 км (замена
    bbox-эпохи «138 км»). JSON -> docs/p_02_0d_match_curves.json.

Запуск: python src/py/figures/bake_figures.py [--only F6|R3]
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
import urllib.request
from pathlib import Path

import ee

ee.Initialize(project="nodal-thunder-481307-u1")

PID = "nodal-thunder-481307-u1"
ROOT = f"projects/{PID}/assets/RuPlumeScan"
CAT = f"{ROOT}/catalog/CH4"
REFS = f"{ROOT}/refs"
YEARS = ["2019", "2020", "2021", "2022", "2023", "2024", "2025"]

import pathlib
def _layout() -> tuple:
    """Каталоги вывода и данных для двух раскладок репозитория.

    Рабочий репозиторий: docs/figures, supplement/data, docs.
    Опубликованный supplement: figures, data, data.
    """
    root = pathlib.Path(__file__).resolve().parents[3]
    if (root / "supplement").is_dir():
        return root / "docs" / "figures", root / "supplement" / "data", root / "docs"
    return root / "figures", root / "data", root / "data"


OUT_DIR, DATA_DIR, AUX_DIR = _layout()
OUT_DIR.mkdir(parents=True, exist_ok=True)

ZAPSIB_FC = ee.FeatureCollection(f"projects/{PID}/assets/zapsib")
ZGEOM = ZAPSIB_FC.geometry()

# Палитра каталога (факелы едины #f57c00; контур маркеров чёрный)


MATCH_KM = 150.0


def _mpl():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


# ─── F6 (matplotlib, русский) ──────────────────────────────────────────────

def bake_f6() -> None:
    print("[F6] годовые счётчики v3 (русские подписи)")
    plt = _mpl()

    per_year = {}
    for y in YEARS:
        fc = ee.FeatureCollection(f"{CAT}/events_{y}")
        total = fc.size()
        artifact = fc.filter(ee.Filter.eq("artifact_likely", 1)).size()
        z5 = fc.filter(ee.Filter.gt("max_z", 5)).size()
        d = ee.Dictionary({"t": total, "a": artifact, "z": z5}).getInfo()
        per_year[y] = {"total": d["t"], "artifact": d["a"],
                       "valid": d["t"] - d["a"], "z5": d["z"]}
        print(f"  {y}: total={d['t']} valid={d['t']-d['a']} artifact={d['a']} z>5={d['z']}")

    tot_v = sum(v["valid"] for v in per_year.values())
    tot_a = sum(v["artifact"] for v in per_year.values())
    print(f"  totals: valid={tot_v} artifact={tot_a} sum={tot_v+tot_a} (expect 88/34/122)")

    valid = [per_year[y]["valid"] for y in YEARS]
    artifact = [per_year[y]["artifact"] for y in YEARS]
    z5 = [per_year[y]["z5"] for y in YEARS]

    # Одна панель: сопоставление с ранней версией конвейера убрано —
    # в тексте статьи оно не обсуждается (решение автора 2026-08-28)
    fig, ax1 = plt.subplots(figsize=(7.0, 4.2), dpi=300)

    x = range(len(YEARS))
    ax1.bar(x, valid, color="#2E7D32", label="Достоверные",
            edgecolor="white", linewidth=0.5)
    ax1.bar(x, artifact, bottom=valid, color="#B45309",
            label="Вероятные артефакты", hatch="//", edgecolor="white",
            linewidth=0.5)
    for i, y in enumerate(YEARS):
        top = valid[i] + artifact[i]
        ax1.annotate(f"z>5: {z5[i]}", (i, top + 0.6), ha="center", fontsize=7.5)
    ax1.set_xticks(list(x))
    ax1.set_xticklabels(YEARS)
    ax1.set_xlabel("Год", fontsize=9)
    ax1.set_ylabel("Число событий", fontsize=9)
    ax1.legend(loc="upper left", fontsize=8, frameon=False)
    ax1.spines[["top", "right"]].set_visible(False)


    for ext in ("svg", "png"):
        out = OUT_DIR / f"fig3_per_year_counts_300dpi.{ext}"
        fig.savefig(out, bbox_inches="tight", dpi=300)
        print(f"  {out.name}: {out.stat().st_size//1024} KB")
    plt.close(fig)


# ─── Р3: кривые совпадений + медианные NN ──────────────────────────────────

def _hav(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _load_events():
    """Каталог (year из int-поля) + референсы (year из date_utc), в границах."""
    ours = []
    for y in YEARS:
        fc = ee.FeatureCollection(f"{CAT}/events_{y}")
        for f in fc.toList(99).getInfo():
            p = f["properties"]
            ours.append((y, p["centroid_lat"], p["centroid_lon"]))

    def refs(asset):
        out = []
        fc = ee.FeatureCollection(asset).filterBounds(ZGEOM)
        for f in fc.toList(500).getInfo():
            p = f["properties"]
            lon, lat = p.get("centroid_lon"), p.get("centroid_lat")
            if lon is None or lat is None:
                g = f.get("geometry", {})
                if g.get("type") == "Point":
                    lon, lat = g["coordinates"]
            d = p.get("date_utc", "") or ""
            out.append((d[:4], lat, lon))
        return out

    return ours, refs(f"{REFS}/schuit2023_v1"), refs(f"{REFS}/imeo_mars_v1")


def bake_r3() -> None:
    print("[Р3] кривые совпадений (25–300 км) + медианные NN при 150 км")
    plt = _mpl()
    import statistics

    ours, schuit, mars = _load_events()
    t1_events = [e for e in ours if e[0] == "2021"]              # 16
    t2_events = [e for e in ours if e[0] in ("2023", "2024", "2025")]  # 74; 2022 исключён из знаменателя (0 MARS в границах равнины) — исправление 2026-08-27, было 81
    print(f"  наши: Tier1 n={len(t1_events)}, Tier2 n={len(t2_events)}; "
          f"Schuit={len(schuit)}, MARS={len(mars)}")

    def nn_dist(ev, refs):
        """Ближайший same-year референс, км (None если нет)."""
        ds = [_hav(ev[1], ev[2], r[1], r[2]) for r in refs if r[0] == ev[0]]
        return min(ds) if ds else None

    t1_nn = [nn_dist(e, schuit) for e in t1_events]
    t2_nn = [nn_dist(e, mars) for e in t2_events]

    radii = list(range(25, 301, 25))
    t1_curve = [100 * sum(1 for d in t1_nn if d is not None and d <= r) / len(t1_nn)
                for r in radii]
    t2_curve = [100 * sum(1 for d in t2_nn if d is not None and d <= r) / len(t2_nn)
                for r in radii]

    # Sanity-якоря при 150 км (ожидаем 7/16 и 53/74; было 53/81 до исправления знаменателя Tier 2)
    n1_150 = sum(1 for d in t1_nn if d is not None and d <= MATCH_KM)
    n2_150 = sum(1 for d in t2_nn if d is not None and d <= MATCH_KM)
    print(f"  якорь 150 км: Tier1 {n1_150}/16 (ожид. 7), Tier2 {n2_150}/{len(t2_nn)} (ожид. 53/74)")
    assert n1_150 == 7 and n2_150 == 53, "anchor mismatch vs phase1!"

    # Медианные NN-расстояния совпавших пар при 150 км
    m1 = [d for d in t1_nn if d is not None and d <= MATCH_KM]
    m2 = [d for d in t2_nn if d is not None and d <= MATCH_KM]
    med1 = statistics.median(m1)
    med2 = statistics.median(m2)
    med_all = statistics.median(m1 + m2)
    print(f"  медианное NN (совпавшие, ≤150 км): Tier1={med1:.1f} км (n=7), "
          f"Tier2={med2:.1f} км (n=53), общее={med_all:.1f} км (n=60)")

    out_json = {
        "radius_km": radii,
        "tier1_matched_pct": [round(v, 1) for v in t1_curve],
        "tier2_matched_pct": [round(v, 1) for v in t2_curve],
        "tier1_n": len(t1_events), "tier2_n": len(t2_events),
        "anchor_150km": {"tier1": f"{n1_150}/16", "tier2": f"{n2_150}/{len(t2_nn)}"},
        "median_nn_matched_150km": {
            "tier1_km": round(med1, 1), "tier1_pairs": len(m1),
            "tier2_km": round(med2, 1), "tier2_pairs": len(m2),
            "overall_km": round(med_all, 1), "overall_pairs": len(m1) + len(m2),
        },
        "note": "zapsib-clipped data (122 catalog / 32 Schuit / 163 MARS); "
                "replaces bbox-era 138 km",
    }
    jpath = AUX_DIR / "p_02_0d_match_curves.json"
    with open(jpath, "w", encoding="utf-8") as fh:
        json.dump(out_json, fh, indent=2, ensure_ascii=False)
    print(f"  JSON -> {jpath.name}")

    # Нулевая модель случайных совпадений (доля площади равнины в пределах R
    # от референсов того же года) — считается p_02_0d_null_model.py
    null_path = AUX_DIR / "p_02_0d_null_model.json"
    null = None
    if null_path.exists():
        with open(null_path, encoding="utf-8") as fh:
            null = json.load(fh)
        assert null["radius_km"] == radii, "сетка радиусов нулевой модели не совпадает"
        i150 = radii.index(MATCH_KM)
        print(f"  нулевая модель при 150 км: Tier1 {null['tier1_null_pct'][i150]}%, "
              f"Tier2 {null['tier2_null_pct'][i150]}% "
              f"(наблюдаемые {t1_curve[i150]:.1f}% и {t2_curve[i150]:.1f}%)")
    else:
        print("  ! нулевая модель не найдена — рисунок без неё")

    # Фигура: наблюдаемые кривые + случайное ожидание, вертикаль на 150 км,
    # ч/б-различимо (разные маркеры и типы линий)
    fig, ax = plt.subplots(figsize=(6.4, 4.4), dpi=300)
    ax.plot(radii, t1_curve, "-o", color="#1a1a1a", ms=4, lw=1.4,
            label=f"Schuit (2021 г.), n = {len(t1_events)}")
    ax.plot(radii, t2_curve, "--s", color="#B45309", ms=4, lw=1.4,
            label=f"MARS (2023–2025 гг.), n = {len(t2_events)}")
    if null:
        ax.plot(radii, null["tier1_null_pct"], "-", color="#9a9a9a", lw=1.0,
                label="случайное ожидание, Schuit")
        ax.plot(radii, null["tier2_null_pct"], "--", color="#9a9a9a", lw=1.0,
                label="случайное ожидание, MARS")
    ax.axvline(MATCH_KM, color="#666666", ls=":", lw=1.2)
    ax.text(MATCH_KM + 4, 4, "150 км", fontsize=8, color="#444444")
    ax.set_xlabel("Радиус сопоставления, км", fontsize=9)
    ax.set_ylabel("Доля совпавших событий, %", fontsize=9)
    ax.set_xlim(0, 310)
    ax.set_ylim(0, 100)
    ax.legend(fontsize=7.5, loc="upper left", frameon=False)
    ax.grid(alpha=0.25, lw=0.4)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(labelsize=8)

    for ext in ("svg", "png"):
        out = OUT_DIR / f"fig4_match_curves_300dpi.{ext}"
        fig.savefig(out, dpi=300, bbox_inches="tight")
        print(f"  {out.name}: {out.stat().st_size//1024} KB")
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["F6", "R3"])
    a = ap.parse_args()
    jobs = {"F6": bake_f6, "R3": bake_r3}   # рисунки 3 и 4 статьи
    todo = [a.only] if a.only else ["F6", "R3"]
    for j in todo:
        jobs[j]()
    print(f"\nDone -> {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
