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

Запуск: python src/py/figures/bake_figures.py [--only F5|F6|F7|F9|R1|R2|R3]
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
BOUNDARY = ee.FeatureCollection(f"{ROOT}/zapsib_boundary")

# Палитра каталога (факелы едины #f57c00; контур маркеров чёрный)
COLOR = {
    "gas_field": "c62828", "oil_field": "8b4513", "viirs_flare_high": "f57c00",
    "viirs_flare_low": "f57c00", "tpp_gres": "7b1fa2", "tpp_chp": "9c27b0",
    "metallurgy": "37474f", "coal_mine": "212121", "urban": "1976d2",
    "other": "757575", "unknown": "bdbdbd",
}
SHAPE = {
    "gas_field": "circle", "oil_field": "circle",
    "viirs_flare_high": "triangle", "viirs_flare_low": "triangle",
    "tpp_gres": "square", "tpp_chp": "square",
    "metallurgy": "diamond", "coal_mine": "diamond",
    "urban": "cross", "other": "cross", "unknown": "cross",
}

ZMIN, ZMAX = 3.0, 85.47
PMIN, PMAX = 5.0, 32.0
LNMIN, LNMAX = math.log(ZMIN), math.log(ZMAX)

MAXZ_LON, MAXZ_LAT = 75.151, 62.883   # z=85.47
BOV_LON, BOV_LAT = 68.788, 70.451     # gold-standard event
MATCH_KM = 150.0


# ─── Общие хелперы ─────────────────────────────────────────────────────────

def log_size(z: ee.Number) -> ee.Number:
    zc = z.max(ZMIN).min(ZMAX)
    return (zc.log().subtract(LNMIN).divide(LNMAX - LNMIN)
            .multiply(PMAX - PMIN).add(PMIN))


def all_events() -> ee.FeatureCollection:
    return ee.FeatureCollection(
        [ee.FeatureCollection(f"{CAT}/events_{y}") for y in YEARS]).flatten()


def styled_centroids() -> ee.Image:
    color_d = ee.Dictionary(COLOR)
    shape_d = ee.Dictionary(SHAPE)

    def style_f(f):
        g = ee.Geometry.Point([f.get("centroid_lon"), f.get("centroid_lat")])
        raw = f.get("nearest_source_type")
        src = ee.String(ee.Algorithms.If(raw, raw, "unknown"))
        fill = ee.String(color_d.get(src, "bdbdbd"))
        shape = ee.String(shape_d.get(src, "circle"))
        z = ee.Number(ee.Algorithms.If(f.get("max_z"), f.get("max_z"), 0))
        return ee.Feature(g).set("style", {
            "color": "000000", "fillColor": fill.cat("E6"),
            "pointSize": log_size(z), "pointShape": shape, "width": 1,
        })

    return all_events().map(style_f).style(styleProperty="style", neighborhood=48)


def ref_points_gray(split: bool) -> ee.Image:
    sch_col = "4a4a4a" if split else "757575"
    mars_col = "9e9e9e" if split else "757575"
    schuit = (ee.FeatureCollection(f"{REFS}/schuit2023_v1").filterBounds(ZGEOM)
              .style(color=sch_col, fillColor="00000000", pointSize=5,
                     pointShape="diamond", width=1.3))
    mars = (ee.FeatureCollection(f"{REFS}/imeo_mars_v1").filterBounds(ZGEOM)
            .style(color=mars_col, fillColor="00000000", pointSize=5,
                   pointShape="diamond", width=1.3))
    return schuit.blend(mars)


def boundary_img(width: int = 2, palette: str = "404040") -> ee.Image:
    return (ee.Image().byte()
            .paint(featureCollection=BOUNDARY, color=1, width=width)
            .visualize(palette=[palette]))


def bg_img(scale: int, vmax: int) -> ee.Image:
    # MERIT DEM: покрытие до 90°N (SRTM обрезан на 60°N)
    return (ee.Image("MERIT/DEM/v1_0_3")
            .reproject(crs="EPSG:4326", scale=scale)
            .unmask(0)
            .visualize(min=0, max=vmax, palette=["eeeeee", "a8a8a8"]))


