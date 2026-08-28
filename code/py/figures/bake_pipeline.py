"""Структурная схема методики детектирования метановых шлейфов (рис. 1 статьи).

Компоновка: одна вертикальная ось из восьми пронумерованных шагов. Каждая
карточка разделена на полосу номера, описание операции и правую область
порогов — длинные русские строки не могут выйти за рамку конструктивно.
Вспомогательные данные подводятся сбоку к тем шагам, где применяются.

Холст задан в физических единицах (170 x 183 мм) и не обрезается при
сохранении, поэтому кегль на полосе журнала остаётся 7–9 pt.

Группы различаются светлотой заливки (Y = 246/236/223/212) и стилем рамки,
то есть читаются и в чёрно-белой печати.

Использование:
    python src/py/figures/bake_pipeline.py [--out DIR] [--check]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle, Circle

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


FIG_DIR = _layout()[0]

MM = 1 / 25.4
FIG_W_MM, FIG_H_MM = 170.0, 182.8

XMAX, YMIN, YMAX = 12.21, 0.10, 13.25
CX = 4.60
BW, BH = 7.30, 0.82

X_L = CX - BW / 2                 # левый край карточки
NUM_CX = X_L + 0.42               # центр кружка с номером
DESC_X = X_L + 0.86               # начало описания
SEP_X = 5.50                      # разделитель перед порогами
PAR_X = SEP_X + 0.18              # начало области порогов

# (заголовок, заливка, рамка, стиль рамки, толщина, x, y, высота)
GROUPS = [
    ("Исходные данные",          "#F4F6F8", "#4A6785", "solid",           0.8, 11.41, 1.38),
    ("Выделение аномалий",       "#E7EEE4", "#3F6E42", (0, (6, 2)),       0.9,  6.81, 4.02),
    ("Проверка и атрибуция",     "#F0DDC7", "#8C4B12", (0, (6, 2, 1, 2)), 0.9,  2.21, 4.02),
    ("Результат",                "#D9D1E4", "#5E4B8B", "solid",           1.3,  0.25, 1.38),
]

# (номер, y, описание, пороги, индекс группы)
STEPS = [
    (1, 12.10, "TROPOMI/Sentinel-5P\nпродукт L3",    "XCH₄, qa ≥ 0,5\nпоорбитно",     0),
    (2, 10.14, "Равновеликая сетка",                 "EPSG:6931\nшаг 5,5 км",         1),
    (3,  8.82, "Фон: медиана и MAD",                 "50–150 км\n≥ 50 пикс.",         1),
    (4,  7.50, "Кластеризация\nпревышений",          "z ≥ 3,0\n≥ 5 пикселей",         1),
    (5,  5.54, "Проверка по ветру",                  "ось ≤ 30°\nv ≥ 2 м/с",          2),
    (6,  4.22, "Диагностика\nартефактов",            "снег > 0,5\nr(альбедо) ±0,5",   2),
    (7,  2.90, "Атрибуция источника",                "радиус поиска\n50 км",          2),
    (8,  0.94, "Каталог событий",                    "122 события\n88 достоверных",   3),
]

# (подпись, y шага, сторона)
AUX = [
    ("Маска\nпромышленных зон\nи городов", 8.82, "right"),
    ("ERA5: ветер 10 м\nи 850 гПа",            5.54, "right"),
    ("MODIS: MCD43A4,\nMOD10A1",               4.22, "right"),
    ("VIIRS Nightfire:\nфакельные\nустановки",  2.90, "right"),
]

AUX_W, AUX_H = 2.66, 1.00
AUX_L_CX, AUX_R_CX = 2.20, 10.38


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(FIG_DIR))
    ap.add_argument("--check", action="store_true",
                    help="проверить, что подписи не выходят за рамки карточек")
    args = ap.parse_args()

    fig = plt.figure(figsize=(FIG_W_MM * MM, FIG_H_MM * MM), dpi=300)
    ax = fig.add_axes([0.01, 0.01, 0.98, 0.98])
    ax.set_xlim(0, XMAX)
    ax.set_ylim(YMIN, YMAX)
    ax.axis("off")

    group_titles = []
    ZX, ZW = X_L - 0.45, BW + 0.90
    for title, fc, ec, ls, lw, gy, gh in GROUPS:
        ax.add_patch(Rectangle((ZX, gy), ZW, gh, facecolor=fc, edgecolor=ec,
                               lw=lw, linestyle=ls, zorder=1))
        gt = ax.text(ZX, gy + gh + 0.10, title, fontsize=10.0,
                     fontweight="bold", color="#1A1A1A", va="bottom", ha="left",
                     zorder=2)
        group_titles.append((gt, CX - 0.30))

    # Стрелки потока — под карточками, поэтому не задевают подписи
    for cur, nxt in zip(STEPS, STEPS[1:]):
        ax.add_patch(FancyArrowPatch((CX, cur[1] - BH / 2 - 0.02),
                                     (CX, nxt[1] + BH / 2 + 0.02),
                                     arrowstyle="-|>", mutation_scale=8,
                                     lw=0.9, color="#1A1A1A", zorder=3))

    texts = []
    for n, y, desc, par, gi in STEPS:
        last = (n == 8)
        ax.add_patch(FancyBboxPatch(
            (X_L, y - BH / 2), BW, BH,
            boxstyle="round,pad=0.02,rounding_size=0.06",
            facecolor="#F4E3B2" if last else "#FFFFFF",
            edgecolor="#000000" if last else "#222222",
            lw=1.45 if last else 0.8, zorder=4))

        ax.add_patch(Circle((NUM_CX, y), 0.26, facecolor=GROUPS[gi][2],
                            edgecolor="none", zorder=5))
        ax.text(NUM_CX, y, str(n), fontsize=9.8, fontweight="bold",
                color="white", ha="center", va="center", zorder=6)

        texts.append((ax.text(DESC_X, y, desc, fontsize=10.0,
                              fontweight="bold" if last else "normal",
                              color="#1A1A1A", ha="left", va="center",
                              zorder=6, linespacing=1.12), SEP_X - 0.10))

        ax.add_patch(Rectangle((SEP_X + 0.05, y - BH / 2 + 0.06), 2.66, BH - 0.12,
                               facecolor="#F2F2F2", edgecolor="none", zorder=5))
        ax.plot([SEP_X, SEP_X], [y - BH / 2 + 0.08, y + BH / 2 - 0.08],
                color="#B0B0B0", lw=0.5, zorder=6)
        texts.append((ax.text(PAR_X, y, par, fontsize=9.3, color="#1A1A1A",
                              ha="left", va="center", zorder=6, linespacing=1.12),
                      X_L + BW - 0.08))

    for label, y, side in AUX:
        cxa = AUX_L_CX if side == "left" else AUX_R_CX
        ax.add_patch(FancyBboxPatch(
            (cxa - AUX_W / 2, y - AUX_H / 2), AUX_W, AUX_H,
            boxstyle="round,pad=0.02,rounding_size=0.05",
            facecolor="#F3F3F3", edgecolor="#666666", lw=0.8,
            linestyle=(0, (4, 2)), zorder=4))
        texts.append((ax.text(cxa, y, label, fontsize=9.1, color="#1A1A1A",
                              ha="center", va="center", zorder=6, linespacing=1.15),
                      cxa + AUX_W / 2 - 0.06))
        if side == "left":
            x_from, x_to = cxa + AUX_W / 2 + 0.06, X_L - 0.04
        else:
            x_from, x_to = cxa - AUX_W / 2 - 0.06, X_L + BW + 0.04
        ax.add_patch(FancyArrowPatch((x_from, y), (x_to, y), arrowstyle="-|>",
                                     mutation_scale=7, lw=0.8, color="#666666",
                                     linestyle=(0, (3, 2)), zorder=3))

    if args.check:
        fig.canvas.draw()
        rend = fig.canvas.get_renderer()
        bad = 0
        for t, x_limit in texts + group_titles:
            bb = t.get_window_extent(rend).transformed(ax.transData.inverted())
            if bb.x1 > x_limit + 1e-6:
                bad += 1
                print(f"  ПЕРЕПОЛНЕНИЕ: «{t.get_text()[:34]}» "
                      f"правый край {bb.x1:.2f} > предела {x_limit:.2f}")
        print(f"  проверка подписей: {'ОК' if not bad else str(bad) + ' переполнений'}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "svg"):
        p = out_dir / f"fig1_pipeline_300dpi.{ext}"
        fig.savefig(p, dpi=300, facecolor="white")   # без bbox_inches: размер фиксирован
        print(f"  {p.name}: {p.stat().st_size // 1024} KB")
    plt.close(fig)


if __name__ == "__main__":
    main()
