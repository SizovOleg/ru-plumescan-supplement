"""Проверка внутренней согласованности публикуемого каталога.

Подтверждает числа, приведённые в README и METHODS, и — главное — проверяет,
что правило отнесения к артефактам применено ко всем годам единообразно,
несмотря на устаревшую метку `algorithm_version` у части записей.

Запуск не требует доступа к Earth Engine: проверяется опубликованный CSV.

    python code/py/supplement/verify_catalog.py [--data DIR]

Код возврата 0 — все проверки пройдены, 1 — есть расхождения.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List

ALBEDO_THRESHOLD = 0.5
SNOW_THRESHOLD = 0.5

results: List[str] = []
failed = False


def check(label: str, actual: Any, expected: Any) -> None:
    global failed
    ok = actual == expected
    if not ok:
        failed = True
    mark = "OK  " if ok else "FAIL"
    suffix = "" if ok else f"   (expected {expected!r}, got {actual!r})"
    results.append(f"[{mark}] {label}: {actual}{suffix}")


def load(path: Path) -> List[Dict[str, str]]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    args = ap.parse_args()

    rows = load(Path(args.data) / "catalog_ch4_west_siberia.csv")

    # --- Заявленные в документации числа ---------------------------------
    check("total events", len(rows), 122)
    check("unique event_id", len({r["event_id"] for r in rows}), 122)
    check("valid (artifact_likely=0)", sum(1 for r in rows if r["artifact_likely"] == "0"), 88)
    check("likely artefacts", sum(1 for r in rows if r["artifact_likely"] == "1"), 34)
    check("matched Schuit", sum(int(r["matched_schuit_150km"]) for r in rows), 7)
    check("matched MARS", sum(int(r["matched_mars_150km"]) for r in rows), 53)
    check("max z-score", round(max(float(r["max_z"]) for r in rows), 2), 85.47)
    check("flare-attributed", sum(1 for r in rows
                                  if r["nearest_source_type"].startswith("viirs_flare")), 96)
    check("gas fields", sum(1 for r in rows if r["nearest_source_type"] == "gas_field"), 25)
    check("event_class distribution",
          dict(Counter(r["event_class"] for r in rows)),
          {"wind_ambiguous": 78, "CH4_only": 43, "diffuse_CH4": 1})

    # --- Единообразие правила отнесения к артефактам ----------------------
    # Метка algorithm_version устарела у части записей; проверяем фактическое
    # правило пособытийно, а не по метке.
    def directional(r: Dict[str, str]) -> int:
        return int(float(r["corr_albedo"]) >= ALBEDO_THRESHOLD
                   or float(r["cluster_overlap_snow_fraction"]) > SNOW_THRESHOLD)

    def symmetric(r: Dict[str, str]) -> int:
        return int(abs(float(r["corr_albedo"])) >= ALBEDO_THRESHOLD
                   or float(r["cluster_overlap_snow_fraction"]) > SNOW_THRESHOLD)

    mismatched = [r["event_id"] for r in rows
                  if directional(r) != int(r["artifact_likely"])]
    check("events disagreeing with the directional rule", len(mismatched), 0)
    if mismatched:
        results.append("        " + ", ".join(mismatched[:10]))

    # Симметричное правило дало бы другой результат — подтверждает, что
    # применена именно направленная редакция, а не старая.
    check("artefacts the symmetric rule would give",
          sum(symmetric(r) for r in rows), 47)

    # Производные признаки должны быть согласованы с тем же правилом
    check("artifact_likely_albedo_positive mismatches",
          sum(1 for r in rows
              if (float(r["corr_albedo"]) >= ALBEDO_THRESHOLD)
              != (r["artifact_likely_albedo_positive"] == "1")), 0)
    check("surface_confounded_dark mismatches",
          sum(1 for r in rows
              if (float(r["corr_albedo"]) <= -ALBEDO_THRESHOLD)
              != (r["surface_confounded_dark"] == "1")), 0)

    # --- Область влияния известного дефекта ------------------------------
    defect = [r for r in rows if float(r["max_z"]) == 0.0]
    check("records with an uncomputed z-score", len(defect), 1)
    if len(defect) == 1:
        d = defect[0]
        check("  the affected record", d["event_id"], "CH4-WSP-017")
        check("  it is outside every cross-check metric",
              d["year"] not in ("2021", "2022", "2023", "2024", "2025"), True)
        check("  it is not counted as matched",
              d["matched_schuit_150km"] == "0" and d["matched_mars_150km"] == "0", True)

    # --- Пороги детекции --------------------------------------------------
    below = [r["event_id"] for r in rows
             if 0.0 < float(r["max_z"]) < 3.0]
    check("events below the z >= 3.0 threshold (excluding the sentinel)", len(below), 0)
    check("events smaller than 5 pixels",
          sum(1 for r in rows if int(r["n_pixels"]) < 5), 0)

    for line in results:
        print(line)
    print()
    if failed:
        print("RESULT: FAILED — the catalogue disagrees with the documented numbers")
        return 1
    print(f"RESULT: all {len(results)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