def fetch_png(image: ee.Image, region: ee.Geometry, dims: str, out_name: str) -> Path:
    url = image.getThumbURL({"region": region, "dimensions": dims, "format": "png"})
    out = OUT_DIR / out_name
    urllib.request.urlretrieve(url, out)
    w, h = png_dims(out)
    print(f"  {out_name}: {out.stat().st_size//1024} KB, {w}x{h}px")
    return out


def png_dims(path: Path) -> tuple[int, int]:
    with open(path, "rb") as fh:
        head = fh.read(24)
    w, h = struct.unpack(">II", head[16:24])
    return w, h


def region_lonlat(region: ee.Geometry) -> tuple[float, float, float, float]:
    coords = region.bounds(maxError=1).getInfo()["coordinates"][0]
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return min(lons), max(lons), min(lats), max(lats)


def _mpl():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


WHITE_BOX = {"boxstyle": "round,pad=0.25", "fc": "white", "alpha": 0.8, "ec": "none"}


def post_process(path: Path, bounds: tuple[float, float, float, float] | None,
                 marks: list | None = None, texts: list | None = None,
                 legend: list | None = None, legend_ncol: int = 2) -> None:
    """Пост-обработка PNG: аннотации (короткая стрелка + белая подложка),
    статичные подписи; легенда — ПОД картой (отдельная полоса, ноль перекрытий).

    marks: (lon, lat, text, dx_px, dy_px) — geo-привязка, offset в px кадра 1015w.
    texts: (x_frac, y_frac, text, fontsize_1015) — доли кадра.
    legend: matplotlib handles; legend_ncol — колонок в полосе под картой.
    """
    plt = _mpl()

    img = plt.imread(path)
    h, w = img.shape[0], img.shape[1]
    k = w / 1015.0  # масштаб от базового 1015w

    # Полоса легенды под картой
    n_rows = 0
    if legend:
        n_rows = math.ceil(len(legend) / legend_ncol)
    strip = int((14 + 26 * n_rows) * k) if legend else 0
    total_h = h + strip

    fig = plt.figure(figsize=(w / 300, total_h / 300), dpi=300,
                     facecolor="white")
    ax = fig.add_axes([0, strip / total_h, 1, h / total_h])
    ax.imshow(img)
    ax.set_xlim(0, w)
    ax.set_ylim(h, 0)
    ax.axis("off")

    if marks and bounds:
        lon0, lon1, lat0, lat1 = bounds
        for lon, lat, text, dx, dy in marks:
            x = (lon - lon0) / (lon1 - lon0) * w
            y = (lat1 - lat) / (lat1 - lat0) * h
            ax.annotate(text, xy=(x, y), xytext=(x + dx * k, y + dy * k),
                        fontsize=8.5 * k, color="black", fontweight="bold",
                        bbox=WHITE_BOX,
                        arrowprops={"arrowstyle": "->", "lw": 1.0 * k,
                                    "color": "black",
                                    "shrinkA": 2, "shrinkB": 3})
    if texts:
        for xf, yf, text, fs in texts:
            ax.text(xf * w, yf * h, text, fontsize=fs * k, fontweight="bold",
                    color="black", bbox=WHITE_BOX, va="top")
    if legend:
        fig.legend(handles=legend, loc="lower center", ncol=legend_ncol,
                   fontsize=5.4 * k, frameon=False, handletextpad=0.4,
                   columnspacing=1.0, borderaxespad=0.15)

    fig.savefig(path, dpi=300, facecolor="white")
    plt.close(fig)
    print(f"  post-processed: {path.name}")


