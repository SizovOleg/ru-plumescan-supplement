"""Обзорная карта каталога на спутниковой подложке (рис. 3 статьи).

Три класса точек: события настоящего каталога и детекции двух референсных
каталогов. Подложка — мозаика Esri World Imagery (тайлы), поверх неё границы
субъектов, крупные реки, города и физико-географическая граница равнины.

Отрисовка целиком в matplotlib: полный контроль над легендой, масштабной
линейкой и подписями, чего не даёт серверный рендер Earth Engine.

Контекстные слои читаются из data/map_layers: admin1.geojson, rivers.geojson,
schuit.geojson, mars.geojson. Первые три готовит prep_map_layers.py; выгрузка
MARS не распространяется вместе с репозиторием (CC BY-NC-SA 4.0) и готовится
пользователем самостоятельно. Каталог событий и граница равнины берутся из
данных supplement.

Использование:
    python src/py/figures/bake_map_satellite.py [--zoom 6] [--data DIR] [--out DIR]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import contextily as cx
import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import matplotlib.patheffects as pe

ROOT = Path(__file__).resolve().parents[3]
# Раскладка одинакова в рабочем репозитории и в опубликованном supplement
MAP_DIR = ROOT / "data" / "map_layers"
SUPP = (ROOT / "supplement" / "data") if (ROOT / "supplement").is_dir() else (ROOT / "data")
FIG_DIR = (ROOT / "docs" / "figures") if (ROOT / "supplement").is_dir() else (ROOT / "figures")

# Контекстные слои готовятся отдельно (prep_map_layers.py); MARS не распространяется
LAYER_SOURCES = {
    "admin1.geojson": "FAO/GAUL/2015/level1 — python code/py/figures/prep_map_layers.py",
    "rivers.geojson": "WWF/HydroSHEDS/v1/FreeFlowingRivers — тот же скрипт",
    "schuit.geojson": "Schuit et al. (2023), приложение к статье — тот же скрипт",
    "mars.geojson":   "выгрузка UNEP IMEO MARS; не распространяется (CC BY-NC-SA 4.0)",
}
WEB = "EPSG:3857"

# Цвета подобраны под тёмную спутниковую подложку: различимы и в печати
C_OURS = "#FF2D95"      # события настоящего каталога
C_SCHUIT = "#00E5FF"    # Schuit et al. (2023)
C_MARS = "#FFB300"      # UNEP IMEO MARS
C_BOUND = "#FFFF66"     # граница равнины
C_ADMIN = "#FFFFFF"     # границы субъектов
C_RIVER = "#7EC8E3"     # реки
C_RIVLAB = "#2196F3"    # подписи рек — синим

# Крупные города района исследования (широта, долгота, подпись, сдвиг подписи)
CITIES = [
    (57.15, 65.53, "Тюмень", (4, -8)),
    (61.25, 73.40, "Сургут", (6, 4)),
    (60.94, 76.57, "Нижневартовск", (6, -5)),
    (66.08, 76.68, "Новый Уренгой", (6, 4)),
    (61.00, 69.02, "Ханты-Мансийск", (-69, -4)),
    (66.53, 66.53, "Салехард", (6, 4)),
    (63.20, 75.45, "Ноябрьск", (6, 4)),
    (65.53, 72.52, "Надым", (-31, 3)),
    (58.20, 68.25, "Тобольск", (6, 2)),
    (54.99, 73.37, "Омск", (6, 1)),
    (56.50, 84.95, "Томск", (6, 2)),
    (55.03, 82.93, "Новосибирск", (-52, -10)),
]


def load(path: Path) -> gpd.GeoDataFrame:
    if not path.exists():
        src = LAYER_SOURCES.get(path.name, "")
        raise FileNotFoundError(
            f"нет слоя {path}" + (f" — источник: {src}" if src else ""))
    g = gpd.read_file(path)
    if g.crs is None:
        g = g.set_crs("EPSG:4326")
    return g.to_crs(WEB)


def scalebar(ax, length_km: int = 300) -> None:
    """Масштабная линейка. Длина корректируется по широте центра кадра."""
    import math

    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    lat = math.degrees(2 * math.atan(math.exp((y0 + y1) / 2 / 6378137.0)) - math.pi / 2)
    # в Web Mercator метр растянут в 1/cos(lat) раз
    length_m = length_km * 1000 / math.cos(math.radians(lat))
    x_start = x0 + (x1 - x0) * 0.055
    y_pos = y0 + (y1 - y0) * 0.018
    h = (y1 - y0) * 0.006
    ax.add_patch(plt.Rectangle((x_start, y_pos), length_m, h,
                               facecolor="white", edgecolor="black", lw=0.8, zorder=12))
    ax.add_patch(plt.Rectangle((x_start, y_pos), length_m / 2, h,
                               facecolor="black", edgecolor="black", lw=0.8, zorder=12))
    for frac, lab in ((0, "0"), (0.5, str(length_km // 2)), (1, f"{length_km} км")):
        ax.text(x_start + length_m * frac, y_pos + h * 2.2, lab,
                ha="center", va="bottom", fontsize=7.5, color="white", zorder=12,
                path_effects=[pe.withStroke(linewidth=2.2, foreground="black")])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zoom", type=int, default=6)
    ap.add_argument("--data", default=str(MAP_DIR), help="каталог контекстных слоёв")
    ap.add_argument("--out", default=str(FIG_DIR))
    args = ap.parse_args()
    data = Path(args.data)

    boundary = load(SUPP / "zapsib_boundary.geojson")
    admin = load(data / "admin1.geojson")
    rivers = load(data / "rivers.geojson")
    schuit = load(data / "schuit.geojson")
    mars = load(data / "mars.geojson")

    cat = load(SUPP / "catalog_ch4_west_siberia.geojson")
    cat["geometry"] = cat.geometry.centroid  # события — полигоны кластеров

    # Кадр по границе равнины с небольшим полем
    minx, miny, maxx, maxy = boundary.total_bounds
    padx, pady = (maxx - minx) * 0.03, (maxy - miny) * 0.03
    xlim = (minx - padx, maxx + padx)
    ylim = (miny - pady, maxy + pady)

    fig, ax = plt.subplots(figsize=(8.6, 11.0), dpi=300)
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)

    print("загрузка спутниковой подложки (Esri World Imagery)…")
    cx.add_basemap(ax, source=cx.providers.Esri.WorldImagery,
                   zoom=args.zoom, attribution=False)

    # Контекстные слои
    admin.boundary.plot(ax=ax, color=C_ADMIN, lw=0.6, alpha=0.65, zorder=3)

    rivers.plot(ax=ax, color=C_RIVER, lw=0.9, alpha=0.85, zorder=4)

    boundary.boundary.plot(ax=ax, color=C_BOUND, lw=2.0, zorder=6)

    # Города
    for lat, lon, name, (dx, dy) in CITIES:
        p = gpd.GeoSeries.from_xy([lon], [lat], crs="EPSG:4326").to_crs(WEB)
        if not (xlim[0] < p.x[0] < xlim[1] and ylim[0] < p.y[0] < ylim[1]):
            continue
        ax.plot(p.x[0], p.y[0], marker="o", ms=3.4, mfc="white", mec="black",
                mew=0.7, zorder=9)
        ax.annotate(name, (p.x[0], p.y[0]), textcoords="offset points",
                    xytext=(dx, dy), fontsize=7.5, color="white", zorder=10,
                    path_effects=[pe.withStroke(linewidth=2.2, foreground="black")])

    # Три класса точек
    mars.plot(ax=ax, color=C_MARS, markersize=17, marker="s",
              edgecolor="black", linewidth=0.35, alpha=0.95, zorder=7)
    schuit.plot(ax=ax, color=C_SCHUIT, markersize=22, marker="D",
                edgecolor="black", linewidth=0.35, alpha=0.95, zorder=8)
    cat.plot(ax=ax, color=C_OURS, markersize=30, marker="^",
             edgecolor="black", linewidth=0.4, zorder=9)

    handles = [
        Line2D([], [], marker="^", color="none", markerfacecolor=C_OURS,
               markeredgecolor="black", markersize=8,
               label=f"Настоящий каталог ({len(cat)})"),
        Line2D([], [], marker="D", color="none", markerfacecolor=C_SCHUIT,
               markeredgecolor="black", markersize=7,
               label=f"Schuit et al., 2023 ({len(schuit)})"),
        Line2D([], [], marker="s", color="none", markerfacecolor=C_MARS,
               markeredgecolor="black", markersize=7,
               label=f"UNEP IMEO MARS ({len(mars)})"),
        Line2D([], [], color=C_BOUND, lw=2.0, label="Граница равнины"),
        Line2D([], [], color=C_ADMIN, lw=0.8, alpha=0.7,
               label="Административные границы"),
        Line2D([], [], color=C_RIVER, lw=1.0, label="Реки"),
        Line2D([], [], marker="o", color="none", markerfacecolor="white",
               markeredgecolor="black", markeredgewidth=0.7, markersize=5,
               label="Города"),
    ]
    leg = ax.legend(handles=handles, loc="upper right", fontsize=8,
                    framealpha=0.82, facecolor="white", edgecolor="#444444")
    leg.set_zorder(13)

    scalebar(ax, 300)

    # Координатная сетка по краю кадра
    import numpy as np
    from pyproj import Transformer
    tr = Transformer.from_crs("EPSG:4326", WEB, always_xy=True)
    inv = Transformer.from_crs(WEB, "EPSG:4326", always_xy=True)
    lon0, lat0 = inv.transform(xlim[0], ylim[0])
    lon1, lat1 = inv.transform(xlim[1], ylim[1])
    lons = [x for x in np.arange(60, 96, 5) if lon0 < x < lon1]
    lats = [y for y in np.arange(50, 76, 5) if lat0 < y < lat1]
    ax.set_xticks([tr.transform(x, (lat0 + lat1) / 2)[0] for x in lons])
    ax.set_xticklabels([f"{x}°в.д." for x in lons], fontsize=7.5)
    ax.yaxis.tick_right()
    ax.set_yticks([tr.transform((lon0 + lon1) / 2, y)[1] for y in lats])
    ax.set_yticklabels([f"{y}°с.ш." for y in lats], fontsize=7.5,
                       rotation=270, va="center")
    ax.tick_params(length=3, pad=2)
    for s in ax.spines.values():
        s.set_linewidth(0.8)

    # Стрелка севера
    nx, ny = 0.055, 0.945
    ax.annotate("", xy=(nx, ny), xytext=(nx, ny - 0.055),
                xycoords="axes fraction",
                arrowprops=dict(arrowstyle="-|>", linewidth=1.6,
                                facecolor="white", edgecolor="black"),
                zorder=13)
    ax.text(nx, ny + 0.006, "С", transform=ax.transAxes, ha="center",
            va="bottom", fontsize=11, fontweight="bold", color="white",
            zorder=13, path_effects=[pe.withStroke(linewidth=2.6, foreground="black")])

    ax.text(0.995, 0.004, "Подложка: Esri World Imagery", transform=ax.transAxes,
            ha="right", va="bottom", fontsize=6.5, color="white", zorder=12,
            path_effects=[pe.withStroke(linewidth=2, foreground="black")])

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "svg"):
        p = out_dir / f"fig2_catalog_map_300dpi.{ext}"
        fig.savefig(p, dpi=300, bbox_inches="tight", facecolor="white")
        print(f"  {p.name}: {p.stat().st_size // 1024} KB")
    plt.close(fig)


if __name__ == "__main__":
    main()