def legend_catalog():
    """Русская легенда F5 (4 класса каталога + референсы)."""
    from matplotlib.lines import Line2D
    return [
        Line2D([], [], marker="o", ls="none", mfc="#c62828", mec="black",
               ms=5.5, label="Газовое месторождение"),
        Line2D([], [], marker="^", ls="none", mfc="#f57c00", mec="black",
               ms=6, label="Факельная установка"),
        Line2D([], [], marker="s", ls="none", mfc="#7b1fa2", mec="black",
               ms=5.5, label="ТЭС"),
        Line2D([], [], marker="D", ls="none", mfc="none", mec="#757575",
               ms=5, label="Референсные детекции (Schuit/MARS)"),
    ]


def legend_f9():
    from matplotlib.lines import Line2D
    return [
        Line2D([], [], marker="^", ls="none", mfc="#f57c00", mec="black",
               ms=6, label="Несовпавшие факельные детекции (настоящая работа)"),
        Line2D([], [], marker="D", ls="none", mfc="none", mec="#757575",
               ms=5, label="Референсные детекции газового класса"),
    ]


# ─── F5 ────────────────────────────────────────────────────────────────────

def bake_f5() -> None:
    print("[F5] карта каталога v3 (короткая аннотация + русская легенда)")
    comp = (bg_img(5000, 3000).blend(boundary_img())
            .blend(ref_points_gray(split=True))
            .blend(styled_centroids()))
    region = ZGEOM.bounds()
    bounds = region_lonlat(region)
    for dims, name in [("1015x760", "F5_spatial_map_300dpi_1015w.png"),
                       ("2100x1570", "F5_spatial_map_300dpi_2100w.png")]:
        p = fetch_png(comp, region, dims, name)
        # Аннотация max_z убрана (v3.1) — лог-размер сам выделяет максимум;
        # значение z = 85,5 указывается в подрисуночной подписи статьи.
        post_process(p, bounds, legend=legend_catalog())


# ─── F7 ────────────────────────────────────────────────────────────────────

def bake_f7() -> None:
    print("[F7] зумы кластеров v3 (русские подписи панелей)")
    color_d = ee.Dictionary(COLOR)

    def style_fp(f):
        raw = f.get("nearest_source_type")
        src = ee.String(ee.Algorithms.If(raw, raw, "unknown"))
        fill = ee.String(color_d.get(src, "bdbdbd"))
        return f.set("style", {"color": "000000", "fillColor": fill.cat("99"),
                               "width": 1.2})

    footprints = all_events().map(style_fp).style(styleProperty="style",
                                                  neighborhood=16)
    comp = bg_img(1000, 1500).blend(ref_points_gray(split=True)).blend(footprints)

    khmao = ee.Geometry.Rectangle([70.5, 59.5, 76.0, 63.0], None, False)
    bovan = ee.Geometry.Rectangle([66.5, 69.0, 75.5, 72.0], None, False)
    combined = ee.Geometry.Rectangle([66.0, 58.0, 77.0, 72.0], None, False)

    p_a = fetch_png(comp, khmao, "1015x645", "F7A_KhMAO_zoom_300dpi_1015w.png")
    post_process(p_a, None, texts=[(0.015, 0.03, "а) ХМАО", 11)])

    p_b = fetch_png(comp, bovan, "1015x340", "F7B_Bovanenkovo_zoom_300dpi_1015w.png")
    near = (ee.FeatureCollection(f"{REFS}/schuit2023_v1")
            .filterBounds(ee.Geometry.Point([BOV_LON, BOV_LAT]).buffer(30000)))
    feats = near.toList(5).getInfo() if near.size().getInfo() else []
    marks = []
    if feats:
        g = feats[0]["geometry"]["coordinates"]
        marks = [(g[0], g[1], "Детекция Schuit, 15 км", 45, 55)]
    post_process(p_b, (66.5, 75.5, 69.0, 72.0), marks=marks,
                 texts=[(0.015, 0.06, "б) Бованенково", 11)])

    fetch_png(comp, combined, "2100x1340", "F7_combined_zoom_300dpi_2100w.png")


# ─── F9 ────────────────────────────────────────────────────────────────────

def bake_f9() -> None:
    print("[F9] flare-complement v3 (русская легенда)")
    unmatched = all_events().filter(ee.Filter.And(
        ee.Filter.stringStartsWith("nearest_source_type", "viirs_flare"),
        ee.Filter.eq("matched_schuit_150km", 0),
        ee.Filter.eq("matched_mars_150km", 0)))
    n = unmatched.size().getInfo()
    print(f"  несовпавших факелов (ожидается 44): {n}")
    if n != 44:
        print("  ABORT — count mismatch")
        return

    def style_flare(f):
        g = ee.Geometry.Point([f.get("centroid_lon"), f.get("centroid_lat")])
        z = ee.Number(ee.Algorithms.If(f.get("max_z"), f.get("max_z"), 0))
        return ee.Feature(g).set("style", {
            "color": "000000", "fillColor": "f57c00E6",
            "pointSize": log_size(z), "pointShape": "triangle", "width": 1})

    flares = unmatched.map(style_flare).style(styleProperty="style",
                                              neighborhood=48)
    comp = (bg_img(5000, 3000).blend(boundary_img())
            .blend(ref_points_gray(split=False)).blend(flares))
    region = ZGEOM.bounds()
    for dims, name in [("1015x760", "F9_flare_complement_300dpi_1015w.png"),
                       ("2100x1570", "F9_flare_complement_300dpi_2100w.png")]:
        p = fetch_png(comp, region, dims, name)
        post_process(p, None, legend=legend_f9())


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


# ─── Р1: карта района исследования ─────────────────────────────────────────

def bake_r1() -> None:
    print("[Р1] карта района исследования (рельеф + контур + сетка + врезка)")
    plt = _mpl()

    # Основная карта: рельеф + жирный контур равнины, регион с полями
    main_region = ee.Geometry.Rectangle([57.0, 47.5, 97.0, 76.0], None, False)
    main = bg_img(5000, 3000).blend(boundary_img(width=4, palette="1a1a1a"))
    p_main = fetch_png(main, main_region, "2100x1500", "_r1_main_tmp.png")

    # Врезка: север Евразии, контур красным
    inset_region = ee.Geometry.Rectangle([15.0, 35.0, 165.0, 80.0], None, False)
    inset = (bg_img(20000, 3000)
             .blend(ee.Image().byte()
                    .paint(featureCollection=BOUNDARY, color=1, width=3)
                    .visualize(palette=["cc0000"])))
    p_inset = fetch_png(inset, inset_region, "700x300", "_r1_inset_tmp.png")

    img = plt.imread(p_main)
    h, w = img.shape[0], img.shape[1]
    lon0, lon1, lat0, lat1 = 57.0, 97.0, 47.5, 76.0

    fig = plt.figure(figsize=(w / 300, h / 300 * 1.06), dpi=300)
    ax = fig.add_axes([0.06, 0.06, 0.92, 0.92])
    ax.imshow(img, extent=[lon0, lon1, lat0, lat1], aspect="auto")

    # Градусная сетка каждые 5°
    for lon in range(60, 96, 5):
        ax.axvline(lon, color="#666666", lw=0.4, ls=":", alpha=0.7)
    for lat in range(50, 76, 5):
        ax.axhline(lat, color="#666666", lw=0.4, ls=":", alpha=0.7)
    ax.set_xticks(list(range(60, 96, 5)))
    ax.set_xticklabels([f"{v}°" for v in range(60, 96, 5)], fontsize=8)
    ax.set_yticks(list(range(50, 76, 5)))
    ax.set_yticklabels([f"{v}°" for v in range(50, 76, 5)], fontsize=8)
    ax.set_xlabel("Долгота, ° в.д.", fontsize=9)
    ax.set_ylabel("Широта, ° с.ш.", fontsize=9)

    # Масштабная линейка 500 км — длина вычислена ПО ШИРОТЕ РАЗМЕЩЕНИЯ (51° с.ш.):
    # на неспроецированной lon/lat-карте линейная линейка валидна только на
    # широте, где она нарисована.
    bar_lat = 51.0
    km_per_deg = 111.32 * math.cos(math.radians(bar_lat))
    bar_deg = 500.0 / km_per_deg
    x0, y0 = 61.5, bar_lat
    ax.plot([x0, x0 + bar_deg], [y0, y0], color="black", lw=2.5)
    ax.plot([x0, x0], [y0 - 0.25, y0 + 0.25], color="black", lw=2.5)
    ax.plot([x0 + bar_deg, x0 + bar_deg], [y0 - 0.25, y0 + 0.25],
            color="black", lw=2.5)
    ax.text(x0 + bar_deg / 2, y0 + 0.55, "500 км (по 51° с. ш.)", ha="center",
            fontsize=8, bbox=WHITE_BOX)

    # Врезка-локатор (верхний правый угол)
    ins_img = plt.imread(p_inset)
    axi = fig.add_axes([0.635, 0.685, 0.335, 0.27])
    axi.imshow(ins_img, extent=[15, 165, 35, 80], aspect="auto")
    axi.set_xticks([])
    axi.set_yticks([])
    for s in axi.spines.values():
        s.set_linewidth(1.2)

    out = OUT_DIR / "R1_study_area_300dpi_2100w.png"
    fig.savefig(out, dpi=300, bbox_inches="tight")
    plt.close(fig)
    p_main.unlink()
    p_inset.unlink()
    print(f"  {out.name}: {out.stat().st_size//1024} KB")


# ─── Р2: блок-схема конвейера ──────────────────────────────────────────────

def bake_r2() -> None:
    print("[Р2] блок-схема конвейера (русский, вертикальный поток)")
    plt = _mpl()

    blocks = [
        "TROPOMI L3 XCH$_4$ (qa ≥ 0,5)",
        "Репроекция EPSG:6931, сетка 5,5 км",
        "Кольцевая z-оценка:\nмедиана/MAD, кольцо 50–150 км",
        "Кластеризация: z ≥ 3,0; ≥ 5 пикселей",
        "Двухусловная маска:\nвалидное восстановление + индустриальная близость",
        "Ветровая валидация:\nERA5 10 м (контроль 850 гПа)",
        "Каскад артефактов:\nснег > 0,5; альбедо ± 0,5 (направленно)",
        "Атрибуция источников\n(VNF-факелы, месторождения, ТЭС)",
        "Каталог: 122 события\n+ флаги совпадений (Schuit, MARS)",
    ]

    fig, ax = plt.subplots(figsize=(4.6, 9.2), dpi=300)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, len(blocks))
    ax.axis("off")

    n = len(blocks)
    for i, text in enumerate(blocks):
        yc = n - i - 0.5
        last = (i == n - 1)
        ax.text(0.5, yc, text, ha="center", va="center", fontsize=8.6,
                fontweight="bold" if last else "normal", wrap=True,
                bbox={"boxstyle": "round,pad=0.45",
                      "fc": "#f5f5f5" if last else "white",
                      "ec": "black", "lw": 1.3 if last else 1.0})
        if not last:
            ax.annotate("", xy=(0.5, yc - 0.78), xytext=(0.5, yc - 0.42),
                        arrowprops={"arrowstyle": "-|>", "color": "black",
                                    "lw": 1.2})

    for ext in ("svg", "png"):
        out = OUT_DIR / f"R2_pipeline_300dpi.{ext}"
        fig.savefig(out, dpi=300, bbox_inches="tight")
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
    ap.add_argument("--only", choices=["F5", "F6", "F7", "F9", "R1", "R2", "R3"])
    a = ap.parse_args()
    jobs = {"F5": bake_f5, "F6": bake_f6, "F7": bake_f7, "F9": bake_f9,
            "R1": bake_r1, "R2": bake_r2, "R3": bake_r3}
    todo = [a.only] if a.only else ["F6", "R3"]   # рисунки 3 и 4 статьи
    for j in todo:
        jobs[j]()
    print(f"\nDone -> {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
